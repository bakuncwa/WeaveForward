from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Prefetch
from decimal import Decimal
from datetime import datetime
import logging

from ..models import (
    MatchPrediction,
    MatchRecommendationStatus,
    Subscription,
    SubscriptionStatus,
    AuditTrail,
)
from .audit_service import log_audit

logger = logging.getLogger(__name__)


def verify_tuab_subscription(tuab):
    """
    Verify that the TUAB has an active subscription.
    
    Returns:
        tuple: (is_active: bool, error_message: str | None)
    """
    try:
        subscription = Subscription.objects.filter(
            user=tuab,
            status=SubscriptionStatus.ACTIVE
        ).first()
        
        if not subscription:
            return False, "No active subscription found. Please upgrade to access Donation Recommendations."
        
        # Check if subscription is still valid (end_date)
        if subscription.end_date and subscription.end_date <= timezone.now():
            return False, "Subscription has expired. Please renew to access Donation Recommendations."
        
        return True, None
    except Exception as e:
        logger.error(f"Error verifying subscription for user {tuab.user_id}: {str(e)}")
        return False, "Unable to verify subscription status. Please try again."


def get_pending_recommendations(tuab, filters=None):
    """
    Get pending match recommendations for a TUAB with optional filtering.
    
    Args:
        tuab: User instance (TUAB)
        filters: dict with optional keys:
            - fiber_types: list of fiber types to filter
            - biodeg_tier: 'HIGH', 'MEDIUM', or 'LOW'
            - city: pickup city
            - confidence_min: min match probability (0-1)
            - confidence_max: max match probability (0-1)
            - date_after: datetime for pickup date filter
            - date_before: datetime for pickup date filter
    
    Returns:
        QuerySet of MatchPrediction objects
    """
    if filters is None:
        filters = {}
    
    # Base queryset: pending recommendations for this TUAB, ordered by confidence
    queryset = MatchPrediction.objects.filter(
        tuab=tuab,
        recommendation_status=MatchRecommendationStatus.PENDING,
        is_archived_version=False,
    ).select_related(
        'item',
        'item__lookup',
        'item__donation',
        'item__donation__donor',
        'tuab',
    ).order_by('-match_prob')
    
    # Apply filters
    if filters.get('fiber_types'):
        fiber_types = filters['fiber_types']
        if isinstance(fiber_types, str):
            fiber_types = [f.strip().lower() for f in fiber_types.split(',')]
        else:
            fiber_types = [f.lower() for f in fiber_types]
        
        # Filter by checking lookup brand or fiber_json
        # This is a simplified approach; may need optimization for large datasets
        q_objects = Q()
        for fiber_type in fiber_types:
            q_objects |= Q(item__lookup__brand__icontains=fiber_type)
        queryset = queryset.filter(q_objects)
    
    if filters.get('city'):
        queryset = queryset.filter(
            item__donation__pickup_city__icontains=filters['city']
        )
    
    if filters.get('confidence_min') is not None:
        queryset = queryset.filter(
            match_prob__gte=Decimal(str(filters['confidence_min']))
        )
    
    if filters.get('confidence_max') is not None:
        queryset = queryset.filter(
            match_prob__lte=Decimal(str(filters['confidence_max']))
        )
    
    if filters.get('date_after'):
        date_after = filters['date_after']
        if isinstance(date_after, str):
            date_after = datetime.fromisoformat(date_after.replace('Z', '+00:00'))
        queryset = queryset.filter(
            item__donation__preferred_pickup_date__gte=date_after
        )
    
    if filters.get('date_before'):
        date_before = filters['date_before']
        if isinstance(date_before, str):
            date_before = datetime.fromisoformat(date_before.replace('Z', '+00:00'))
        queryset = queryset.filter(
            item__donation__preferred_pickup_date__lte=date_before
        )
    
    return queryset


@transaction.atomic
def accept_recommendation(pair_id, tuab, client_ip=None):
    """
    Accept a match recommendation and initiate donation intake workflow.
    
    Args:
        pair_id: MatchPrediction.pair_id
        tuab: User instance (TUAB)
        client_ip: Client IP for audit logging
    
    Returns:
        dict: {
            'success': bool,
            'message': str,
            'pair_id': int (on success),
            'recommendation_status': str (on success)
        }
    """
    try:
        match_pred = MatchPrediction.objects.select_for_update().get(
            pair_id=pair_id,
            tuab=tuab,
            recommendation_status=MatchRecommendationStatus.PENDING,
        )
    except MatchPrediction.DoesNotExist:
        return {
            'success': False,
            'message': 'Recommendation not found or no longer pending.',
        }
    
    try:
        # Update recommendation status
        match_pred.recommendation_status = MatchRecommendationStatus.ACCEPTED
        match_pred.save(update_fields=['recommendation_status'])
        
        # Log audit trail
        log_audit(
            actor=tuab,
            entity_type='MatchPrediction',
            action='ACCEPT_RECOMMENDATION',
            fields_modified='recommendation_status',
            ip_address=client_ip,
        )
        
        logger.info(f"TUAB {tuab.user_id} accepted recommendation {pair_id}")
        
        return {
            'success': True,
            'message': 'Recommendation accepted successfully.',
            'pair_id': pair_id,
            'recommendation_status': MatchRecommendationStatus.ACCEPTED,
        }
    except Exception as e:
        logger.error(f"Error accepting recommendation {pair_id}: {str(e)}")
        raise


@transaction.atomic
def reject_recommendation(pair_id, tuab, reason=None, client_ip=None):
    """
    Reject a match recommendation with optional reason.
    
    Args:
        pair_id: MatchPrediction.pair_id
        tuab: User instance (TUAB)
        reason: Rejection reason (optional)
        client_ip: Client IP for audit logging
    
    Returns:
        dict: {
            'success': bool,
            'message': str,
            'pair_id': int (on success),
            'recommendation_status': str (on success),
            'tuab_rejection_reason': str (on success)
        }
    """
    try:
        match_pred = MatchPrediction.objects.select_for_update().get(
            pair_id=pair_id,
            tuab=tuab,
            recommendation_status=MatchRecommendationStatus.PENDING,
        )
    except MatchPrediction.DoesNotExist:
        return {
            'success': False,
            'message': 'Recommendation not found or no longer pending.',
        }
    
    try:
        # Update recommendation status and reason
        match_pred.recommendation_status = MatchRecommendationStatus.REJECTED
        match_pred.tuab_rejection_reason = reason if reason and reason.strip() else None
        match_pred.save(update_fields=['recommendation_status', 'tuab_rejection_reason'])
        
        # Log audit trail
        log_audit(
            actor=tuab,
            entity_type='MatchPrediction',
            action='REJECT_RECOMMENDATION',
            fields_modified='recommendation_status,tuab_rejection_reason',
            ip_address=client_ip,
        )
        
        logger.info(f"TUAB {tuab.user_id} rejected recommendation {pair_id}")
        
        return {
            'success': True,
            'message': 'Recommendation rejected successfully.',
            'pair_id': pair_id,
            'recommendation_status': MatchRecommendationStatus.REJECTED,
            'tuab_rejection_reason': match_pred.tuab_rejection_reason,
        }
    except Exception as e:
        logger.error(f"Error rejecting recommendation {pair_id}: {str(e)}")
        raise
