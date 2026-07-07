import json
from datetime import datetime, time

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..models import Donation, DonationItem, DonationStatus, UserRole
from ..permissions import IsActiveAdminOrTUABWithActiveSubscription


class TuabCircularEconomyViewSet(viewsets.GenericViewSet):
    permission_classes = [IsActiveAdminOrTUABWithActiveSubscription]

    def list(self, request, *args, **kwargs):
        # Overall complexity by dashboard section:
        # 1. Biodegradability distribution: O(d + i + 10)
        # 2. City/fiber volume: O(d + i + g log g + g)
        # 3. Top 20 brands: O(d + i + b log b + 20)
        # 4. Decisions by city: O(d + c log c + c)
        # Overall: O((d + i + 10) + (d + i + g log g + g) +
        #            (d + i + b log b + 20) + (d + c log c + c))
        # Combined overall: O(d + i + g log g + g + b log b + c log c + c)
        # Simplified overall: O(d + i + g log g + b log b + c log c)
        # where d = matching donations, i = matching donation items,
        # g = grouped city/fiber rows, b = grouped brand rows, and
        # c = grouped city decision rows.
        # SQL query count inside this method: 4. Permission checks run before this method.

        donation_filters = {"status__in": [DonationStatus.RECEIVED, DonationStatus.REJECTED]}
        if request.user.role == UserRole.TUAB:
            donation_filters["claimed_by_tuab"] = request.user
        errors = {}

        if settings.USE_TZ:
            today = timezone.localdate()
            tz = timezone.get_current_timezone()
        else:
            today = datetime.now().date()
            tz = None

        if df := request.query_params.get("date_from"):
            try:
                if p := parse_date(df):
                    dt_from = datetime.combine(p, time.min)
                    if tz:
                        dt_from = dt_from.replace(tzinfo=tz)
                    if p > today:
                        errors["date_from"] = "Date cannot be in the future."
                    else:
                        donation_filters["updated_at__gte"] = dt_from
                else:
                    errors["date_from"] = "Please enter a valid start date in YYYY-MM-DD format."
            except ValueError:
                errors["date_from"] = "Please enter a valid start date in YYYY-MM-DD format."

        if dt := request.query_params.get("date_to"):
            try:
                if p := parse_date(dt):
                    dt_to = datetime.combine(p, time.max)
                    if tz:
                        dt_to = dt_to.replace(tzinfo=tz)
                    if p > today:
                        errors["date_to"] = "Date cannot be in the future."
                    else:
                        donation_filters["updated_at__lte"] = dt_to
                else:
                    errors["date_to"] = "Please enter a valid end date in YYYY-MM-DD format."
            except ValueError:
                errors["date_to"] = "Please enter a valid end date in YYYY-MM-DD format."

        if "updated_at__gte" in donation_filters and "updated_at__lte" in donation_filters:
            if donation_filters["updated_at__gte"] > donation_filters["updated_at__lte"]:
                errors["date_range"] = "Please choose a start date that is on or before the end date."

        if errors:
            raise ValidationError(errors)

        _d = donation_filters
        date_q = Q()
        if "updated_at__gte" in _d:
            v = _d.pop("updated_at__gte")
            date_q &= Q(Q(status=DonationStatus.RECEIVED, inventory_ledger_entries__ingested_at__gte=v) | Q(status=DonationStatus.REJECTED, updated_at__gte=v))
        if "updated_at__lte" in _d:
            v = _d.pop("updated_at__lte")
            date_q &= Q(Q(status=DonationStatus.RECEIVED, inventory_ledger_entries__ingested_at__lte=v) | Q(status=DonationStatus.REJECTED, updated_at__lte=v))
        donations_qs = Donation.objects.filter(date_q, **_d)
        received_donations_qs = donations_qs.filter(status=DonationStatus.RECEIVED)

        # 1. Biodegradability score distribution
        items_qs = DonationItem.objects.filter(donation__in=received_donations_qs, is_archived=False).select_related("donation", "lookup")

        biodeg_buckets = {f"{i}-{i+10}": 0 for i in range(0, 100, 10)}
        for item in items_qs:
            score = float(item.lookup.biodeg_score or 0)
            bucket = min(int(score // 10) * 10, 90)
            biodeg_buckets[f"{bucket}-{bucket+10}"] += 1

        biodeg_distribution = [
            {"range": k, "count": v}
            for k, v in biodeg_buckets.items()
        ]

        # 2. Donation weight by city stacked by full fiber composition
        city_fiber_rows = {}
        for item in items_qs:
            for fiber, pct in json.loads(item.lookup.fiber_json).items():
                key = (item.donation.pickup_city, fiber.lower())
                city_fiber_rows[key] = city_fiber_rows.get(key, 0) + float(item.weight_kg) * float(pct) / 100
        volume_by_city_fiber = [
            {
                "city": city,
                "fiber": fiber,
                "weight_kg": round(weight_kg, 2),
            }
            for (city, fiber), weight_kg in sorted(city_fiber_rows.items())
        ]

        # 3. Top 20 brands by donation weight
        # Rough SQL:
        # SELECT brand_fiber_lookups.brand,
        #        SUM(donation_items.weight_kg) AS weight_kg,
        #        COUNT(donation_items.item_id) AS item_count
        # FROM donation_items
        # JOIN brand_fiber_lookups ON donation_items.lookup_id = brand_fiber_lookups.lookup_id
        # WHERE donation_items.donation_id IN (...filtered donation ids...)
        # GROUP BY brand_fiber_lookups.brand
        # ORDER BY weight_kg DESC
        # LIMIT 20;
        # Complexity: O(d + i + b log b + 20), where d is the number of
        # matching RECEIVED/REJECTED donations, i is the number of matching
        # donation items, and b is the number of grouped brand rows. The final
        # list formatting handles at most 20 rows because of [:20].
        top_brands_rows = (
            items_qs
            .values("lookup__brand")
            .annotate(weight_kg=Sum("weight_kg"), item_count=Count("item_id"))
            .order_by("-item_count")[:20]
        )
        top_brands = [
            {
                "brand": r["lookup__brand"] or "Unknown",
                "weight_kg": float(r["weight_kg"] or 0),
                "item_count": r["item_count"],
            }
            for r in top_brands_rows
        ]

        # 4. Donation decisions by city (RECEIVED = accepted, REJECTED = rejected)
        # Rough SQL:
        # SELECT donations.pickup_city,
        #        COUNT(donation_id) FILTER (WHERE status = RECEIVED) AS accepted,
        #        COUNT(donation_id) FILTER (WHERE status = REJECTED) AS rejected,
        # FROM donations
        # WHERE ...donation_filters...
        # GROUP BY donations.pickup_city
        # ORDER BY donations.pickup_city;
        # Complexity: O(d + c log c + c), where d is the number of matching
        # donations and c is the number of grouped city rows.
        decision_rows = (
            donations_qs
            .values("pickup_city")
            .annotate(
                accepted=Count("donation_id", filter=Q(status=DonationStatus.RECEIVED)),
                rejected=Count("donation_id", filter=Q(status=DonationStatus.REJECTED)),
            )
            .order_by("pickup_city")
        )
        decisions_by_city = [
            {
                "city": r["pickup_city"] or "Unknown",
                "accepted": r["accepted"],
                "rejected": r["rejected"],
            }
            for r in decision_rows
        ]

        return Response({
            "biodeg_distribution": biodeg_distribution,
            "volume_by_city_fiber": volume_by_city_fiber,
            "top_brands": top_brands,
            "decisions_by_city": decisions_by_city,
        })
