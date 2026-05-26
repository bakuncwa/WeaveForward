from decimal import Decimal
from datetime import datetime, time
from django.conf import settings
from django.db.models import Count, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import BrandFiberLookup, Donation, DonationStatus, UserRole
from ..serializers.impact_dashboard import ImpactDashboardSerializer
from ..services.location_service import load_ncr_features


class ImpactDashboardViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ImpactDashboardSerializer

    def list(self, request, *args, **kwargs):
        if request.user.role not in ['Donor', 'Admin']:
            raise PermissionDenied("Only donors and admins can access the impact dashboard.")

        # Query flow notes:
        # - This endpoint builds one filtered Donation queryset and then reuses that
        #   filtered base for several summary queries.
        # - The filtered base is built lazily here; SQL is not sent until count(),
        #   annotate(), or other queryset-evaluating calls run.
        # - The dashboard then runs separate SQL queries for:
        #   1) total donations
        #   2) distinct donors
        #   3) top 10 donors
        #   4) barangay breakdown
        #
        # SQL shape:
        #   base_qs is the filtered donation queryset that the dashboard reuses for
        #   its summary queries.
        #
        #   The inner filtered donation-id set is:
        #     SELECT DISTINCT d2.donation_id
        #     FROM donations d2
        #     WHERE <filters>
        #
        #   Django wraps that in an outer Donation queryset so it can reuse the same
        #   filtered donation set for count(), donor grouping, and barangay grouping.
        #
        #   donations count:
        #     SELECT COUNT(*)
        #     FROM donations d
        #     WHERE d.donation_id IN (
        #         SELECT DISTINCT d2.donation_id
        #         FROM donations d2
        #         WHERE <filters>
        #     )
        #
        #   donors count:
        #     SELECT COUNT(DISTINCT d.donor_id)
        #     FROM donations d
        #     JOIN users u ON d.donor_id = u.user_id
        #     WHERE d.donation_id IN (
        #         SELECT DISTINCT d2.donation_id
        #         FROM donations d2
        #         WHERE <filters>
        #     )
        #     AND u.role = 'Donor'
        #
        #   top donors:
        #     SELECT d.donor_id, u.first_name, u.last_name, COUNT(d.donation_id) AS donation_count
        #     FROM donations d
        #     JOIN users u ON d.donor_id = u.user_id
        #     WHERE d.donation_id IN (
        #         SELECT DISTINCT d2.donation_id
        #         FROM donations d2
        #         WHERE <filters>
        #     )
        #     AND u.role = 'Donor'
        #     GROUP BY d.donor_id, u.first_name, u.last_name
        #     ORDER BY donation_count DESC
        #     LIMIT 10;
        #
        #   barangay breakdown:
        #     SELECT d.pickup_barangay, d.pickup_city, COUNT(d.donation_id) AS donation_count
        #     FROM donations d
        #     WHERE d.donation_id IN (
        #         SELECT DISTINCT d2.donation_id
        #         FROM donations d2
        #         WHERE <filters>
        #     )
        #     GROUP BY d.pickup_barangay, d.pickup_city
        #     ORDER BY donation_count DESC;
        #
        # Complexity notes:
        # - F = number of NCR geo features loaded from load_ncr_features()
        # - L = number of active clothing types loaded from BrandFiberLookup
        # - D = number of donations that match the filters
        # - G = number of grouped barangay rows returned
        # - Overall: O(F + L + D + G)
        # - Simplified: O(n)
        filters = {"status": DonationStatus.RECEIVED}
        errors = {}

        valid_cities = {
            city.lower()
            for _, _, city in load_ncr_features()
            if city
        }
        valid_clothing_types = {
            clothing_type.lower()
            for clothing_type in BrandFiberLookup.objects.filter(is_active=True)
            .values_list("clothing_type", flat=True)
            .distinct()
            if clothing_type
        }

        if ct := request.query_params.get("clothing_type"):
            if ct.lower() not in valid_clothing_types:
                errors["clothing_type"] = "Invalid clothing_type."
            else:
                filters["items__is_archived"] = False
                filters["items__lookup__clothing_type__iexact"] = ct
        city_filter = request.query_params.get("pickup_city")
        if city_filter:
            if city_filter.lower() not in valid_cities:
                errors["pickup_city"] = "Invalid pickup_city."
            else:
                filters["pickup_city__iexact"] = city_filter

        if df := request.query_params.get("date_from"):
            try:
                if p := parse_date(df):
                    if settings.USE_TZ:
                        tz = timezone.get_current_timezone()
                        today = timezone.localdate()
                        dt_from = datetime.combine(p, time.min).replace(tzinfo=tz)
                    else:
                        today = datetime.now().date()
                        dt_from = datetime.combine(p, time.min)
                    if p > today:
                        errors["date_from"] = "Date cannot be in the future."
                    else:
                        filters["updated_at__gte"] = dt_from
                else:
                    errors["date_from"] = "Invalid date_from."
            except ValueError:
                errors["date_from"] = "Invalid date_from."

        if dt := request.query_params.get("date_to"):
            try:
                if p := parse_date(dt):
                    if settings.USE_TZ:
                        tz = timezone.get_current_timezone()
                        today = timezone.localdate()
                        dt_to = datetime.combine(p, time.max).replace(tzinfo=tz)
                    else:
                        today = datetime.now().date()
                        dt_to = datetime.combine(p, time.max)
                    if p > today:
                        errors["date_to"] = "Date cannot be in the future."
                    else:
                        filters["updated_at__lte"] = dt_to
                else:
                    errors["date_to"] = "Invalid date_to."
            except ValueError:
                errors["date_to"] = "Invalid date_to."

        if "updated_at__gte" in filters and "updated_at__lte" in filters:
            if filters["updated_at__gte"] > filters["updated_at__lte"]:
                errors["date_range"] = "Please choose a start date that is on or before the end date."

        if errors:
            raise ValidationError(errors)


        base_qs = Donation.objects.filter(donation_id__in=Subquery(
            Donation.objects.filter(**filters).values_list("donation_id", flat=True).distinct()
        ))

        coords = {}
        for geo, brgy, city_name in load_ncr_features():
            if city_filter and city_name and city_name.lower() != city_filter.lower():
                continue
            ring = geo["coordinates"][0] if geo["type"] == "Polygon" else geo["coordinates"][0][0]
            lons = [p[0] for p in ring]; lats = [p[1] for p in ring]
            coords[(brgy.lower(), city_name.lower() if city_name else "")] = (sum(lats) / len(lats), sum(lons) / len(lons))

        def key(e):
            return (e["pickup_barangay"].lower(), e["pickup_city"].lower() if e["pickup_city"] else "")

        serializer = self.get_serializer({
            "donations": base_qs.count(),
            "donors": base_qs.filter(donor__role=UserRole.DONOR).values("donor").distinct().count(),
            "top_donors": [
                {"full_name": (f"{d['donor__first_name'] or ''} {d['donor__last_name'] or ''}").strip() or None,
                 "donation_count": d["donation_count"]}
                for d in base_qs.filter(donor__role=UserRole.DONOR).values("donor_id", "donor__first_name", "donor__last_name")
                .annotate(donation_count=Count("donation_id")).order_by("-donation_count")[:10]
            ],
            "barangay_breakdown": [
                {"barangay": e["pickup_barangay"],
                 "latitude": Decimal(f"{c[0]:.7f}") if (c := coords.get(key(e))) is not None else None,
                 "longitude": Decimal(f"{c[1]:.7f}") if c is not None else None,
                 "donation_count": e["donation_count"]}
                for e in base_qs.values("pickup_barangay", "pickup_city")
                .annotate(donation_count=Count("donation_id")).order_by("-donation_count")
            ],
        })
        return Response(serializer.data)
