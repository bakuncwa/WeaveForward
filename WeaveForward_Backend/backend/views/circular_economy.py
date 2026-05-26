from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import (
    DonationItem, MatchPrediction, MatchRecommendationStatus, UserRole,
)


class TuabCircularEconomyViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        if request.user.role != UserRole.TUAB:
            raise PermissionDenied("Only TUABs can access this dashboard.")

        tuab = request.user
        date_filters = {}

        if df := request.query_params.get("date_from"):
            try:
                if p := parse_date(df):
                    tz = timezone.get_current_timezone() if settings.USE_TZ else None
                    dt_from = datetime.combine(p, time.min)
                    if tz:
                        dt_from = dt_from.replace(tzinfo=tz)
                    date_filters["predicted_at__gte"] = dt_from
            except ValueError:
                pass

        if dt := request.query_params.get("date_to"):
            try:
                if p := parse_date(dt):
                    tz = timezone.get_current_timezone() if settings.USE_TZ else None
                    dt_to = datetime.combine(p, time.max)
                    if tz:
                        dt_to = dt_to.replace(tzinfo=tz)
                    date_filters["predicted_at__lte"] = dt_to
            except ValueError:
                pass

        # All non-archived predictions for this TUAB (used for decisions panel)
        pred_qs = MatchPrediction.objects.filter(
            tuab=tuab,
            is_archived_version=False,
            **date_filters,
        ).select_related("item__lookup", "item__donation")

        # Analytics panels are scoped to ACCEPTED predictions only so they
        # align with what is actually entering (or has entered) inventory.
        accepted_item_ids = pred_qs.filter(
            recommendation_status=MatchRecommendationStatus.ACCEPTED,
        ).values_list("item_id", flat=True).distinct()

        # 1. Biodegradability score distribution (buckets from DonationItems)
        items_qs = DonationItem.objects.filter(item_id__in=accepted_item_ids).select_related("lookup")

        biodeg_buckets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
        for item in items_qs:
            score = float(item.lookup.biodeg_score or 0)
            if score < 20:
                biodeg_buckets["0-20"] += 1
            elif score < 40:
                biodeg_buckets["20-40"] += 1
            elif score < 60:
                biodeg_buckets["40-60"] += 1
            elif score < 80:
                biodeg_buckets["60-80"] += 1
            else:
                biodeg_buckets["80-100"] += 1

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

        # 4. Donation decisions by city (ACCEPTED / REJECTED / PENDING counts)
        decision_rows = (
            pred_qs
            .values("item__donation__pickup_city", "recommendation_status")
            .annotate(count=Count("pair_id"))
        )
        decisions_map: dict[str, dict] = {}
        for r in decision_rows:
            city = r["item__donation__pickup_city"] or "Unknown"
            status = r["recommendation_status"]
            if city not in decisions_map:
                decisions_map[city] = {"city": city, "accepted": 0, "rejected": 0, "pending": 0}
            key = status.lower() if status else "pending"
            if key in decisions_map[city]:
                decisions_map[city][key] += r["count"]
        decisions_by_city = list(decisions_map.values())

        return Response({
            "biodeg_distribution": biodeg_distribution,
            "volume_by_city_fiber": volume_by_city_fiber,
            "top_brands": top_brands,
            "decisions_by_city": decisions_by_city,
        })
