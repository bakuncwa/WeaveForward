import json
from rest_framework import serializers
from ..models import MatchPrediction, Donation, DonationItem, User, BrandFiberLookup
from ..services.prediction_service import BIO_FIBERS, MatchPredictionService


def _biodeg_tier_from_fibers(fiber_json):
    if not fiber_json:
        return 'MEDIUM'
    if MatchPredictionService._metadata:
        score = MatchPredictionService._compute_biodeg_score(fiber_json)
        return MatchPredictionService._compute_biodeg_tier(score).upper()
    dominant = max(fiber_json, key=fiber_json.get)
    if dominant.lower() in BIO_FIBERS:
        pct = fiber_json.get(dominant, 0)
        if pct >= 80:
            return 'HIGH'
        if pct >= 50:
            return 'MEDIUM'
        return 'LOW'
    return 'LOW'


class DonationPreviewSerializer(serializers.ModelSerializer):
    pickup_barangay = serializers.SerializerMethodField()
    pickup_city = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    pickup_window = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = ['donation_id', 'pickup_barangay', 'pickup_city', 'location', 'pickup_window', 'preferred_pickup_date']

    def get_pickup_barangay(self, obj): return obj.pickup_barangay
    def get_pickup_city(self, obj): return obj.pickup_city

    def get_location(self, obj):
        return {'latitude': float(obj.pickup_latitude), 'longitude': float(obj.pickup_longitude)}

    def get_pickup_window(self, obj):
        if obj.preferred_pickup_window_start and obj.preferred_pickup_window_end:
            return {'start': obj.preferred_pickup_window_start.isoformat(), 'end': obj.preferred_pickup_window_end.isoformat()}
        return None


class DonationItemPreviewSerializer(serializers.ModelSerializer):
    fiber_breakdown = serializers.SerializerMethodField()
    dominant_fiber = serializers.SerializerMethodField()
    biodeg_score = serializers.SerializerMethodField()
    biodeg_tier = serializers.SerializerMethodField()

    class Meta:
        model = DonationItem
        fields = ['item_id', 'weight_kg', 'condition_rating', 'fiber_breakdown', 'dominant_fiber', 'biodeg_score', 'biodeg_tier']

    def _parse_fibers(self, obj):
        try:
            if obj.lookup and obj.lookup.fiber_json:
                return json.loads(obj.lookup.fiber_json)
        except (json.JSONDecodeError, AttributeError):
            pass
        return {}

    def get_fiber_breakdown(self, obj): return self._parse_fibers(obj)

    def get_dominant_fiber(self, obj):
        fibers = self._parse_fibers(obj)
        return max(fibers, key=fibers.get) if fibers else None

    def get_biodeg_score(self, obj):
        fibers = self._parse_fibers(obj)
        if fibers and MatchPredictionService._metadata:
            try:
                return round(MatchPredictionService._compute_biodeg_score(fibers), 2)
            except (TypeError, KeyError):
                pass
        return None

    def get_biodeg_tier(self, obj):
        try:
            return _biodeg_tier_from_fibers(self._parse_fibers(obj))
        except (TypeError, KeyError, ValueError):
            return 'MEDIUM'


class MatchRecommendationListSerializer(serializers.ModelSerializer):
    donor = serializers.SerializerMethodField()
    item = DonationItemPreviewSerializer()
    donation = DonationPreviewSerializer(source='item.donation')
    biodeg_tier = serializers.SerializerMethodField()
    distance_km = serializers.DecimalField(max_digits=8, decimal_places=3, allow_null=True, required=False)
    match_confidence = serializers.SerializerMethodField()

    class Meta:
        model = MatchPrediction
        fields = ['pair_id', 'donor', 'item', 'donation', 'match_confidence', 'biodeg_tier', 'distance_km', 'recommendation_status', 'predicted_at']
        read_only_fields = fields

    def get_donor(self, obj):
        donor = obj.item.donation.donor
        name = f"{donor.first_name or ''} {donor.last_name or ''}".strip() or donor.email
        return {'user_id': donor.user_id, 'name': name, 'barangay': obj.item.donation.pickup_barangay, 'city': obj.item.donation.pickup_city}

    def get_biodeg_tier(self, obj):
        try:
            fibers = {}
            if obj.item.lookup and obj.item.lookup.fiber_json:
                fibers = json.loads(obj.item.lookup.fiber_json)
            return _biodeg_tier_from_fibers(fibers)
        except (json.JSONDecodeError, AttributeError, TypeError, KeyError, ValueError):
            return 'MEDIUM'

    def get_match_confidence(self, obj):
        return round(float(obj.match_prob) * 100, 2) if obj.match_prob else 0


class MatchRecommendationDetailSerializer(serializers.ModelSerializer):
    donor = serializers.SerializerMethodField()
    item = DonationItemPreviewSerializer()
    donation = DonationPreviewSerializer(source='item.donation')
    tuab = serializers.SerializerMethodField()
    biodeg_tier = serializers.SerializerMethodField()
    match_confidence = serializers.SerializerMethodField()

    class Meta:
        model = MatchPrediction
        fields = ['pair_id', 'donor', 'item', 'donation', 'tuab', 'match_confidence', 'biodeg_tier', 'distance_km', 'is_match', 'recommendation_status', 'tuab_rejection_reason', 'predicted_at']
        read_only_fields = fields

    def get_donor(self, obj):
        donor = obj.item.donation.donor
        name = f"{donor.first_name or ''} {donor.last_name or ''}".strip() or donor.email
        return {'user_id': donor.user_id, 'name': name, 'email': donor.email, 'barangay': obj.item.donation.pickup_barangay, 'city': obj.item.donation.pickup_city}

    def get_tuab(self, obj):
        name = obj.tuab.business_name or f"{obj.tuab.first_name or ''} {obj.tuab.last_name or ''}".strip()
        return {'user_id': obj.tuab.user_id, 'name': name}

    def get_biodeg_tier(self, obj):
        try:
            fibers = {}
            if obj.item.lookup and obj.item.lookup.fiber_json:
                fibers = json.loads(obj.item.lookup.fiber_json)
            return _biodeg_tier_from_fibers(fibers)
        except (json.JSONDecodeError, AttributeError, TypeError, KeyError, ValueError):
            return 'MEDIUM'

    def get_match_confidence(self, obj):
        return round(float(obj.match_prob) * 100, 2) if obj.match_prob else 0


class MatchRecommendationActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate_reason(self, value):
        if not value or not value.strip():
            return None
        return value.strip()
