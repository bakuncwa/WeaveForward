from django.db.models import Prefetch, Q
from datetime import datetime, time
from django_filters.rest_framework import DjangoFilterBackend, FilterSet, DateTimeFilter, DateFilter
from rest_framework import filters, mixins, viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rest_framework.exceptions import PermissionDenied, APIException, NotFound, ValidationError

from datetime import timezone as dt_timezone
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ..utils.view_mixins import PaginatedResponseMixin
from ..models import Donation, DonationItem, Subscription, SubscriptionStatus, User, UserRole
from ..permissions import (
    IsActiveAdmin,
    IsActiveAdminOrDonor,
    IsActiveAdminOrTUAB,
    IsActiveTUAB,
)
from ..serializers import DonationDetailSerializer, DonationListSerializer, QuotationRequestSerializer, DonorDonationUpdateSerializer, DonationResolveSerializer
from ..services.donation_service import (
    create_donation, mark_donation_in_transit, donor_update_donation,
    admin_update_donation, cancel_donation, archive_donation,
    resolve_donation, claim_donation, sign_quotation_data,
    _extract_external_error_message,
)
from ..services.etag_service import build_updated_at_etag, matches_if_match
from ..services.lalamove_service import get_lalamove_quotation
from ..services.audit_service import get_client_ip, log_audit
from ..services.email_service import send_flag_notification
from ..services.location_service import get_city_and_barangay


class DonationFilterSet(FilterSet):
    preferred_pickup_date__gte = DateFilter(field_name='preferred_pickup_date', lookup_expr='gte')
    preferred_pickup_date__lte = DateFilter(method='filter_lte')

    def filter_lte(self, queryset, name, value):
        gte = self.data.get('preferred_pickup_date__gte')
        if gte and gte > value.isoformat():
            raise ValidationError({"preferred_pickup_date__lte": "End date cannot be before start date."})
        return queryset.filter(preferred_pickup_date__lte=timezone.make_aware(datetime.combine(value, time.max)))

    class Meta:
        model = Donation
        fields = ['preferred_pickup_date__gte', 'preferred_pickup_date__lte']


class DonationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, PaginatedResponseMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = DonationDetailSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = DonationFilterSet
    ordering_fields = ['donation_id', 'is_flagged', 'claimed_by_tuab__business_name', 'status', 'preferred_pickup_date', 'pickup_display_address']
    search_fields = [
        'donor__email', 
        'donor__first_name', 
        'donor__last_name', 
        'claimed_by_tuab__business_name', 
        'claimed_by_tuab__email',
        'items__lookup__brand',
        'items__lookup__clothing_type',
        'items__lookup__dominant_fiber',
        'items__condition_rating',
    ]

    def get_permissions(self):
        permission_map = {
            'create': [IsActiveAdminOrDonor],
            'partial_update': [IsActiveAdminOrDonor],
            'quotation': [IsActiveTUAB],
            'claim': [IsActiveTUAB],
            'transit': [IsActiveTUAB],
            'resolve': [IsActiveTUAB],
            'cancel': [IsActiveAdminOrDonor],
            'archive': [IsActiveAdmin],
            'flag': [IsActiveAdminOrTUAB],
        }
        if self.action in permission_map:
            return [permission() for permission in permission_map[self.action]]
        return super().get_permissions()

    def get_serializer_class(self):
        if getattr(self, 'action', None) in ['list', 'me']:
            return DonationListSerializer
        return DonationDetailSerializer

    def get_queryset(self):
        """Base queryset for all donation actions."""
        # ORM loading strategy:
        # - select_related(...) tells Django to use JOINs for single-valued relations
        #   like donor, claimed_by_tuab, and upload so those objects come back with
        #   the donation row in one main query.
        # - prefetch_related(Prefetch(...)) tells Django to run separate bulk queries
        #   for the active DonationItem rows and their BrandFiberLookup rows, then
        #   stitch them onto each donation in Python.
        #
        # SQL shape (simplified):
        #   1)
        #   SELECT donations.*, donor.*, donor_upload.*, claimed.*, claimed_upload.*, upload.*
        #   FROM donations
        #   LEFT JOIN users AS donor ON donations.donor_id = donor.user_id
        #   LEFT JOIN uploads AS donor_upload ON donor.upload_id = donor_upload.upload_id
        #   LEFT JOIN users AS claimed ON donations.claimed_by_tuab_id = claimed.user_id
        #   LEFT JOIN uploads AS claimed_upload ON claimed.upload_id = claimed_upload.upload_id
        #   LEFT JOIN uploads AS upload ON donations.upload_id = upload.upload_id
        #   ORDER BY donations.submitted_at DESC, donations.donation_id DESC;
        #
        #   2)
        #   SELECT donation_items.*, brand_fiber_lookups.*
        #   FROM donation_items
        #   LEFT JOIN brand_fiber_lookups
        #     ON donation_items.lookup_id = brand_fiber_lookups.lookup_id
        #   WHERE donation_items.is_archived = FALSE
        #     AND donation_items.donation_id IN (...returned donation ids...);
        #
        # The serializer reads the prefetched active_items list directly.
        return Donation.objects.select_related(
            'donor',
            'donor__upload',
            'claimed_by_tuab',
            'claimed_by_tuab__upload',
            'upload',
        ).prefetch_related(
            Prefetch(
                'items',
                queryset=DonationItem.objects.filter(is_archived=False).select_related('lookup'),
                to_attr='active_items',
            ),
        ).order_by('-updated_at')

    def list(self, request, *args, **kwargs):
        """Main 'Hall of Fame' list - Non-admins only see PENDING."""
        # Query plan notes:
        # - get_queryset() builds a lazy Django queryset; no SQL is sent yet.
        # - filter(status='PENDING') and filter_queryset(...) only add conditions to
        #   that queryset object.
        # - The first real SQL round-trip happens when pagination evaluates the queryset.
        # - Because get_queryset() includes select_related(...) and a filtered Prefetch(...)
        #   Django will fetch donation rows plus the single-valued relations in the main query,
        #   then fetch only active donation_items and their lookup rows in a separate prefetch query.
        # - The serializer reads the prefetched active_items list directly.
        # - So the endpoint is not just "one list query"; it is a main donation query plus
        #   nested item hydration work driven by the serializer.
        #
        # Complexity notes:
        # - Let n = number of matching donations.
        # - Let k = average number of active items per donation.
        # - The list endpoint is O(n * k) because each returned donation still needs
        #   its active items serialized.
        queryset = self.get_queryset()

        # 1. Security Rule (Hard-coded)
        if request.user.role != 'Admin':
            queryset = queryset.filter(status='PENDING')

        # 2. Automated Filtering (Handles ?search and ?status from URL)
        queryset = self.filter_queryset(queryset)

        return self.get_paginated_response_data(queryset)

    def retrieve(self, request, *args, **kwargs):
        """Detail View - Privacy Guard logic."""
        instance = self.get_object()
        user = request.user

        # Non-admins: Cannot see ARCHIVED or other people's non-pending donations
        if user.role != 'Admin':
            if instance.status == 'ARCHIVED':
                raise NotFound("Donation not found.")
            
            if instance.status != 'PENDING' and instance.donor != user and instance.claimed_by_tuab != user:
                raise PermissionDenied("Access denied.")

        serializer = self.get_serializer(instance)
        data = serializer.data
        if user.role != 'Admin' and user != instance.donor and instance.claimed_by_tuab != user:
            if isinstance(data.get('donor'), dict):
                data['donor'].pop('email', None)
                data['donor'].pop('contact_no', None)
        response = Response(data)
        response['ETag'] = build_updated_at_etag(instance)
        return response

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Personal History - Shows everything owned/claimed by user."""
        user = request.user
        queryset = self.get_queryset()

        if user.role == 'Donor':
            queryset = queryset.filter(donor=user)
        elif user.role == 'TUAB':
            queryset = queryset.filter(claimed_by_tuab=user)
        elif user.role != 'Admin':
            queryset = queryset.none()

        # Still exclude ARCHIVED for everyone except Admin
        if user.role != 'Admin':
            queryset = queryset.exclude(status='ARCHIVED')

        queryset = self.filter_queryset(queryset)
        return self.get_paginated_response_data(queryset)

    def create(self, request, *args, **kwargs):
        """Creates a new donation via the orchestrated service."""
        # Note: Only ACTIVE admins and ACTIVE donors are allowed to create.
        # Complexity notes:
        # - Let n = number of submitted donation items.
        # - Let i = number of active items used by prediction inference.
        # - Let t = number of eligible TUAB users.
        # - Cost is O(n + i * t) because prediction generation builds
        #   every active-item / TUAB pair.
        try:
            donation = create_donation(request=request)
        except (ValueError, serializers.ValidationError) as e:
            if isinstance(e, serializers.ValidationError):
                raise
            exc = APIException(str(e))
            exc.status_code = 400
            raise exc

        response_serializer = DonationDetailSerializer(donation, context={'request': request})
        response = Response(response_serializer.data, status=201)
        response['ETag'] = build_updated_at_etag(donation)
        return response

    def partial_update(self, request, *args, **kwargs):
        """Update a donation - Restricted to Donor (PENDING only)."""
        # Complexity notes:
        # - Let m = number of submitted item patches.
        # - Let i = number of active items used by prediction inference.
        # - Let t = number of eligible TUAB users.
        # - Item patch processing is O(m).
        # - If predictions are rerun, the dominant cost is O(i * t).
        # - Overall worst case: O(m + i * t).
        user = request.user
        donation = Donation.objects.filter(pk=kwargs.get('pk')).first()
        if not donation:
            raise NotFound("Donation not found.")

        if_match = request.headers.get('If-Match')
        if not if_match or not matches_if_match(build_updated_at_etag(donation), if_match):
            exc = APIException("Your session has expired. Please refresh the page and try again.")
            exc.status_code = 412
            raise exc

        if user.role == 'Admin':
            if donation.status == 'ARCHIVED':
                exc = APIException("Donations in archived status are immutable.")
                exc.status_code = 409
                raise exc

            try:
                updated_donation = admin_update_donation(request=request, donation=donation)
            except (ValueError, serializers.ValidationError) as e:
                if isinstance(e, serializers.ValidationError):
                    raise
                exc = APIException(str(e))
                exc.status_code = 400
                raise exc
        else:
            if donation.donor != user:
                raise PermissionDenied("You can only edit donations that you created.")
            if donation.status != 'PENDING':
                exc = APIException(f"This donation cannot be modified because its current status is {donation.status.lower().replace('_', ' ')}.")
                exc.status_code = 409
                raise exc
            try:
                updated_donation = donor_update_donation(request=request, donation=donation)
            except (ValueError, serializers.ValidationError) as e:
                if isinstance(e, serializers.ValidationError):
                    raise
                exc = APIException(str(e))
                exc.status_code = 400
                raise exc

        serializer = DonationDetailSerializer(updated_donation, context={'request': request})
        response = Response(serializer.data)
        response['ETag'] = build_updated_at_etag(updated_donation)
        return response

    @action(detail=True, methods=['post'])
    def quotation(self, request, pk=None):
        """Generates a delivery quotation via Lalamove for PRO TUABs."""
        donation = self.get_object()
        user = request.user

        # Request freshness
        if_match = request.headers.get('If-Match')
        if not if_match or not matches_if_match(build_updated_at_etag(donation), if_match):
            exc = APIException("Your session has expired. Please refresh the page and try again.")
            exc.status_code = 412
            raise exc

        # 2. Authorization: Active PRO Subscription check
        now = timezone.now()
        has_pro = Subscription.objects.filter(user=user, subscription_tier='PRO', status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED], end_date__gt=now).exists()
        if not has_pro:
            raise PermissionDenied({
                "error": "SUBSCRIPTION_INACTIVE",
                "detail": "Subscribe first to get a delivery price."
            })

        # 3. Authorization: Max Claims check
        claimed_count = Donation.objects.filter(claimed_by_tuab=user, status__in=['CLAIMED', 'IN_TRANSIT']).count()
        if claimed_count >= user.max_active_claims:
            exc = APIException({
                "error": "MAX_CLAIMS_REACHED",
                "detail": f"You have reached your limit of {user.max_active_claims} active claims."
            })
            exc.status_code = 409
            raise exc

        # Donation eligibility
        if donation.status != 'PENDING':
            exc = APIException({
                "error": "DONATION_UNAVAILABLE",
                "detail": "Quotations can only be generated for donations with status 'PENDING'."
            })
            exc.status_code = 409
            raise exc

        # Request validation
        serializer = QuotationRequestSerializer(data=request.data, context={'request': request, 'donation': donation})
        serializer.is_valid(raise_exception=True)

        v_data = serializer.validated_data
        schedule_at = timezone.localtime(donation.preferred_pickup_date).replace(
            hour=v_data['scheduled_time'].hour,
            minute=v_data['scheduled_time'].minute,
            second=v_data['scheduled_time'].second,
            microsecond=0,
        )
        if schedule_at <= timezone.now():
            now_local = timezone.localtime(timezone.now())
            schedule_at = now_local.replace(
                hour=v_data['scheduled_time'].hour,
                minute=v_data['scheduled_time'].minute,
                second=v_data['scheduled_time'].second,
                microsecond=0,
            )
            if schedule_at <= now_local:
                exc = APIException("Donor's Preferred Time Window has already passed today. Please choose a later time.")
                exc.status_code = 409
                raise exc

        quote_request = {
            "dropoff_lat": "{:.7f}".format(v_data['dropoff_latitude']),
            "dropoff_lng": "{:.7f}".format(v_data['dropoff_longitude']),
            "dropoff_address": v_data['dropoff_display_address'],
            "schedule_at": schedule_at,
        }
        quote_request["schedule_at_str"] = quote_request["schedule_at"].astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        result = get_lalamove_quotation(
            pickup_lat=donation.pickup_latitude,
            pickup_lng=donation.pickup_longitude,
            pickup_address=donation.pickup_display_address or "N/A",
            dropoff_lat=quote_request["dropoff_lat"],
            dropoff_lng=quote_request["dropoff_lng"],
            dropoff_address=quote_request["dropoff_address"],
            schedule_at=quote_request["schedule_at_str"],
        )

        if "error" in result:
            exc = APIException({
                "error": "LALAMOVE_API_ERROR",
                "detail": _extract_external_error_message(result["error"])
            })
            exc.status_code = result.get("status_code", 400)
            raise exc

        quote_data = result.get("data") or {}
        stops = quote_data["stops"]
        response_data = {
            "total_price": quote_data["priceBreakdown"]["total"],
            "quotationId": quote_data["quotationId"],
            "stopId_1": stops[0]["stopId"],
            "stopId_2": stops[1]["stopId"],
            "schedule_at": quote_request["schedule_at_str"],
            "expires_at": int(parse_datetime(quote_data["expiresAt"]).timestamp()),
        }
        response_data["quotation_token"] = sign_quotation_data({
            "amount": response_data["total_price"],
            "quotationId": response_data["quotationId"],
            "stopId_1": response_data["stopId_1"],
            "stopId_2": response_data["stopId_2"],
            "dropoff_address": quote_request["dropoff_address"],
            "dropoff_latitude": quote_request["dropoff_lat"],
            "dropoff_longitude": quote_request["dropoff_lng"],
            "schedule_at": response_data["schedule_at"],
            "expires_at": response_data["expires_at"],
        })

        return Response(response_data)

    @action(detail=True, methods=['post'])
    def claim(self, request, pk=None):
        """Claims a donation for a TUAB."""
        donation = self.get_object()
        user = request.user

        # 2. ETag Verification
        if_match = request.headers.get('If-Match')
        if not if_match or not matches_if_match(build_updated_at_etag(donation), if_match):
            exc = APIException("Your session has expired. Please refresh the page and try again.")
            exc.status_code = 412
            raise exc

        # 3. Request Data
        delivery_method = request.data.get('delivery_method')
        if delivery_method not in ['PICKUP', 'DELIVERY']:
            exc = APIException("Delivery method must be either PICKUP or DELIVERY.")
            exc.status_code = 400
            raise exc

        # 4. Authorization: Active PRO Subscription check (Required for DELIVERY only)
        if delivery_method == 'DELIVERY':
            now = timezone.now()
            has_pro = Subscription.objects.filter(user=user, subscription_tier='PRO', status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED], end_date__gt=now).exists()
            if not has_pro:
                raise PermissionDenied({
                    "error": "SUBSCRIPTION_INACTIVE",
                    "detail": "Subscribe first to claim donations for delivery."
                })

        quotation_token = request.data.get('quotation_token')

        claim_params = {
            'delivery_method': delivery_method,
            'quotation_token': quotation_token,
        }

        # 5. Call Service
        ip_address = get_client_ip(request)
        result = claim_donation(
            user=user, 
            donation=donation, 
            claim_params=claim_params,
            ip_address=ip_address
        )
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def transit(self, request, pk=None):
        """Marks a donation as in-transit."""
        donation = self.get_object()
        user = request.user
        ip_address = get_client_ip(request)
        
        result = mark_donation_in_transit(
            user=user,
            donation=donation,
            ip_address=ip_address
        )
        
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancels a donation."""
        # Retrieve the donation instance from database using view set lookup
        donation = self.get_object()
        # Extract authenticated user executing request
        user = request.user
        # Resolve real client IP address for the audit log
        ip_address = get_client_ip(request)
        # Execute orchestrated donation cancellation service logic raising standard DRF exceptions
        result = cancel_donation(user=user, donation=donation, ip_address=ip_address)
        # Return successful cancellation details with 200 OK status
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archives a donation (Admin-only)."""
        # Retrieve the donation instance using view set lookup
        donation = self.get_object()
        # Extract authenticated user executing request
        user = request.user
        # Resolve real client IP address for the audit log
        ip_address = get_client_ip(request)
        # Execute orchestrated donation archiving service logic raising standard DRF exceptions
        result = archive_donation(user=user, donation=donation, ip_address=ip_address)
        # Return successful archiving details with 200 OK status
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Resolves a donation by marking it as RECEIVED or REJECTED."""
        user = request.user
        donation = self.get_object()

        # Request freshness
        if_match = request.headers.get('If-Match')
        if not if_match or not matches_if_match(build_updated_at_etag(donation), if_match):
            exc = APIException("Your session has expired. Please refresh the page and try again.")
            exc.status_code = 412
            raise exc

        # Authorization checks
        if donation.claimed_by_tuab != user:
            raise PermissionDenied("You can only resolve donations claimed by your own business.")

        (serializer := DonationResolveSerializer(data=request.data, context={'donation': donation})).is_valid(raise_exception=True)
        
        result = resolve_donation(
            user=user,
            donation=donation,
            validated_data=serializer.validated_data,
            ip_address=get_client_ip(request)
        )

        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def flag(self, request, pk=None):
        """Flags a donation with a reason. Allowed for TUAB (claimed donations) and Admin."""
        user = request.user
        donation = self.get_object()

        if donation.status == 'ARCHIVED':
            exc = APIException("Archived donations cannot be flagged.")
            exc.status_code = 409
            raise exc

        if user.role == 'TUAB' and donation.status not in ('PENDING', 'FLAGGED'):
            exc = APIException("Only pending or already-flagged donations can be flagged for archiving.")
            exc.status_code = 409
            raise exc

        reason = (request.data.get('flag_reason') or '').strip()
        if not reason:
            exc = APIException("A flag reason is required.")
            exc.status_code = 400
            raise exc
        was_already_flagged = donation.is_flagged
        donation.is_flagged = True
        donation.flag_reason = reason
        donation.save(update_fields=['is_flagged', 'flag_reason', 'updated_at'])
        log_audit(actor=user, entity_type='Donation', action='FLAG_DONATION',
                  fields_modified='is_flagged,flag_reason', ip_address=get_client_ip(request))

        if not was_already_flagged:
            try:
                admin_emails = list(User.objects.filter(
                    role=UserRole.ADMIN, status='ACTIVE',
                ).values_list('email', flat=True))
                if admin_emails:
                    send_flag_notification(
                        admin_emails=admin_emails,
                        donation_id=donation.pk,
                        flag_reason=reason,
                        flagged_by_name=user.business_name or user.email,
                        donor_name=donation.donor.first_name or donation.donor.email,
                        pickup_city=donation.pickup_city,
                    )
            except Exception:
                pass

        return Response({'detail': f'Donation #{donation.pk} has been flagged.'}, status=status.HTTP_200_OK)
