"""Extract subscriptions and their payment history."""


def extract_subscriptions() -> list[dict]:
    from backend.models import Subscription

    rows = []
    for s in Subscription.objects.select_related("user").order_by("subscription_id"):
        rows.append({
            "subscription_id":   s.subscription_id,
            "user_id":           s.user_id,
            "status":            s.status,
            "subscription_tier": s.subscription_tier,
            "start_date":        s.start_date.isoformat(),
            "end_date":          s.end_date.isoformat(),
            "created_at":        s.created_at.isoformat(),
            "updated_at":        s.updated_at.isoformat(),
        })
    return rows


def extract_subscription_payments() -> list[dict]:
    from backend.models import SubscriptionPayment

    rows = []
    for p in SubscriptionPayment.objects.select_related("subscription").order_by("payment_id"):
        rows.append({
            "payment_id":        p.payment_id,
            "subscription_id":   p.subscription_id,
            "amount":            float(p.amount),
            "status":            p.status,
            "payment_reference": p.payment_reference,
            "created_at":        p.created_at.isoformat(),
            "updated_at":        p.updated_at.isoformat(),
        })
    return rows
