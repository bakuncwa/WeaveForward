from django.db import transaction
from ..models import User, Subscription, SubscriptionStatus

def unsubscribe_user(*, target_user_id):
    """
    Cancels all active subscriptions for a user and clears their Maya payment information.
    Uses transaction.atomic() and select_for_update() for data consistency and locking.
    """
    with transaction.atomic():
        try:
            # Lock the user record
            user = User.objects.select_for_update().get(pk=target_user_id)
        except User.DoesNotExist:
            return {
                "status_code": 404,
                "detail": "User not found.",
                "user_updated": False,
                "cancelled_subscriptions_count": 0
            }

        # Lock and fetch active subscriptions
        active_subscriptions = list(
            Subscription.objects.select_for_update()
            .filter(user=user, status=SubscriptionStatus.ACTIVE)
        )

        for sub in active_subscriptions:
            sub.status = SubscriptionStatus.CANCELLED
        
        if active_subscriptions:
            Subscription.objects.bulk_update(active_subscriptions, ['status'])

        # Clear Maya IDs
        user.maya_customer_id = None
        user.maya_card_id = None
        user.save(update_fields=['maya_customer_id', 'maya_card_id', 'updated_at'])

        return {
            "status_code": 200,
            "detail": "Successfully unsubscribed.",
            "user_updated": True,
            "cancelled_subscriptions_count": len(active_subscriptions)
        }
