import json
from rest_framework import serializers
from ..models import MatchPrediction, Donation, DonationItem, User, BrandFiberLookup


class DonorPreviewSerializer(serializers.ModelSerializer):
    """Minimal donor info for list view"""
    class Meta:
        model = User
        fields = ['user_id', 'name', 'pickup_barangay']


class DonationPreviewSerializer(serializers.ModelSerializer):
    """Minimal donation info with location"""
    pickup_barangay = serializers.SerializerMethodField()
    pickup_city = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    pickup_window = serializers.SerializerMethodField()
    
    class Meta:
        model = Donation
        fields = [
            'donation_id',
            'pickup_barangay',
            'pickup_city',
            'location',
            'pickup_window',
            'preferred_pickup_date',
        ]
    
    def get_pickup_barangay(self, obj):
        return obj.pickup_barangay
    
    def get_pickup_city(self, obj):
        return obj.pickup_city
    
    def get_location(self, obj):
        return {
            'latitude': float(obj.pickup_latitude),
            'longitude': float(obj.pickup_longitude),
        }
    
    def get_pickup_window(self, obj):
        if obj.preferred_pickup_window_start and obj.preferred_pickup_window_end:
            return {
                'start': obj.preferred_pickup_window_start.isoformat(),
                'end': obj.preferred_pickup_window_end.isoformat(),
            }
        return None


class DonationItemPreviewSerializer(serializers.ModelSerializer):
    """Item details including fiber composition"""
    fiber_breakdown = serializers.SerializerMethodField()
    dominant_fiber = serializers.SerializerMethodField()
    
    class Meta:
        model = DonationItem
        fields = [
            'item_id',
            'weight_kg',
            'condition_rating',
            'fiber_breakdown',
            'dominant_fiber',
        ]
    
    def get_fiber_breakdown(self, obj):
        try:
            if obj.lookup and obj.lookup.fiber_json:
                return json.loads(obj.lookup.fiber_json)
        except (json.JSONDecodeError, AttributeError):
            pass
        return {}
    
    def get_dominant_fiber(self, obj):
        try:
            if obj.lookup and obj.lookup.fiber_json:
                fibers = json.loads(obj.lookup.fiber_json)
                if fibers:
                    return max(fibers, key=fibers.get)
        except (json.JSONDecodeError, AttributeError, ValueError):
            pass
        return None


class MatchRecommendationListSerializer(serializers.ModelSerializer):
    """Optimized list view serializer for recommendations"""
    donor = serializers.SerializerMethodField()
    item = DonationItemPreviewSerializer()
    donation = DonationPreviewSerializer()
    biodeg_tier = serializers.SerializerMethodField()
    distance_km = serializers.DecimalField(
        max_digits=8,
        decimal_places=3,
        allow_null=True,
        required=False
    )
    match_confidence = serializers.SerializerMethodField()
    
    class Meta:
        model = MatchPrediction
        fields = [
            'pair_id',
            'donor',
            'item',
            'donation',
            'match_confidence',
            'biodeg_tier',
            'distance_km',
            'recommendation_status',
            'predicted_at',
        ]
        read_only_fields = fields
    
    def get_donor(self, obj):
        donor = obj.item.donation.donor
        return {
            'user_id': donor.user_id,
            'name': donor.name,
            'barangay': obj.item.donation.pickup_barangay,
            'city': obj.item.donation.pickup_city,
        }
    
    def get_biodeg_tier(self, obj):
        # Compute biodegradability tier from fiber composition
        try:
            if obj.item.lookup and obj.item.lookup.fiber_json:
                fibers = json.loads(obj.item.lookup.fiber_json)
                # Simple tier calculation: check dominant fiber
                dominant = max(fibers, key=fibers.get) if fibers else 'unknown'
                
                # Biodegradable fibers
                bio_fibers = {
                    'cotton', 'linen', 'hemp', 'wool', 'silk',
                    'bamboo', 'tencel', 'lyocell', 'modal',
                    'cashmere', 'viscose', 'rayon', 'denim', 'alpaca'
                }
                
                if dominant.lower() in bio_fibers:
                    pct = fibers.get(dominant, 0)
                    if pct >= 80:
                        return 'HIGH'
                    elif pct >= 50:
                        return 'MEDIUM'
                    else:
                        return 'LOW'
                return 'LOW'
        except (json.JSONDecodeError, AttributeError, ValueError):
            pass
        return 'MEDIUM'
    
    def get_match_confidence(self, obj):
        """Return match probability as percentage"""
        return round(float(obj.match_prob) * 100, 2) if obj.match_prob else 0


class MatchRecommendationDetailSerializer(serializers.ModelSerializer):
    """Full detail view serializer"""
    donor = serializers.SerializerMethodField()
    item = DonationItemPreviewSerializer()
    donation = DonationPreviewSerializer()
    tuab = serializers.SerializerMethodField()
    biodeg_tier = serializers.SerializerMethodField()
    match_confidence = serializers.SerializerMethodField()
    
    class Meta:
        model = MatchPrediction
        fields = [
            'pair_id',
            'donor',
            'item',
            'donation',
            'tuab',
            'match_confidence',
            'biodeg_tier',
            'distance_km',
            'is_match',
            'recommendation_status',
            'tuab_rejection_reason',
            'predicted_at',
        ]
        read_only_fields = fields
    
    def get_donor(self, obj):
        donor = obj.item.donation.donor
        return {
            'user_id': donor.user_id,
            'name': donor.name,
            'email': donor.email,
            'barangay': obj.item.donation.pickup_barangay,
            'city': obj.item.donation.pickup_city,
        }
    
    def get_tuab(self, obj):
        return {
            'user_id': obj.tuab.user_id,
            'name': obj.tuab.name,
        }
    
    def get_biodeg_tier(self, obj):
        # Same logic as in list serializer
        try:
            if obj.item.lookup and obj.item.lookup.fiber_json:
                fibers = json.loads(obj.item.lookup.fiber_json)
                dominant = max(fibers, key=fibers.get) if fibers else 'unknown'
                
                bio_fibers = {
                    'cotton', 'linen', 'hemp', 'wool', 'silk',
                    'bamboo', 'tencel', 'lyocell', 'modal',
                    'cashmere', 'viscose', 'rayon', 'denim', 'alpaca'
                }
                
                if dominant.lower() in bio_fibers:
                    pct = fibers.get(dominant, 0)
                    if pct >= 80:
                        return 'HIGH'
                    elif pct >= 50:
                        return 'MEDIUM'
                    else:
                        return 'LOW'
                return 'LOW'
        except (json.JSONDecodeError, AttributeError, ValueError):
            pass
        return 'MEDIUM'
    
    def get_match_confidence(self, obj):
        return round(float(obj.match_prob) * 100, 2) if obj.match_prob else 0


class MatchRecommendationActionSerializer(serializers.Serializer):
    """Serializer for accept/reject actions"""
    reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Rejection reason (required for reject action)"
    )
    
    def validate_reason(self, value):
        if not value or not value.strip():
            return None
        return value.strip()
