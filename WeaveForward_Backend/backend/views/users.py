import pyotp
from django.db.models import Exists, OuterRef
from django.db import transaction
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from ..utils.view_mixins import PaginatedResponseMixin

from ..models import Subscription, SubscriptionStatus, User, UserRole, UserAccountStatus, UserOperationalStatus
from ..serializers import (
    PublicUserSerializer, 
    UserSerializer, 
    TwoFactorSerializer,
    SubscribeSetupSerializer,
    DonorRegisterSerializer, 
    TUABRegisterSerializer
)
from ..services.audit_service import get_client_ip, log_audit
from ..services.etag_service import build_updated_at_etag, matches_if_match
from ..services.two_factor_service import disable_two_factor, enable_two_factor
from ..services.user_archive_service import archive_user
from ..services.subscription_service import subscribe_user, unsubscribe_user
from ..services.location_service import haversine



class UserViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, PaginatedResponseMixin):
    filter_backends = [filters.SearchFilter]
    search_fields = ['email', 'first_name', 'last_name']
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_serializer_class(self):
        if hasattr(self, 'request') and hasattr(self.request, 'user'):
            if self.request.user.role != 'Admin' and self.action in ['list', 'retrieve']:
                return PublicUserSerializer
        return UserSerializer

    def get_queryset(self):
        # We define a broad queryset here; the list/retrieve methods handle the role-based blocking
        active_subscriptions = Subscription.objects.filter(
            user=OuterRef('pk'),
            status=SubscriptionStatus.ACTIVE,
        )
        return (
            User.objects.select_related('upload', 'documentation')
            .annotate(is_subscribed=Exists(active_subscriptions))
            .order_by('user_id')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        
        # Capture filter params
        user_lat = request.query_params.get('lat')
        user_lng = request.query_params.get('lng')
        category = request.query_params.get('category')

        if request.user.is_authenticated and request.user.role == UserRole.ADMIN:
            role_filter = request.query_params.get('role')
            status_filter = request.query_params.get('status')
            if role_filter:
                queryset = queryset.filter(role=role_filter)
            if status_filter:
                queryset = queryset.filter(status=status_filter)
        else:
            queryset = queryset.filter(role=UserRole.TUAB, status='ACTIVE', operational_status='ACTIVE')
        
        if category:
            queryset = queryset.filter(target_fibers__icontains=category)

        # Convert queryset to list if we need to calculate distance (DRF pagination handles lists too)
        results = list(queryset)

        if user_lat and user_lng:
            for u in results: u.distance_km = haversine(user_lng, user_lat, u.longitude, u.latitude) if (u.latitude and u.longitude) else None
            results.sort(key=lambda x: x.distance_km if x.distance_km is not None else float('inf'))

        return self.get_paginated_response_data(results)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.user.role != UserRole.ADMIN:
            if (
                instance.role != UserRole.TUAB
                or instance.status != UserAccountStatus.ACTIVE
                or instance.operational_status != UserOperationalStatus.ACTIVE
            ):
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        response = super().retrieve(request, *args, **kwargs)
        response['ETag'] = build_updated_at_etag(instance)
        return response

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.user.role != UserRole.ADMIN and instance.user_id != request.user.user_id:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if instance.status != UserAccountStatus.ACTIVE:
            return Response(
                {"detail": "Only active users can be edited."},
                status=status.HTTP_409_CONFLICT
            )

        if_match = request.headers.get('If-Match')
        current_etag = build_updated_at_etag(instance)
        if if_match is None:
            return Response({"detail": "If-Match header is required."}, status=status.HTTP_428_PRECONDITION_REQUIRED)
        if not matches_if_match(current_etag, if_match):
            return Response({"detail": "ETag does not match the current resource version."}, status=status.HTTP_412_PRECONDITION_FAILED)

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        fields_modified = list(serializer.validated_data.keys())
        if instance.role == UserRole.TUAB:
            critical = ['max_distance_km', 'min_biodeg_score', 'target_fibers', 'latitude', 'longitude', 'display_address']
            # Put critical fields at the FRONT so they are prioritized before the 100-char cutoff
            fields_modified = critical + [f for f in fields_modified if f not in critical]

        ip_address = get_client_ip(request)
        with transaction.atomic():
            user = serializer.save()
            log_audit(
                actor=request.user,
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                ip_address=ip_address,
                fields_modified=fields_modified or None
            )

        response = Response(self.get_serializer(user).data, status=status.HTTP_200_OK)
        response['ETag'] = build_updated_at_etag(user)
        return response

    @action(detail=False, methods=['get'])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        response = Response(serializer.data)
        response['ETag'] = build_updated_at_etag(request.user)
        return response

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        if request.user.role != UserRole.ADMIN:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        status_input = request.data.get('status')
        rejection_reason = request.data.get('rejection_reason')

        if status_input not in [UserAccountStatus.ACTIVE, UserAccountStatus.REJECTED]:
            return Response({"detail": "Invalid status. Must be ACTIVE or REJECTED."}, status=status.HTTP_400_BAD_REQUEST)

        if status_input == UserAccountStatus.REJECTED:
            if not rejection_reason or not str(rejection_reason).strip():
                return Response({"detail": "Rejection reason is required when rejecting a TUAB."}, status=status.HTTP_400_BAD_REQUEST)
            
            max_len = User._meta.get_field('rejection_reason').max_length
            if len(rejection_reason) > max_len:
                return Response({"detail": f"Rejection reason is too long (max {max_len} characters)."}, status=status.HTTP_400_BAD_REQUEST)

        ip_address = get_client_ip(request)
        with transaction.atomic():
            try:
                target_user = (
                    User.objects.select_for_update()
                    .select_related('upload', 'documentation')
                    .get(pk=pk)
                )
            except User.DoesNotExist:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

            if target_user.role != UserRole.TUAB:
                return Response({"detail": "Only TUAB users can be reviewed via this endpoint."}, status=status.HTTP_409_CONFLICT)

            if target_user.status != UserAccountStatus.UNDER_REVIEW:
                return Response({"detail": "Only TUAB users under review can be reviewed."}, status=status.HTTP_409_CONFLICT)

            if status_input == UserAccountStatus.REJECTED:
                target_user.status = UserAccountStatus.REJECTED
                target_user.rejection_reason = rejection_reason
            else:
                target_user.status = UserAccountStatus.ACTIVE
                target_user.rejection_reason = None
            
            target_user.save(update_fields=['status', 'rejection_reason', 'updated_at'])

            log_audit(
                actor=request.user,
                entity_type='users',
                action='STATUS_CHANGE',
                ip_address=ip_address,
                fields_modified=['status', 'rejection_reason'] if status_input == UserAccountStatus.REJECTED else ['status']
            )

        response = Response(self.get_serializer(target_user).data, status=status.HTTP_200_OK)
        response['ETag'] = build_updated_at_etag(target_user)
        return response

    @action(detail=False, methods=['post'], url_path='me/2fa/setup')
    def two_factor_setup(self, request):
        secret = pyotp.random_base32()
        provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
            name=request.user.email,
            issuer_name="WeaveForward"
        )
        return Response(
            {
                "secret": secret,
                "provisioning_uri": provisioning_uri,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post', 'delete'], url_path='me/2fa')
    def my_two_factor(self, request):
        if request.method == 'POST':
            serializer = TwoFactorSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            ip_address = get_client_ip(request)
            result = enable_two_factor(
                target_user=request.user,
                secret=serializer.validated_data['secret']
            )
            log_audit(
                actor=request.user,
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                ip_address=ip_address,
                fields_modified=result['fields_modified']
            )
            return Response({"message": result["detail"]}, status=status.HTTP_200_OK)

        ip_address = get_client_ip(request)
        result = disable_two_factor(target_user=request.user)
        log_audit(
            actor=request.user,
            entity_type='users',
            action='CREDENTIAL_UPDATE',
            ip_address=ip_address,
            fields_modified=result['fields_modified']
        )
        return Response({"message": result["detail"]}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post', 'delete'], url_path='2fa')
    def two_factor(self, request, pk=None):
        target_user = self.get_object()

        if request.method == 'POST':
            if request.user.user_id != target_user.user_id:
                return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

            serializer = TwoFactorSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            ip_address = get_client_ip(request)
            result = enable_two_factor(
                target_user=target_user,
                secret=serializer.validated_data['secret']
            )
            log_audit(
                actor=request.user,
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                ip_address=ip_address,
                fields_modified=result['fields_modified']
            )

            return Response({"message": result["detail"]}, status=status.HTTP_200_OK)

        if request.user.role != UserRole.ADMIN and request.user.user_id != target_user.user_id:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        ip_address = get_client_ip(request)
        result = disable_two_factor(target_user=target_user)
        log_audit(
            actor=request.user,
            entity_type='users',
            action='CREDENTIAL_UPDATE',
            ip_address=ip_address,
            fields_modified=result['fields_modified']
        )
        return Response({"message": result["detail"]}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], url_path='subscription')
    def cancel_subscription(self, request, pk=None):
        """Admin only endpoint to unsubscribe any user."""
        if request.user.role != UserRole.ADMIN:
            return Response({"detail": "Only admins can unsubscribe other users."}, status=status.HTTP_403_FORBIDDEN)
        
        ip_address = get_client_ip(request)
        result = unsubscribe_user(target_user_id=pk)

        if result["status_code"] != 200:
            return Response({"detail": result["detail"]}, status=result["status_code"])

        if result["user_updated"]:
            log_audit(
                actor=request.user,
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                ip_address=ip_address,
                fields_modified=['maya_card_id']
            )

        return Response({"detail": result["detail"]}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='subscription')
    def create_subscription(self, request, pk=None):
        if request.user.user_id != int(pk):
            return Response({"detail": "You may only subscribe your own account."}, status=status.HTTP_403_FORBIDDEN)

        if request.user.role != UserRole.TUAB:
            return Response({"detail": "Only TUAB users can subscribe themselves."}, status=status.HTTP_403_FORBIDDEN)

        serializer = SubscribeSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ip_address = get_client_ip(request)
        result = subscribe_user(
            target_user_id=pk,
            first_name=serializer.validated_data['firstName'],
            last_name=serializer.validated_data['lastName'],
            card=serializer.validated_data['card'],
        )

        if result["status_code"] != 200:
            return Response({"detail": result["detail"]}, status=result["status_code"])

        log_audit(
            actor=request.user,
            entity_type='users',
            action='CREDENTIAL_UPDATE',
            ip_address=ip_address,
            fields_modified=result['fields_modified']
        )

        return Response(
            {
                "detail": result["detail"],
                "maya_customer_id": result["maya_customer_id"],
                "maya_card_id": result["maya_card_id"],
                "cardTokenId": result["cardTokenId"],
                "state": result["state"],
                "verificationUrl": result["verificationUrl"],
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['delete'], url_path='me/subscription')
    def cancel_my_subscription(self, request):
        """Endpoint for users to unsubscribe themselves."""
        ip_address = get_client_ip(request)
        result = unsubscribe_user(target_user_id=request.user.user_id)

        if result["status_code"] != 200:
            return Response({"detail": result["detail"]}, status=result["status_code"])

        if result["user_updated"]:
            log_audit(
                actor=request.user,
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                ip_address=ip_address,
                fields_modified=['maya_card_id']
            )

        return Response({"detail": result["detail"]}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        # Only allow Admins to use this POST endpoint
        if request.user.role != UserRole.ADMIN:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        role = request.data.get('role')
        if role == UserRole.DONOR:
            serializer = DonorRegisterSerializer(data=request.data)
        else:
            return Response({"error": "Only Donor creation is supported via this endpoint."}, status=status.HTTP_400_BAD_REQUEST)

        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Registration successful."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != UserRole.ADMIN:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        try:
            target_user = User.objects.get(pk=kwargs['pk'])
        except User.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if_match = request.headers.get('If-Match')
        current_etag = build_updated_at_etag(target_user)
        if if_match is None:
            return Response({"detail": "If-Match header is required."}, status=status.HTTP_428_PRECONDITION_REQUIRED)
        if not matches_if_match(current_etag, if_match):
            return Response({"detail": "ETag does not match the current resource version."}, status=status.HTTP_412_PRECONDITION_FAILED)

        ip_address = get_client_ip(request)
        with transaction.atomic():
            result = archive_user(target_user_id=kwargs['pk'])
            if result["detail"] is not None:
                return Response({"detail": result["detail"]}, status=result["status_code"])

            if result["user_updated"]:
                log_audit(
                    actor=request.user,
                    entity_type='users',
                    action='STATUS_CHANGE',
                    ip_address=ip_address,
                    fields_modified=['status', 'maya_card_id']
                )

            for donation in result["changed_donations"] or []:
                log_audit(
                    actor=request.user,
                    entity_type='donations',
                    action='STATUS_CHANGE',
                    ip_address=ip_address,
                    fields_modified=['status']
                )

            for inventory_ledger in result["changed_inventory_ledgers"] or []:
                log_audit(
                    actor=request.user,
                    entity_type='inventory_ledger',
                    action='STATUS_CHANGE',
                    ip_address=ip_address,
                    fields_modified=['lifecycle_status', 'was_forced_archived', 'archived_at']
                )

        return Response(status=result["status_code"])
