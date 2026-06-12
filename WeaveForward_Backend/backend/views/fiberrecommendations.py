from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, AuthenticationFailed
from rest_framework.authentication import BaseAuthentication
from rest_framework.settings import api_settings
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.dateparse import parse_datetime
from django.db import transaction
from django.db.models import Q
from decimal import Decimal
import json
import logging
import hashlib

from ..models import MatchPrediction, MatchRecommendationStatus, AuditTrail, ApiToken, DonationItem
from ..permissions import IsActiveTUABWithActiveSubscription
from ..serializers.fiberrecommendations import (
    MatchRecommendationListSerializer,
    MatchRecommendationDetailSerializer,
    MatchRecommendationActionSerializer,
)
from ..services.prediction_service import MatchPredictionService, run_predictions_for_donation_for_one_tuab
from ..services.audit_service import get_client_ip, log_audit
from ..services.email_service import (
    send_match_accept_notification,
    send_match_reject_notification,
)
from ..utils.view_mixins import PaginatedResponseMixin

logger = logging.getLogger(__name__)


class ApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None
        
        parts = auth_header.split(" ")
        if len(parts) != 2 or parts[0] != "ApiKey":
            return None
            
        api_key = parts[1]
        hashed_key = hashlib.sha1(api_key.encode()).hexdigest()
        try:
            api_token = ApiToken.objects.select_related("user").get(token=hashed_key)
            return (api_token.user, api_token)
        except ApiToken.DoesNotExist:
            raise AuthenticationFailed("Invalid API key.")


