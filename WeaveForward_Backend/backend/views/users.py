import pyotp
from django.db import transaction
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..utils.view_mixins import PaginatedResponseMixin

from ..models import User, UserRole
from ..serializers import (
    PublicUserSerializer, 
    UserSerializer, 
    TwoFactorSerializer,
    DonorRegisterSerializer, 
    TUABRegisterSerializer
)
from ..services.audit_service import get_client_ip, log_audit
from ..services.etag_service import build_updated_at_etag, matches_if_match



class UserViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, PaginatedResponseMixin):
    filter_backends = [filters.SearchFilter]
    search_fields = ['email']
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated()] # We will check the ADMIN role inside create
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if hasattr(self, 'request') and hasattr(self.request, 'user'):
            if self.request.user.role != 'Admin' and self.action in ['list', 'retrieve']:
                return PublicUserSerializer
        return UserSerializer

    def get_queryset(self):
        # We define a broad queryset here; the list/retrieve methods handle the role-based blocking
        return User.objects.select_related('upload').order_by('user_id')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        if request.user.role == UserRole.ADMIN:
            role_filter = request.query_params.get('role')
            if role_filter:
                queryset = queryset.filter(role=role_filter)
        else:
            queryset = queryset.filter(role=UserRole.TUAB, status='ACTIVE', operational_status='ACTIVE')

        return self.get_paginated_response_data(queryset)

    def retrieve(self, request, *args, **kwargs):
        # Admins can retrieve ANY user; others can retrieve THEMSELVES or active TUABs
        instance = self.get_object()
        if request.user.role != UserRole.ADMIN:
            is_self = instance.user_id == request.user.user_id
            is_active_tuab = instance.role == UserRole.TUAB and instance.status == 'ACTIVE' and instance.operational_status == 'ACTIVE'
            if not (is_self or is_active_tuab):
                return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        response = super().retrieve(request, *args, **kwargs)
        response['ETag'] = build_updated_at_etag(instance)
        return response

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.user.role != UserRole.ADMIN and instance.user_id != request.user.user_id:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        if_match = request.headers.get('If-Match')
        current_etag = build_updated_at_etag(instance)
        if if_match is None:
            return Response({"detail": "If-Match header is required."}, status=status.HTTP_428_PRECONDITION_REQUIRED)
        if not matches_if_match(current_etag, if_match):
            return Response({"detail": "ETag does not match the current resource version."}, status=status.HTTP_412_PRECONDITION_FAILED)

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        fields_modified = [
            'upload' if field == 'profile_picture' else field
            for field in serializer.validated_data.keys()
        ]

        ip_address = get_client_ip(request)
        with transaction.atomic():
            user = serializer.save()
            log_audit(
                actor=request.user,
                entity_type='User',
                action='PATCH',
                ip_address=ip_address,
                fields_modified=','.join(fields_modified) if fields_modified else None
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
            ip_address = get_client_ip(request)
            with transaction.atomic():
                user = serializer.save()
                log_audit(actor=user, entity_type='User', action='POST', ip_address=ip_address)
            return Response({"message": "Registration successful."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TwoFactorSetupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
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


class TwoFactorView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role == UserRole.ADMIN and request.user.user_id != pk:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if request.user.user_id != pk:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        serializer = TwoFactorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ip_address = get_client_ip(request)
        with transaction.atomic():
            request.user.is_2fa_enabled = True
            request.user.totp_secret = serializer.validated_data['secret']
            request.user.save(update_fields=['is_2fa_enabled', 'totp_secret'])
            log_audit(
                actor=request.user,
                entity_type='User',
                action='POST',
                ip_address=ip_address,
                fields_modified='is_2fa_enabled,totp_secret'
            )

        return Response({"message": "2FA enabled successfully."}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        try:
            target_user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role != UserRole.ADMIN and request.user.user_id != target_user.user_id:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        ip_address = get_client_ip(request)
        with transaction.atomic():
            target_user.is_2fa_enabled = False
            target_user.totp_secret = None
            target_user.save(update_fields=['is_2fa_enabled', 'totp_secret'])
            log_audit(
                actor=request.user,
                entity_type='User',
                action='DELETE',
                ip_address=ip_address,
                fields_modified='is_2fa_enabled,totp_secret'
            )

        return Response({"message": "2FA disabled successfully."}, status=status.HTTP_200_OK)
