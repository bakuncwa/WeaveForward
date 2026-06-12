from decimal import Decimal
from datetime import datetime, time
from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..models import Donation, DonationStatus, UserRole
from ..permissions import IsActiveAdminOrDonor
from ..serializers.impact_dashboard import ImpactDashboardSerializer
from ..services.location_service import load_ncr_features


class ImpactDashboardViewSet(viewsets.GenericViewSet):
    permission_classes = [IsActiveAdminOrDonor]
    serializer_class = ImpactDashboardSerializer

    def list(self, request, *args, **kwargs):
        # Query flow notes:
        # - This endpoint builds one filtered Donation queryset and reuses it
        #   for several dashboard summaries.
        # - The queryset is lazy. SQL is only sent when count(), annotate(),
        #   order_by(), or iteration actually runs.
        # - The dashboard does four main database reads:
        #   1) total donations
        #   2) distinct donor count
        #   3) top donors grouped by donor and ordered by donation_count
        #   4) barangay breakdown grouped by barangay/city and ordered by donation_count
        #
        # SQL shape:
        #   base_qs is the filtered donation queryset:
        #     SELECT DISTINCT *
        #     FROM donations
        #     WHERE <filters>;
        #
        #   donations count:
        #     SELECT COUNT(*)
        #     FROM donations
        #     WHERE <filters>;
        #
        #   donors count:
        #     SELECT COUNT(DISTINCT donor_id)
        #     FROM donations
        #     JOIN users ON donations.donor_id = users.user_id
        #     WHERE <filters> AND users.role = 'Donor';
        #
        #   top donors:
        #     SELECT donor_id, first_name, last_name, COUNT(donation_id) AS donation_count
        #     FROM donations
        #     JOIN users ON donations.donor_id = users.user_id
        #     WHERE <filters> AND users.role = 'Donor'
        #     GROUP BY donor_id, first_name, last_name
        #     ORDER BY donation_count DESC
        #     LIMIT 10;
        #
        #   barangay breakdown:
        #     SELECT pickup_barangay, pickup_city, COUNT(donation_id) AS donation_count
        #     FROM donations
        #     WHERE <filters>
        #     GROUP BY pickup_barangay, pickup_city
        #     ORDER BY donation_count DESC;
        #
        # Overall complexity by dashboard section:
        # 1. Coordinates from NCR features: O(f + f)
        # 2. Top donors: O(d + u log u + 10)
        # 3. Barangay breakdown: O(d + b log b + b)
        # 4. Total donation count: O(d)
        # 5. Distinct donor count: O(d)
        # Overall: O((f + f) + (d + u log u + 10) +
        #            (d + b log b + b) + d + d)
        # Combined overall: O(f + d + u log u + b log b + b)
        # Simplified worst case: O(f + d log d)
        # where f = NCR geo features, d = matching received donations,
        # u = grouped unique donor rows, and b = grouped barangay/city rows.
        filters = {"status": DonationStatus.RECEIVED}
        features = load_ncr_features()

        clothing_type = request.query_params.get("clothing_type")
        if clothing_type:
            filters["items__is_archived"] = False
            filters["items__lookup__clothing_type__iexact"] = clothing_type

        city_filter = request.query_params.get("pickup_city")
        if city_filter:
            filters["pickup_city__iexact"] = city_filter

        today = timezone.now().date()
        current_timezone = timezone.get_current_timezone()

        date_from = request.query_params.get("date_from")
        if date_from:
            parsed_date_from = parse_date(date_from)
            if parsed_date_from is None or parsed_date_from > today:
                raise ValidationError({"date": "Invalid date."})
            date_from_bound = datetime.combine(parsed_date_from, time.min)
            date_from_bound = timezone.make_aware(date_from_bound, current_timezone)
            filters["updated_at__gte"] = date_from_bound

        date_to = request.query_params.get("date_to")
        if date_to:
            parsed_date_to = parse_date(date_to)
            if parsed_date_to is None or parsed_date_to > today:
                raise ValidationError({"date": "Invalid date."})
            date_to_bound = datetime.combine(parsed_date_to, time.max)
            date_to_bound = timezone.make_aware(date_to_bound, current_timezone)
            filters["updated_at__lte"] = date_to_bound

        if date_from and date_to and filters["updated_at__gte"] > filters["updated_at__lte"]:
            raise ValidationError({"date": "Invalid date."})

        base_qs = Donation.objects.filter(**filters).distinct()

        coords = {}
        for geo, brgy, city_name in features:
            if geo["type"] == "Polygon":
                first_point = geo["coordinates"][0][0]
            else:
                first_point = geo["coordinates"][0][0][0]

            barangay_name = brgy.lower()
            city_name_key = city_name.lower() if city_name else ""
            longitude = first_point[0]
            latitude = first_point[1]
            coords[(barangay_name, city_name_key)] = (latitude, longitude)

        top_donors = []
        for donor in (
            base_qs
            .filter(donor__role=UserRole.DONOR)
            .values("donor_id", "donor__first_name", "donor__last_name")
            .annotate(donation_count=Count("donation_id"))
            .order_by("-donation_count")[:10]
        ):
            first_name = donor["donor__first_name"] or ""
            last_name = donor["donor__last_name"] or ""
            full_name = f"{first_name} {last_name}".strip() or None
            top_donors.append({
                "full_name": full_name,
                "donation_count": donor["donation_count"],
            })

        barangay_breakdown = []
        for row in (
            base_qs
            .values("pickup_barangay", "pickup_city")
            .annotate(donation_count=Count("donation_id"))
            .order_by("-donation_count")
        ):
            coord_key = (
                row["pickup_barangay"].lower(),
                row["pickup_city"].lower() if row["pickup_city"] else "",
            )
            coordinate = coords.get(coord_key)

            latitude = None
            longitude = None
            if coordinate is not None:
                latitude = Decimal(f"{coordinate[0]:.7f}")
                longitude = Decimal(f"{coordinate[1]:.7f}")

            barangay_breakdown.append({
                "barangay": row["pickup_barangay"],
                "latitude": latitude,
                "longitude": longitude,
                "donation_count": row["donation_count"],
            })

        serializer = self.get_serializer({
            "donations": base_qs.count(),
            "donors": base_qs.filter(donor__role=UserRole.DONOR).values("donor").distinct().count(),
            "top_donors": top_donors,
            "barangay_breakdown": barangay_breakdown,
        })
        return Response(serializer.data)
