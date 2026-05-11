from rest_framework import serializers

from ..models import BrandFiberLookup, Donation, DonationItem, User
from ..services.upload_service import build_upload_url


class BrandFiberLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandFiberLookup
        fields = '__all__'


class DonationItemSerializer(serializers.ModelSerializer):
    lookup_details = BrandFiberLookupSerializer(source='lookup', read_only=True)

    class Meta:
        model = DonationItem
        fields = ['item_id', 'condition_rating', 'weight_kg', 'lookup_details']


class DonationUserSerializer(serializers.ModelSerializer):
    """Minimal user data for nesting in donations."""
    upload = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['user_id', 'email', 'role', 'first_name', 'last_name', 'business_name', 'contact_no', 'upload']

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)


class DonationSerializer(serializers.ModelSerializer):
    donor = DonationUserSerializer(read_only=True)
    claimed_by_tuab = DonationUserSerializer(read_only=True)
    items = DonationItemSerializer(many=True, read_only=True)
    upload = serializers.SerializerMethodField()
    pickup_latitude = serializers.DecimalField(max_digits=18, decimal_places=15, read_only=True)
    pickup_longitude = serializers.DecimalField(max_digits=18, decimal_places=15, read_only=True)

    class Meta:
        model = Donation
        fields = '__all__'

    def get_upload(self, obj):
        return build_upload_url(obj.upload, self.context)
