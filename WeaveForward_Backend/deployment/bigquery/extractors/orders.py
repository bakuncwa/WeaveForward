"""Extract delivery orders and their payment records."""


def extract_orders() -> list[dict]:
    from backend.models import Order

    rows = []
    for o in Order.objects.select_related("donation").order_by("order_id"):
        rows.append({
            "order_id":                o.order_id,
            "donation_id":             o.donation_id,
            "lalamove_order_id":       o.lalamove_order_id,
            "status":                  o.status,
            "dropoff_display_address": o.dropoff_display_address,
            "dropoff_latitude":        float(o.dropoff_latitude),
            "dropoff_longitude":       float(o.dropoff_longitude),
            "has_been_edited":         o.has_been_edited,
            "no_reassigned":           o.no_reassigned,
            "scheduled_at":            o.scheduled_at.isoformat()  if o.scheduled_at else None,
            "expires_at":              o.expires_at.isoformat()    if o.expires_at    else None,
            "created_at":              o.created_at.isoformat(),
            "updated_at":              o.updated_at.isoformat(),
        })
    return rows


def extract_order_payments() -> list[dict]:
    from backend.models import OrderPayment

    rows = []
    for p in OrderPayment.objects.select_related("order").order_by("order_payment_id"):
        rows.append({
            "order_payment_id":  p.order_payment_id,
            "order_id":          p.order_id,
            "donation_id":       p.order.donation_id,
            "amount":            float(p.amount),
            "status":            p.status,
            "payment_reference": p.payment_reference,
            "created_at":        p.created_at.isoformat(),
            "updated_at":        p.updated_at.isoformat(),
        })
    return rows
