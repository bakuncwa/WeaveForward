from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.dateparse import parse_datetime
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
import logging

from ..models import MatchPrediction, UserRole, MatchRecommendationStatus, Subscription, SubscriptionStatus
from ..serializers.fiberrecommendations import (
    MatchRecommendationListSerializer,
    MatchRecommendationDetailSerializer,
    MatchRecommendationActionSerializer,
)
from ..services.prediction_service import MatchPredictionService
from ..services.audit_service import get_client_ip, log_audit
from ..utils.view_mixins import PaginatedResponseMixin

logger = logging.getLogger(__name__)


class IsTUABWithSubscription(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.user.role != UserRole.TUAB:
            raise PermissionDenied("Only TUABs can access Donation Recommendations.")
        try:
            subscription = Subscription.objects.filter(
                user=request.user,
                status=SubscriptionStatus.ACTIVE
            ).first()
            if not subscription or (subscription.end_date and subscription.end_date < timezone.now()):
                raise PermissionDenied("No active subscription found. Please upgrade to access Donation Recommendations.")
        except Exception as e:
            if isinstance(e, PermissionDenied):
                raise
            raise PermissionDenied("Unable to verify subscription status.")
        return True


class MatchRecommendationViewSet(viewsets.GenericViewSet, PaginatedResponseMixin):
    permission_classes = [IsTUABWithSubscription]
    serializer_class = MatchRecommendationDetailSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = []

    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return MatchRecommendationListSerializer
        elif getattr(self, 'action', None) in ['accept', 'reject']:
            return MatchRecommendationActionSerializer
        return MatchRecommendationDetailSerializer

    def get_queryset(self):
        return MatchPrediction.objects.filter(
            tuab=self.request.user
        ).select_related(
            'item', 'item__lookup', 'item__donation', 'item__donation__donor', 'tuab',
        ).order_by('-match_prob')

    def list(self, request, *args, **kwargs):
        try:
            MatchPredictionService.load_model()
        except ValueError:
            return Response(
                {'detail': 'Recommendation engine is currently unavailable. Please try again later.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        filters = {}
        if request.query_params.get('fiber_type'):
            filters['fiber_types'] = request.query_params.get('fiber_type')
        if request.query_params.get('biodeg_tier'):
            filters['biodeg_tier'] = request.query_params.get('biodeg_tier')
        if request.query_params.get('city'):
            filters['city'] = request.query_params.get('city')
        if request.query_params.get('confidence_min'):
            try:
                filters['confidence_min'] = float(request.query_params.get('confidence_min')) / 100
            except (ValueError, TypeError):
                return Response({'detail': 'confidence_min must be 0-100'}, status=status.HTTP_400_BAD_REQUEST)
        if request.query_params.get('confidence_max'):
            try:
                filters['confidence_max'] = float(request.query_params.get('confidence_max')) / 100
            except (ValueError, TypeError):
                return Response({'detail': 'confidence_max must be 0-100'}, status=status.HTTP_400_BAD_REQUEST)
        if request.query_params.get('date_after'):
            try:
                filters['date_after'] = parse_datetime(request.query_params.get('date_after'))
            except (ValueError, TypeError):
                return Response({'detail': 'date_after must be ISO 8601'}, status=status.HTTP_400_BAD_REQUEST)
        if request.query_params.get('date_before'):
            try:
                filters['date_before'] = parse_datetime(request.query_params.get('date_before'))
            except (ValueError, TypeError):
                return Response({'detail': 'date_before must be ISO 8601'}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self._get_filtered_recommendations(request.user, filters)
        return self.get_paginated_response_data(queryset)

    def _get_filtered_recommendations(self, tuab, filters):
        from django.db.models import Q

        queryset = MatchPrediction.objects.filter(
            tuab=tuab,
            recommendation_status=MatchRecommendationStatus.PENDING,
            is_archived_version=False,
        ).select_related(
            'item', 'item__lookup', 'item__donation', 'item__donation__donor', 'tuab',
        ).order_by('-match_prob')

        if filters.get('biodeg_tier'):
            tier = filters['biodeg_tier'].upper()
            if tier == 'HIGH':
                queryset = queryset.filter(biodeg_target_fiber__gte=80)
            elif tier == 'MEDIUM':
                queryset = queryset.filter(biodeg_target_fiber__gte=50, biodeg_target_fiber__lt=80)
            elif tier == 'LOW':
                queryset = queryset.filter(biodeg_target_fiber__lt=50)

        if filters.get('fiber_types'):
            fiber_types = filters['fiber_types']
            if isinstance(fiber_types, str):
                fiber_types = [f.strip().lower() for f in fiber_types.split(',')]
            q = Q()
            for ft in fiber_types:
                q |= Q(item__lookup__fiber_json__icontains=ft)
            queryset = queryset.filter(q)

        if filters.get('city'):
            queryset = queryset.filter(item__donation__pickup_city__icontains=filters['city'])
        if filters.get('confidence_min') is not None:
            queryset = queryset.filter(match_prob__gte=Decimal(str(filters['confidence_min'])))
        if filters.get('confidence_max') is not None:
            queryset = queryset.filter(match_prob__lte=Decimal(str(filters['confidence_max'])))
        if filters.get('date_after'):
            queryset = queryset.filter(item__donation__preferred_pickup_date__gte=filters['date_after'])
        if filters.get('date_before'):
            queryset = queryset.filter(item__donation__preferred_pickup_date__lte=filters['date_before'])

        return queryset

    def retrieve(self, request, pk=None):
        try:
            match_pred = MatchPrediction.objects.select_related(
                'item', 'item__lookup', 'item__donation', 'item__donation__donor', 'tuab',
            ).get(pair_id=pk, tuab=request.user)
        except MatchPrediction.DoesNotExist:
            raise NotFound("Recommendation not found.")
        serializer = self.get_serializer(match_pred)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        with transaction.atomic():
            try:
                match_pred = MatchPrediction.objects.select_for_update().get(
                    pair_id=pk, tuab=request.user,
                    recommendation_status=MatchRecommendationStatus.PENDING,
                )
            except MatchPrediction.DoesNotExist:
                return Response({'detail': 'Recommendation not found or no longer pending'}, status=status.HTTP_404_NOT_FOUND)

            try:
                match_pred.recommendation_status = MatchRecommendationStatus.ACCEPTED
                match_pred.save(update_fields=['recommendation_status'])
                log_audit(actor=request.user, entity_type='MatchPrediction', action='ACCEPT_RECOMMENDATION',
                          fields_modified='recommendation_status', ip_address=get_client_ip(request))
                return Response({'pair_id': pk, 'recommendation_status': MatchRecommendationStatus.ACCEPTED,
                                 'message': 'Recommendation accepted successfully'}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Error accepting recommendation {pk}: {e}")
                return Response({'detail': 'Failed to process acceptance'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            try:
                match_pred = MatchPrediction.objects.select_for_update().get(
                    pair_id=pk, tuab=request.user,
                    recommendation_status=MatchRecommendationStatus.PENDING,
                )
            except MatchPrediction.DoesNotExist:
                return Response({'detail': 'Recommendation not found or no longer pending'}, status=status.HTTP_404_NOT_FOUND)

            try:
                reason = serializer.validated_data.get('reason')
                match_pred.recommendation_status = MatchRecommendationStatus.REJECTED
                match_pred.tuab_rejection_reason = reason if reason and reason.strip() else None
                match_pred.save(update_fields=['recommendation_status', 'tuab_rejection_reason'])
                log_audit(actor=request.user, entity_type='MatchPrediction', action='REJECT_RECOMMENDATION',
                          fields_modified='recommendation_status,tuab_rejection_reason', ip_address=get_client_ip(request))
                return Response({'pair_id': pk, 'recommendation_status': MatchRecommendationStatus.REJECTED,
                                 'tuab_rejection_reason': match_pred.tuab_rejection_reason,
                                 'message': 'Recommendation rejected successfully'}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Error rejecting recommendation {pk}: {e}")
                return Response({'detail': 'Failed to process rejection'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
