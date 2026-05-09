from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
import json

from ..models import BrandFiberLookup
from ..serializers.brandfiberlookups import BrandFiberLookupSerializer

class BrandFiberLookupViewset(viewsets.ReadOnlyModelViewSet):
    """
    Publicly accessible, read-only lookup for clothing material data.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = BrandFiberLookupSerializer
    pagination_class = None  # Disable pagination as requested

    @action(detail=False, methods=['get'])
    def fibers(self, request):
        """Returns a unique list of fiber types found in the fiber_json column."""
        fibers_set = set()
        # Fetching only the fiber_json column for efficiency
        raw_jsons = BrandFiberLookup.objects.filter(is_active=True).values_list('fiber_json', flat=True)
        
        for fj in raw_jsons:
            try:
                data = json.loads(fj)
                if isinstance(data, dict):
                    fibers_set.update(data.keys())
            except (json.JSONDecodeError, TypeError):
                continue
                
        return Response(sorted(list(fibers_set)))

    def get_queryset(self):
        queryset = BrandFiberLookup.objects.filter(is_active=True).order_by('brand', 'clothing_type')
        
        # Allow query parameters for fields in the serializer
        params = self.request.query_params
        for field in ['lookup_id', 'category', 'brand', 'clothing_type', 'fiber_json']:
            val = params.get(field)
            if val:
                if field == 'lookup_id':
                    queryset = queryset.filter(lookup_id=val)
                else:
                    queryset = queryset.filter(**{f"{field}__icontains": val})
        
        return queryset
