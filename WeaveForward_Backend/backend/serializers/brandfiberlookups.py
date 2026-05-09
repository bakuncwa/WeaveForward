import json
from rest_framework import serializers
from ..models import BrandFiberLookup

class BrandFiberLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandFiberLookup
        fields = ['lookup_id', 'category', 'brand', 'clothing_type', 'fiber_json']
