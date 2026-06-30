import pyotp
from django.db.models import F, Func, ExpressionWrapper, FloatField, Q
from django.db import transaction
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend
from ..utils.view_mixins import PaginatedResponseMixin

from ..models import User, UserRole, UserAccountStatus, UserOperationalStatus
from ..permissions import IsActiveAdmin, IsActiveTUAB
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
from ..services.auth_service import create_tuab_documentation_upload, generate_api_key, generate_reset_token, get_request_base_url
from ..services.email_service import send_tuab_review_result_email, send_verification_email
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
        permission_map = {
            'approve': [IsActiveAdmin],
            'destroy': [IsActiveAdmin],
            'cancel_subscription': [IsActiveAdmin],
            'create_subscription': [IsActiveTUAB],
            'create_my_subscription': [IsActiveTUAB],
        }
        if self.action in permission_map:
            return [permission() for permission in permission_map[self.action]]
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
            .order_by('-updated_at', '-user_id')
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
            category = request.query_params.get('category')
            queryset = queryset.filter(
                Q(target_fibers=category)
                | Q(target_fibers__startswith=f"{category},")
                | Q(target_fibers__endswith=f",{category}")
                | Q(target_fibers__contains=f",{category},")
                | Q(target_fibers__contains=f", {category},")
                | Q(target_fibers__endswith=f", {category}")
            )

        # 5. Distance Calculation & Sorting (Database Level)
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        if lat and lng:
            lat = float(lat)
            lng = float(lng)

            artisan_point = Func(F('longitude'), F('latitude'), function='POINT')
            user_point = Func(lng, lat, function='POINT')
            distance_meters = Func(
                artisan_point,
                user_point,
                function='ST_Distance_Sphere'
            )

            queryset = queryset.annotate(
                distance_km=ExpressionWrapper(
                    distance_meters / 1000.0,
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
        if not if_match or not matches_if_match(current_etag, if_match):
            return Response({"detail": "Your session has expired. Please refresh the page and try again."}, status=status.HTTP_412_PRECONDITION_FAILED)

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        if request.query_params.get('validate_only') == 'true':
            return Response({"detail": "Validation successful."}, status=status.HTTP_200_OK)

        fields_modified = []
        for field_name, new_value in serializer.validated_data.items():
            if field_name in {'password', 'upload'}:
                fields_modified.append(field_name)
                continue

            if getattr(instance, field_name) != new_value:
                fields_modified.append(field_name)

        if instance.role == UserRole.TUAB:
            critical = ['max_distance_km', 'min_biodeg_score', 'target_fibers', 'latitude', 'longitude', 'display_address']
            # Put critical fields at the FRONT so they are prioritized before the 100-char cutoff
            fields_modified = [f for f in critical if f in fields_modified] + [f for f in fields_modified if f not in critical]

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
        status_input = request.data.get('status')
        rejection_reason = request.data.get('rejection_reason')
        if status_input not in [UserAccountStatus.ACTIVE, UserAccountStatus.REJECTED]:
            return Response({"detail": "Status must be either ACTIVE or REJECTED."}, status=status.HTTP_400_BAD_REQUEST)

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

            if target_user.status == UserAccountStatus.EMAIL_UNVERIFIED:
                return Response({"detail": "TUAB must verify their email before being approved."}, status=status.HTTP_409_CONFLICT)

            if target_user.status != UserAccountStatus.UNDER_REVIEW:
                return Response({"detail": "Only TUAB users under review can be reviewed."}, status=status.HTTP_409_CONFLICT)

            if status_input == UserAccountStatus.REJECTED:
                target_user.status = UserAccountStatus.REJECTED
                target_user.rejection_reason = rejection_reason
            else:
                target_user.status = UserAccountStatus.ACTIVE
                target_user.operational_status = UserOperationalStatus.ACTIVE
                target_user.rejection_reason = None
                generate_api_key(target_user)
            
            target_user.save(update_fields=['status', 'operational_status', 'rejection_reason', 'updated_at'])

            log_audit(
                actor=request.user,
                entity_type='users',
                action='STATUS_CHANGE',
                ip_address=ip_address,
                fields_modified=['status', 'rejection_reason'] if status_input == UserAccountStatus.REJECTED else ['status']
            )

        send_tuab_review_result_email(
            target_user.email,
            target_user.business_name,
            status_input == UserAccountStatus.ACTIVE,
            target_user.rejection_reason,
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
        ip_address = get_client_ip(request)
        result = unsubscribe_user(target_user_id=pk, actor=request.user, ip_address=ip_address)

        if result["status_code"] != 200:
            return Response({"detail": result["detail"]}, status=result["status_code"])

        return Response({"detail": result["detail"]}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='subscription')
    def create_subscription(self, request, pk=None):
        if request.user.user_id != int(pk):
            return Response({"detail": "You may only subscribe your own account."}, status=status.HTTP_403_FORBIDDEN)

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
        is_admin_create = bool(request.user and request.user.is_authenticated)
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
                return Response({"error": "Please specify a valid user role (Donor or TUAB)."}, status=status.HTTP_400_BAD_REQUEST)

        if serializer.is_valid():
            with transaction.atomic():
                if role == UserRole.TUAB:
                    documentation = serializer.validated_data.pop('documentation', None)
                    documentation_upload = create_tuab_documentation_upload(documentation)
                    user = serializer.save(documentation=documentation_upload)
                else:
                    user = serializer.save()

                if is_admin_create:
                    user.status = UserAccountStatus.ACTIVE
                    user.save(update_fields=['status', 'updated_at'])
                    return Response({"message": "Donor account created successfully."}, status=status.HTTP_201_CREATED)

                if user.status == UserAccountStatus.UNDER_REVIEW:
                    return Response({"message": "TUAB application submitted for review."}, status=status.HTTP_201_CREATED)

                try:
                    uidb64, token = generate_reset_token(user)
                    frontend_base_url = get_request_base_url(request)
                    verify_link = f"{frontend_base_url}/verify-email/?uidb64={uidb64}&token={token}"
                    display_name = user.business_name or f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
                    email_result = send_verification_email(user.email, verify_link, display_name)
                except Exception:
                    email_result = None

                if email_result is None:
                    transaction.set_rollback(True)
                    return Response(
                        {"detail": "Registration could not be completed because the verification email could not be sent. Please try again."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )

            return Response({"message": "Registration successful. Please check your email to verify your account."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
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
