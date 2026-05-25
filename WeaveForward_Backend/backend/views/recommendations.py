from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.dateparse import parse_datetime

from ..models import MatchPrediction, UserRole
from ..serializers.recommendations import (
    MatchRecommendationListSerializer,
    MatchRecommendationDetailSerializer,
    MatchRecommendationActionSerializer,
)
from ..services.match_recommendation_service import (
    verify_tuab_subscription,
    get_pending_recommendations,
    accept_recommendation,
    reject_recommendation,
)
from ..services.audit_service import get_client_ip
from ..utils.view_mixins import PaginatedResponseMixin


class IsTUABWithSubscription(IsAuthenticated):
    """Permission to verify user is authenticated TUAB with active subscription"""
    
    def has_permission(self, request, view):
        # First check authentication
        if not super().has_permission(request, view):
            return False
        
        # Check user role
        if request.user.role != UserRole.TUAB:
            raise PermissionDenied("Only TUABs can access Donation Recommendations.")
        
        # Check subscription
        is_active, error_msg = verify_tuab_subscription(request.user)
        if not is_active:
            raise PermissionDenied(
                error_msg or "No active subscription found. Please upgrade to access Donation Recommendations."
            )
        
        return True


class MatchRecommendationViewSet(viewsets.GenericViewSet, PaginatedResponseMixin):
    """
    ViewSet for handling match recommendations.
    
    Endpoints:
    - GET /match-recommendations/ - List pending recommendations
    - GET /match-recommendations/{id}/ - Get recommendation detail
    - POST /match-recommendations/{id}/accept/ - Accept recommendation
    - POST /match-recommendations/{id}/reject/ - Reject recommendation
    """
    permission_classes = [IsTUABWithSubscription]
    serializer_class = MatchRecommendationDetailSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = []  # We handle filtering manually
    
    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return MatchRecommendationListSerializer
        elif getattr(self, 'action', None) in ['accept', 'reject']:
            return MatchRecommendationActionSerializer
        return MatchRecommendationDetailSerializer
    
    def get_queryset(self):
        """Get base queryset - filtered by TUAB"""
        return MatchPrediction.objects.filter(
            tuab=self.request.user
        ).select_related(
            'item',
            'item__lookup',
            'item__donation',
            'item__donation__donor',
            'tuab',
        ).order_by('-match_prob')
    
    def list(self, request, *args, **kwargs):
        """
        List pending match recommendations with optional filtering.
        
        Query parameters:
        - fiber_type: comma-separated list of fiber types
        - biodeg_tier: HIGH|MEDIUM|LOW
        - city: pickup city
        - confidence_min: 0-100 (percentage)
        - confidence_max: 0-100 (percentage)
        - date_after: ISO datetime
        - date_before: ISO datetime
        - page: page number (default 1)
        - page_size: items per page (default 10, max 100)
        """
        # Build filters dict from query parameters
        filters = {}
        
        if request.query_params.get('fiber_type'):
            filters['fiber_types'] = request.query_params.get('fiber_type')
        
        if request.query_params.get('biodeg_tier'):
            filters['biodeg_tier'] = request.query_params.get('biodeg_tier')
        
        if request.query_params.get('city'):
            filters['city'] = request.query_params.get('city')
        
        # Convert confidence percentages to 0-1 range
        if request.query_params.get('confidence_min'):
            try:
                filters['confidence_min'] = float(request.query_params.get('confidence_min')) / 100
            except (ValueError, TypeError):
                return Response(
                    {'detail': 'confidence_min must be a number between 0 and 100'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if request.query_params.get('confidence_max'):
            try:
                filters['confidence_max'] = float(request.query_params.get('confidence_max')) / 100
            except (ValueError, TypeError):
                return Response(
                    {'detail': 'confidence_max must be a number between 0 and 100'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if request.query_params.get('date_after'):
            try:
                filters['date_after'] = parse_datetime(request.query_params.get('date_after'))
            except (ValueError, TypeError):
                return Response(
                    {'detail': 'date_after must be ISO 8601 format'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if request.query_params.get('date_before'):
            try:
                filters['date_before'] = parse_datetime(request.query_params.get('date_before'))
            except (ValueError, TypeError):
                return Response(
                    {'detail': 'date_before must be ISO 8601 format'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Get recommendations with filters
        queryset = get_pending_recommendations(request.user, filters)
        
        # Return paginated response
        return self.get_paginated_response_data(queryset)
    
    def retrieve(self, request, pk=None):
        """Get a single recommendation detail"""
        try:
            match_pred = MatchPrediction.objects.select_related(
                'item',
                'item__lookup',
                'item__donation',
                'item__donation__donor',
                'tuab',
            ).get(pair_id=pk, tuab=request.user)
        except MatchPrediction.DoesNotExist:
            raise NotFound("Recommendation not found.")
        
        serializer = self.get_serializer(match_pred)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """Accept a match recommendation"""
        client_ip = get_client_ip(request)
        
        result = accept_recommendation(
            pair_id=pk,
            tuab=request.user,
            client_ip=client_ip,
        )
        
        if not result.get('success'):
            return Response(
                {'detail': result.get('message')},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(
            {
                'pair_id': result['pair_id'],
                'recommendation_status': result['recommendation_status'],
                'message': result['message'],
            },
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a match recommendation with optional reason"""
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        client_ip = get_client_ip(request)
        reason = serializer.validated_data.get('reason')
        
        result = reject_recommendation(
            pair_id=pk,
            tuab=request.user,
            reason=reason,
            client_ip=client_ip,
        )
        
        if not result.get('success'):
            return Response(
                {'detail': result.get('message')},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(
            {
                'pair_id': result['pair_id'],
                'recommendation_status': result['recommendation_status'],
                'tuab_rejection_reason': result.get('tuab_rejection_reason'),
                'message': result['message'],
            },
            status=status.HTTP_200_OK
        )
