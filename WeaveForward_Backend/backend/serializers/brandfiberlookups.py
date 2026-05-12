import json
from rest_framework import serializers
from ..models import BrandFiberLookup

class BrandFiberLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandFiberLookup
        fields = '__all__'

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Format clothing_type
        if ret.get('clothing_type'):
            ret['clothing_type'] = ret['clothing_type'].capitalize()
        # Format fiber_json
        f_data = ret.get('fiber_json')
        if f_data and f_data.startswith('{'):
            try:
                f_obj = json.loads(f_data)
                if isinstance(f_obj, dict):
                    ret['fiber_json'] = ", ".join([f"{v}% {k.capitalize()}" for k, v in f_obj.items()])
            except:
                pass
        return ret
