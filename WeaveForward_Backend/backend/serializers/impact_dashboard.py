from rest_framework import serializers


class TopDonorSerializer(serializers.Serializer):
    full_name = serializers.CharField(allow_null=True)
    donation_count = serializers.IntegerField()


class BarangayBreakdownSerializer(serializers.Serializer):
    barangay = serializers.CharField()
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, allow_null=True)
    donation_count = serializers.IntegerField()


class ImpactDashboardSerializer(serializers.Serializer):
    donations = serializers.IntegerField()
    donors = serializers.IntegerField()
    top_donors = TopDonorSerializer(many=True)
    barangay_breakdown = BarangayBreakdownSerializer(many=True)
