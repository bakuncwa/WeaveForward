from decimal import Decimal
from datetime import datetime, time
from django.conf import settings
from django.db.models import Count, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Donation, DonationStatus, UserRole
from ..serializers.impact_dashboard import ImpactDashboardSerializer
from ..services.location_service import load_ncr_features


class ImpactDashboardViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ImpactDashboardSerializer

    def list(self, request, *args, **kwargs):
        if request.user.role not in ['Donor', 'Admin']:
            raise PermissionDenied("Only donors and admins can access the impact dashboard.")

        filters = {"status": DonationStatus.RECEIVED}

        if ct := request.query_params.get("clothing_type"):
            filters["items__is_archived"] = False
            filters["items__lookup__clothing_type__iexact"] = ct
        city_filter = request.query_params.get("pickup_city")
        if city_filter:
            filters["pickup_city__iexact"] = city_filter
        if df := request.query_params.get("date_from"):
            try:
                if p := parse_date(df):
                    if settings.USE_TZ:
                        tz = timezone.get_current_timezone()
                        dt_from = datetime.combine(p, time.min).replace(tzinfo=tz)
                    else:
                        dt_from = datetime.combine(p, time.min)
                    filters["updated_at__gte"] = dt_from
            except ValueError:
                pass
        if dt := request.query_params.get("date_to"):
            try:
                if p := parse_date(dt):
                    if settings.USE_TZ:
                        tz = timezone.get_current_timezone()
                        dt_to = datetime.combine(p, time.max).replace(tzinfo=tz)
                    else:
                        dt_to = datetime.combine(p, time.max)
                    filters["updated_at__lte"] = dt_to
            except ValueError:
                pass



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
