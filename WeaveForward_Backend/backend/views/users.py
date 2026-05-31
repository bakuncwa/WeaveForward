import pyotp
from django.db.models import F, Func, ExpressionWrapper, FloatField
from django.db import transaction
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend
from ..utils.view_mixins import PaginatedResponseMixin

from ..models import User, UserRole, UserAccountStatus, UserOperationalStatus
from ..serializers import (
    AdminUserListSerializer,
    AdminUserDetailSerializer,
    DonorSelfSerializer,
    DonorUpdateSerializer,
    DonorUpdateSelfSerializer,
    TuabDetailSerializer,
    TuabSelfSerializer,
    TuabListSerializer,
    TuabUpdateSerializer,
    TuabUpdateSelfSerializer,
    TwoFactorSerializer,
    SubscribeSetupSerializer,
    DonorRegisterSerializer, 
    TUABRegisterSerializer
)
from ..services.audit_service import get_client_ip, log_audit
from ..services.auth_service import get_request_base_url, generate_api_key
from ..services.etag_service import build_updated_at_etag, matches_if_match
from ..services.two_factor_service import disable_two_factor, enable_two_factor
from ..services.user_archive_service import archive_user
from ..services.subscription_service import subscribe_user, unsubscribe_user




class UserViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, PaginatedResponseMixin):
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    filterset_fields = ['role', 'status']
    search_fields = ['email', 'first_name', 'last_name', 'business_name']
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        return super().get_permissions()

    def get_serializer_class(self):
        if hasattr(self, 'request') and hasattr(self.request, 'user'):
            # 1. Action-based routing (Target-dependent)
            if self.action in ['update', 'partial_update', 'partial_update_me']:
                try:
                    pk = self.kwargs.get('pk')
                    if pk == 'me':
                        target_role = self.request.user.role
                    elif pk:
                        target_role = User.objects.values_list('role', flat=True).get(pk=pk)
                    else:
                        target_role = self.request.user.role
                except User.DoesNotExist:
                    target_role = self.request.user.role
                except Exception:
                    target_role = self.request.user.role

                if target_role == UserRole.DONOR:
                    if self.request.user.role != 'Admin':
                        return DonorUpdateSelfSerializer
                    return DonorUpdateSerializer
                elif target_role == UserRole.TUAB:
                    if self.request.user.role != 'Admin':
                        return TuabUpdateSelfSerializer
                    return TuabUpdateSerializer

            # 2. Requester-based routing
            if self.request.user.role != 'Admin':
                if self.action == 'list':
                    return TuabListSerializer
                if self.action == 'retrieve':
                    return TuabDetailSerializer
                if self.action == 'me' and self.request.user.role == UserRole.DONOR:
                    return DonorSelfSerializer
                if self.action == 'me' and self.request.user.role == UserRole.TUAB:
                    return TuabSelfSerializer
            if self.request.user.role == 'Admin' and self.action == 'list':
                return AdminUserListSerializer
        return AdminUserDetailSerializer

    def get_queryset(self):
        return (
            User.objects.select_related('upload', 'documentation')
            .order_by('-created_at', '-user_id')
        )

    def list(self, request, *args, **kwargs):
        # 1. Start with the base plan
        # Complexity notes:
        # - Let n = number of matching users.
        # - Filtering/scan work is O(n).
        # - Ordering/sorting work is O(n log n).
        # - Overall list complexity is O(n log n).
        queryset = self.get_queryset()
        
        # 2. Hard Security Rules (Cannot be bypassed by URL params)
        if request.user.role != UserRole.ADMIN:
            queryset = queryset.filter(
                role=UserRole.TUAB, 
                status=UserAccountStatus.ACTIVE, 
                operational_status=UserOperationalStatus.ACTIVE
            )

        # 3. Automated Filtering (Handles ?search, ?role, and ?status from URL)
        queryset = self.filter_queryset(queryset)
        
        # 4. Apply Category Filter if present
        if request.query_params.get('category'):
            queryset = queryset.filter(target_fibers=request.query_params.get('category'))

        # 5. Distance Calculation & Sorting (Database Level)
        if request.query_params.get('lat') and request.query_params.get('lng'):
            queryset = queryset.annotate(
                distance_km=ExpressionWrapper(
                    Func(
                        Func(F('longitude'), F('latitude'), function='POINT'),
                        Func(float(request.query_params.get('lng')), float(request.query_params.get('lat')), function='POINT'),
                        function='ST_Distance_Sphere'
                    ) / 1000.0,
                    output_field=FloatField()
                )
            ).order_by('distance_km')

        return self.get_paginated_response_data(queryset)

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
            
        if instance.role == UserRole.ADMIN:
            return Response({"detail": "Admin profiles cannot be updated via this endpoint."}, status=status.HTTP_403_FORBIDDEN)
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

        if request.query_params.get('validate_only') == 'true':
            return Response({"detail": "Validation successful."}, status=status.HTTP_200_OK)

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

    @action(detail=False, methods=['patch'], url_path='me')
    def partial_update_me(self, request, *args, **kwargs):
        self.kwargs['pk'] = request.user.user_id
        return self.partial_update(request, *args, **kwargs)

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
                generate_api_key(target_user)
            
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
            return Response({
                "message": result["detail"],
                "etag": build_updated_at_etag(request.user)
            }, status=status.HTTP_200_OK)

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

            return Response({
                "message": result["detail"],
                "etag": build_updated_at_etag(target_user)
            }, status=status.HTTP_200_OK)

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
        result = unsubscribe_user(target_user_id=pk, actor=request.user, ip_address=ip_address)

        if result["status_code"] != 200:
            return Response({"detail": result["detail"]}, status=result["status_code"])

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
            frontend_base_url=get_request_base_url(request),
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

    @action(detail=False, methods=['post'], url_path='me/subscription')
    def create_my_subscription(self, request):
        if request.user.role != UserRole.TUAB:
            return Response({"detail": "Only TUAB users can subscribe themselves."}, status=status.HTTP_403_FORBIDDEN)

        serializer = SubscribeSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ip_address = get_client_ip(request)
        result = subscribe_user(
            target_user_id=request.user.user_id,
            first_name=serializer.validated_data['firstName'],
            last_name=serializer.validated_data['lastName'],
            card=serializer.validated_data['card'],
            frontend_base_url=get_request_base_url(request),
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
        result = unsubscribe_user(target_user_id=request.user.user_id, actor=request.user, ip_address=ip_address)

        if result["status_code"] != 200:
            return Response({"detail": result["detail"]}, status=result["status_code"])

        return Response({"detail": result["detail"]}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        # If user is authenticated, they must be an Admin
        if request.user and request.user.is_authenticated:
            if request.user.role != UserRole.ADMIN:
                return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

            role = request.data.get('role')
            if role == UserRole.DONOR:
                serializer = DonorRegisterSerializer(data=request.data)
            else:
                return Response({"error": "Only Donor creation is supported via this endpoint."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Public registration flow
            role = request.data.get('role')
            if role == UserRole.DONOR:
                serializer = DonorRegisterSerializer(data=request.data)
            elif role == UserRole.TUAB:
                serializer = TUABRegisterSerializer(data=request.data)
            else:
                return Response({"error": "Invalid role specified."}, status=status.HTTP_400_BAD_REQUEST)

        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Registration successful."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != UserRole.ADMIN:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        # Complexity notes:
        # - The archive route is linear in the number of affected donations,
        #   inventory ledgers, subscriptions, and tokens processed.
        # - Real form: O(d + l + s + t)
        # - Simplified: O(n)
        try:
            target_user = User.objects.get(pk=kwargs['pk'])
        except User.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ip_address = get_client_ip(request)
        with transaction.atomic():
            result = archive_user(target_user_id=kwargs['pk'])
            if result["detail"] is not None:
                transaction.set_rollback(True)
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
