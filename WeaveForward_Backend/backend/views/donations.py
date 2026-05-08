from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..utils.view_mixins import PaginatedResponseMixin
from ..models import Donation
from ..serializers import DonationSerializer

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
