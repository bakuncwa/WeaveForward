from django.db import transaction
from rest_framework import filters, mixins, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..utils.view_mixins import PaginatedResponseMixin
from ..models import Donation
from ..serializers import DonationSerializer
from ..services.donation_service import create_donation
from ..services.etag_service import build_updated_at_etag

class DonationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, PaginatedResponseMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = DonationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['donation_id']


    def get_queryset(self):
        user = self.request.user
        queryset = Donation.objects.all()

        # Main List visibility (Hall of Fame)
        if user.role != 'Admin':
            # Everyone sees all donations except those that are ARCHIVED
            queryset = queryset.exclude(status='ARCHIVED')

        return queryset.select_related(
            'donor',
            'donor__upload',
            'claimed_by_tuab',
            'claimed_by_tuab__upload',
            'upload',
        ).prefetch_related(
            'items__lookup',
        ).order_by('-submitted_at', '-donation_id')

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        response = super().retrieve(request, *args, **kwargs)
        response['ETag'] = build_updated_at_etag(instance)
        return response

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Returns the logged-in user's personal donation history."""
        user = request.user

        queryset = self.get_queryset()
        if user.role == 'Donor':
            queryset = queryset.filter(donor=user)
        elif user.role == 'TUAB':
            queryset = queryset.filter(claimed_by_tuab=user)
        elif user.role != 'Admin':
            queryset = queryset.none()

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