class MatchRecommendationViewSet(viewsets.GenericViewSet, PaginatedResponseMixin):
    authentication_classes = [ApiKeyAuthentication] + list(api_settings.DEFAULT_AUTHENTICATION_CLASSES)
    permission_classes = [IsActiveTUABWithActiveSubscription]
    serializer_class = MatchRecommendationDetailSerializer

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
        user = request.user

        # If the TUAB changed ML-critical profile fields (fibers, biodeg, distance, location)
        # after the last prediction run, predictions are stale — re-run before serving results.
        latest_prediction = MatchPrediction.objects.filter(
            tuab=user, is_archived_version=False
        ).order_by('-predicted_at').values_list('predicted_at', flat=True).first()

        if not latest_prediction:
            if DonationItem.objects.filter(donation__status='PENDING', is_archived=False).exists():
                run_predictions_for_donation_for_one_tuab(user)
        else:
            q = Q()
            for field in {'target_fibers', 'min_biodeg_score', 'max_distance_km', 'latitude', 'longitude'}:
                q |= Q(fields_modified__contains=field)

            latest_ml_audit = AuditTrail.objects.filter(
                q,
                actor=user,
                entity_type='users',
            ).order_by('-occurred_at').values_list('fields_modified', 'occurred_at').first()

            if latest_ml_audit and latest_ml_audit[1] > latest_prediction:
                run_predictions_for_donation_for_one_tuab(user)

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
        if request.query_params.get('unpaginated') == 'true':
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        return self.get_paginated_response_data(queryset)

    def _get_filtered_recommendations(self, tuab, filters):
        from django.db.models import Q

        queryset = MatchPrediction.objects.filter(
            tuab=tuab,
            recommendation_status=MatchRecommendationStatus.PENDING,
            is_archived_version=False,
            item__donation__status='PENDING',
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
        _notify_data = None

        with transaction.atomic():
            qs = MatchPrediction.objects.select_for_update().select_related(
                'item__donation__donor', 'item__lookup', 'tuab',
            )
            match_pred = qs.filter(
                pair_id=pk, tuab=request.user,
                recommendation_status=MatchRecommendationStatus.PENDING,
            ).first()

            if not match_pred:
                return Response({'detail': 'Recommendation not found or no longer pending'},
                                status=status.HTTP_404_NOT_FOUND)

            donation = match_pred.item.donation
            if donation.status != 'PENDING':
                return Response({'detail': 'This donation is no longer available.'},
                                status=status.HTTP_409_CONFLICT)

            match_pred.recommendation_status = MatchRecommendationStatus.ACCEPTED
            match_pred.save(update_fields=['recommendation_status'])
            log_audit(actor=request.user, entity_type='MatchPrediction', action='ACCEPT_RECOMMENDATION',
                      fields_modified='recommendation_status', ip_address=get_client_ip(request))

            donor = donation.donor
            already_notified = MatchPrediction.objects.filter(
                tuab=request.user,
                item__donation_id=donation.donation_id,
                is_archived_version=False,
                recommendation_status=MatchRecommendationStatus.ACCEPTED,
            ).exclude(pair_id=pk).exists()

            if not already_notified:
                tuab_name = request.user.business_name or request.user.email
                _notify_data = {
                    'donor_email': donor.email,
                    'donor_name': donor.first_name or 'Donor',
                    'tuab_name': tuab_name,
                    'pickup_address': donation.pickup_display_address,
                    'pickup_date': donation.preferred_pickup_date.strftime(
                        '%B %d, %Y at %I:%M %p'
                    ) if donation.preferred_pickup_date else 'TBD',
                    'items_list': [{
                        'brand': match_pred.item.lookup.brand,
                        'clothing_type': match_pred.item.lookup.clothing_type,
                        'condition': match_pred.item.condition_rating,
                        'weight': str(match_pred.item.weight_kg),
                    }],
                }

        if _notify_data:
            send_match_accept_notification(**_notify_data)
        return Response({'pair_id': pk, 'recommendation_status': MatchRecommendationStatus.ACCEPTED,
                         'message': 'Recommendation accepted successfully'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        _notify_data = None

        with transaction.atomic():
            qs = MatchPrediction.objects.select_for_update().select_related(
                'item__donation__donor', 'item__lookup', 'tuab',
            )
            match_pred = qs.filter(
                pair_id=pk, tuab=request.user,
                recommendation_status=MatchRecommendationStatus.PENDING,
            ).first()

            if not match_pred:
                return Response({'detail': 'Recommendation not found or no longer pending'},
                                status=status.HTTP_404_NOT_FOUND)

            donation = match_pred.item.donation
            if donation.status != 'PENDING':
                return Response({'detail': 'This donation is no longer available.'},
                                status=status.HTTP_409_CONFLICT)

            reason = serializer.validated_data.get('reason')
            match_pred.recommendation_status = MatchRecommendationStatus.REJECTED
            match_pred.tuab_rejection_reason = reason if reason and reason.strip() else None
            match_pred.save(update_fields=['recommendation_status', 'tuab_rejection_reason'])
            log_audit(actor=request.user, entity_type='MatchPrediction', action='REJECT_RECOMMENDATION',
                      fields_modified='recommendation_status,tuab_rejection_reason', ip_address=get_client_ip(request))

            donor = donation.donor
            already_notified = MatchPrediction.objects.filter(
                tuab=request.user,
                item__donation_id=donation.donation_id,
                is_archived_version=False,
                recommendation_status=MatchRecommendationStatus.REJECTED,
            ).exclude(pair_id=pk).exists()

            if not already_notified:
                tuab_name = request.user.business_name or request.user.email
                _notify_data = {
                    'donor_email': donor.email,
                    'donor_name': donor.first_name or 'Donor',
                    'tuab_name': tuab_name,
                    'items_list': [{
                        'brand': match_pred.item.lookup.brand,
                        'clothing_type': match_pred.item.lookup.clothing_type,
                        'condition': match_pred.item.condition_rating,
                        'weight': str(match_pred.item.weight_kg),
                    }],
                }

        if _notify_data:
            send_match_reject_notification(**_notify_data)
        return Response({'pair_id': pk, 'recommendation_status': MatchRecommendationStatus.REJECTED,
                         'tuab_rejection_reason': match_pred.tuab_rejection_reason,
                         'message': 'Recommendation rejected successfully'}, status=status.HTTP_200_OK)
