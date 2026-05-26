from datetime import datetime, time

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Donation, DonationItem, DonationStatus, UserRole


class TuabCircularEconomyViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        if request.user.role != UserRole.TUAB:
            raise PermissionDenied("Only TUABs can access this dashboard.")

        donation_filters = {"status__in": [DonationStatus.RECEIVED, DonationStatus.REJECTED, DonationStatus.PENDING]}

        if df := request.query_params.get("date_from"):
            try:
                if p := parse_date(df):
                    tz = timezone.get_current_timezone() if settings.USE_TZ else None
                    dt_from = datetime.combine(p, time.min)
                    if tz:
                        dt_from = dt_from.replace(tzinfo=tz)
                    donation_filters["updated_at__gte"] = dt_from
            except ValueError:
                pass

        if dt := request.query_params.get("date_to"):
            try:
                if p := parse_date(dt):
                    tz = timezone.get_current_timezone() if settings.USE_TZ else None
                    dt_to = datetime.combine(p, time.max)
                    if tz:
                        dt_to = dt_to.replace(tzinfo=tz)
                    donation_filters["updated_at__lte"] = dt_to
            except ValueError:
                pass

        donations_qs = Donation.objects.filter(**donation_filters)

        # 1. Biodegradability score distribution
        items_qs = DonationItem.objects.filter(donation__in=donations_qs).select_related("lookup")

        biodeg_buckets = {f"{i}-{i+10}": 0 for i in range(0, 100, 10)}
        for item in items_qs:
            score = float(item.lookup.biodeg_score or 0)
            bucket = min(int(score // 10) * 10, 90)
            biodeg_buckets[f"{bucket}-{bucket+10}"] += 1

        biodeg_distribution = [
            {"range": k, "count": v}
            for k, v in biodeg_buckets.items()
        ]

        # 2. Donation volume by city stacked by dominant fiber
        city_fiber_rows = (
            items_qs
            .values("donation__pickup_city", "lookup__dominant_fiber")
            .annotate(weight_kg=Sum("weight_kg"), item_count=Count("item_id"))
            .order_by("donation__pickup_city", "lookup__dominant_fiber")
        )
        volume_by_city_fiber = [
            {
                "city": r["donation__pickup_city"] or "Unknown",
                "fiber": (r["lookup__dominant_fiber"] or "other").lower(),
                "weight_kg": float(r["weight_kg"] or 0),
                "item_count": r["item_count"],
            }
            for r in city_fiber_rows
        ]

        # 3. Top 20 brands by donation weight
        top_brands_rows = (
            items_qs
            .values("lookup__brand")
            .annotate(weight_kg=Sum("weight_kg"), item_count=Count("item_id"))
            .order_by("-weight_kg")[:20]
        )
        top_brands = [
            {
                "brand": r["lookup__brand"] or "Unknown",
                "weight_kg": float(r["weight_kg"] or 0),
                "item_count": r["item_count"],
            }
            for r in top_brands_rows
        ]

        # 4. Donation decisions by city (RECEIVED = accepted, REJECTED = rejected, PENDING = pending)
        decision_rows = (
            donations_qs
            .values("pickup_city")
            .annotate(
                accepted=Count("donation_id", filter=Q(status=DonationStatus.RECEIVED)),
                rejected=Count("donation_id", filter=Q(status=DonationStatus.REJECTED)),
                pending=Count("donation_id", filter=Q(status=DonationStatus.PENDING)),
            )
            .order_by("pickup_city")
        )
        decisions_by_city = [
            {
                "city": r["pickup_city"] or "Unknown",
                "accepted": r["accepted"],
                "rejected": r["rejected"],
                "pending": r["pending"],
            }
            for r in decision_rows
        ]

        return Response({
            "biodeg_distribution": biodeg_distribution,
            "volume_by_city_fiber": volume_by_city_fiber,
            "top_brands": top_brands,
            "decisions_by_city": decisions_by_city,
        })
