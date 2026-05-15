from django.db import transaction
from django.db.models import Q
from rest_framework import filters, mixins, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from datetime import timezone as dt_timezone
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ..utils.view_mixins import PaginatedResponseMixin
from ..models import Donation, Subscription
from ..serializers import DonationSerializer, QuotationRequestSerializer
from ..services.donation_service import create_donation
from ..services.etag_service import build_updated_at_etag, matches_if_match
from ..services.lalamove_service import get_lalamove_quotation
from ..services.claim_donation_service import claim_donation, sign_quotation_data
from ..services.audit_service import get_client_ip
from ..services.location_service import get_city_and_barangay


class DonationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, PaginatedResponseMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = DonationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['donation_id']


    def get_queryset(self):
        """Base queryset for all donation actions."""
        return Donation.objects.select_related(
            'donor',
            'donor__upload',
            'claimed_by_tuab',
            'claimed_by_tuab__upload',
            'upload',
        ).prefetch_related(
            'items__lookup',
        ).order_by('-submitted_at', '-donation_id')

    def list(self, request, *args, **kwargs):
        """Main 'Hall of Fame' list - Non-admins only see PENDING."""
        user = request.user
        queryset = self.get_queryset()

        if user.role != 'Admin':
            queryset = queryset.filter(status='PENDING')

        return self.get_paginated_response_data(queryset)

    def retrieve(self, request, *args, **kwargs):
        """Detail View - Privacy Guard logic."""
        instance = self.get_object()
        user = request.user

        # Non-admins: Cannot see ARCHIVED or other people's non-pending donations
        if user.role != 'Admin':
            if instance.status == 'ARCHIVED':
                return Response({"detail": "Not found."}, status=404)
            
            if instance.status != 'PENDING' and instance.donor != user and instance.claimed_by_tuab != user:
                return Response({"detail": "Access denied."}, status=403)

        serializer = self.get_serializer(instance)
        response = Response(serializer.data)
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

        return self.get_paginated_response_data(queryset)

    def create(self, request, *args, **kwargs):
        """Creates a new donation via the orchestrated service."""
        # Note: Only ACTIVE admins and ACTIVE donors are allowed to create.
        if request.user.status != 'ACTIVE' or request.user.role not in ['Admin', 'Donor']:
            return Response({"detail": "Only active admins and donors can create donations."}, status=403)

        try:
            donation = create_donation(request=request)
            response_serializer = DonationSerializer(donation, context={'request': request})
            response = Response(response_serializer.data, status=201)
            response['ETag'] = build_updated_at_etag(donation)
            return response
        except (ValueError, serializers.ValidationError) as e:
            if isinstance(e, serializers.ValidationError):
                return Response(e.detail, status=400)
            return Response({"detail": str(e)}, status=400)
        except Exception:
            return Response({"detail": "An unexpected error occurred during donation creation."}, status=500)

    @action(detail=True, methods=['post'])
    def quotation(self, request, pk=None):
        """Generates a delivery quotation via Lalamove for PRO TUABs."""
        donation = self.get_object()
        user = request.user

        # ETag Verification
        if_match = request.headers.get('If-Match')
        current_etag = build_updated_at_etag(donation)
        if if_match is None:
            return Response({"detail": "If-Match header is required."}, status=428)
        if not matches_if_match(current_etag, if_match):
            return Response({"detail": "ETag does not match the current resource version."}, status=412)

        # 1. Authorization: Role check
        if user.role != 'TUAB':
            return Response({"detail": "Only TUABs can request a delivery quotation."}, status=403)

        # 2. Authorization: Active PRO Subscription check
        now = timezone.now()
        has_pro = Subscription.objects.filter(user=user, subscription_tier='PRO', status='ACTIVE', end_date__gt=now).exists()
        if not has_pro:
            return Response({
                "error": "SUBSCRIPTION_INACTIVE",
                "detail": "An active PRO subscription is required to access delivery quotations."
            }, status=403)

        # 3. Authorization: Max Claims check
        claimed_count = Donation.objects.filter(claimed_by_tuab=user, status__in=['CLAIMED', 'IN_TRANSIT']).count()
        if claimed_count >= user.max_active_claims:
            return Response({
                "error": "MAX_CLAIMS_REACHED",
                "detail": f"You have reached your limit of {user.max_active_claims} active claims."
            }, status=409)

        # 4. Donation Availability Check
        if donation.status != 'PENDING':
            return Response({
                "error": "DONATION_UNAVAILABLE",
                "detail": "Quotations can only be generated for donations with status 'PENDING'."
            }, status=409)

        # 5. Request Validation using Serializer
        serializer = QuotationRequestSerializer(data=request.data, context={'request': request, 'donation': donation})
        serializer.is_valid(raise_exception=True)
        
        v_data = serializer.validated_data
        dropoff_lat = "{:.7f}".format(v_data['dropoff_latitude'])
        dropoff_lng = "{:.7f}".format(v_data['dropoff_longitude'])
        dropoff_address = v_data['dropoff_display_address']
        scheduled_time = v_data['scheduled_time']
        # --- MANILA-FIRST LOCALIZATION ---
        # 1. Convert the UTC date to Manila local time
        # 2. Replace the hours/minutes with the user's selected window
        schedule_at = timezone.localtime(donation.preferred_pickup_date).replace(
            hour=scheduled_time.hour,
            minute=scheduled_time.minute,
            second=scheduled_time.second,
            microsecond=0,
        )
        
        # Lalamove requires ISO 8601 with Z for UTC, so we convert it back
        schedule_at_str = schedule_at.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # 6. Call Lalamove Service
        result = get_lalamove_quotation(
            pickup_lat=donation.pickup_latitude,
            pickup_lng=donation.pickup_longitude,
            pickup_address=donation.pickup_display_address or "N/A",
            dropoff_lat=dropoff_lat,
            dropoff_lng=dropoff_lng,
            dropoff_address=dropoff_address,
            schedule_at=schedule_at_str
        )

        if "error" in result:
            # If Lalamove returns an error (e.g. out of service area), pass it along
            lalamove_error = result["error"]
            if isinstance(lalamove_error, dict) and lalamove_error.get('errors'):
                detail = ' '.join(
                    item.get('message') or item.get('detail')
                    for item in lalamove_error['errors']
                    if isinstance(item, dict) and (item.get('message') or item.get('detail'))
                ) or "Lalamove rejected the quotation request."
            elif isinstance(lalamove_error, list):
                detail = ' '.join(str(item) for item in lalamove_error) or "Lalamove rejected the quotation request."
            else:
                detail = str(lalamove_error)

            if "scheduleAt" in detail and "past date or more than 30 days in advance" in detail:
                detail = "The donation's scheduled pickup time is no longer valid for delivery quotations. Choose a donation with a future pickup schedule within the next 30 days."

            return Response({
                "error": "LALAMOVE_API_ERROR",
                "detail": detail
            }, status=result.get("status_code", 400))

        # 7. Format and return response
        data = result.get("data", {})
        stops = data.get("stops", [])
        total_price = data.get("priceBreakdown", {}).get("total")
        quotation_id = data.get("quotationId")
        stop_id_1 = stops[0].get("stopId") if len(stops) > 0 else None
        stop_id_2 = stops[1].get("stopId") if len(stops) > 1 else None
        expires_at = int(parse_datetime(data.get("expiresAt")).timestamp())

        # Generate a signed token (Source of Truth)
        quotation_token = sign_quotation_data({
            "amount": total_price,
            "quotationId": quotation_id,
            "stopId_1": stop_id_1,
            "stopId_2": stop_id_2,
            "schedule_at": schedule_at_str,
            "expires_at": expires_at
        })
        
        return Response({
            "total_price": total_price,
            "quotationId": quotation_id,
            "stopId_1": stop_id_1,
            "stopId_2": stop_id_2,
            "schedule_at": schedule_at_str,
            "expires_at": expires_at,
            "quotation_token": quotation_token
        })

    @action(detail=True, methods=['post'])
    def claim(self, request, pk=None):
        """Claims a donation for a TUAB."""
        donation = self.get_object()
        user = request.user

        # 1. Role Check
        if user.role != 'TUAB':
            return Response({"detail": "Only TUABs can claim donations."}, status=403)

        # 2. ETag Verification
        if_match = request.headers.get('If-Match')
        current_etag = build_updated_at_etag(donation)
        if if_match is None:
            return Response({"detail": "If-Match header is required."}, status=428)
        if not matches_if_match(current_etag, if_match):
            return Response({"detail": "ETag does not match the current resource version."}, status=412)

        # 3. Authorization: Active PRO Subscription check (Required for both methods)
        now = timezone.now()
        has_pro = Subscription.objects.filter(user=user, subscription_tier='PRO', status='ACTIVE', end_date__gt=now).exists()
        if not has_pro:
            return Response({
                "error": "SUBSCRIPTION_INACTIVE",
                "detail": "An active PRO subscription is required to claim donations."
            }, status=403)

        # 4. Request Data
        delivery_method = request.data.get('delivery_method')
        if delivery_method not in ['PICKUP', 'DELIVERY']:
            return Response({"detail": "Invalid delivery_method. Must be 'PICKUP' or 'DELIVERY'."}, status=400)

        claim_params = {
            'delivery_method': delivery_method,
            'quotation_token': request.data.get('quotation_token'),
        }

        # 5. Call Service
        ip_address = get_client_ip(request)
        result = claim_donation(
            user=user, 
            donation=donation, 
            claim_params=claim_params,
            ip_address=ip_address
        )
        
        if result["status_code"] != 200:
            return Response({"detail": result["detail"]}, status=result["status_code"])
            
        return Response(result, status=200)
