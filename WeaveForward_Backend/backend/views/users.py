from django.db import transaction
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..utils.view_mixins import PaginatedResponseMixin

from ..models import User, UserRole
from ..serializers import (
    PublicUserSerializer, 
    UserSerializer, 
    DonorRegisterSerializer, 
    TUABRegisterSerializer
)
from ..services.audit_service import get_client_ip, log_audit



class UserViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, PaginatedResponseMixin):
    filter_backends = [filters.SearchFilter]
    search_fields = ['email']

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
        return super().retrieve(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

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

