from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
import json

from ..models import BrandFiberLookup
from ..serializers.brandfiberlookups import BrandFiberLookupSerializer

class BrandFiberLookupViewset(viewsets.ReadOnlyModelViewSet):
    """
    Authenticated access to lookup for clothing material data.
    """
    serializer_class = BrandFiberLookupSerializer
    pagination_class = None
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['lookup_id', 'category', 'brand', 'clothing_type']

    def get_permissions(self):
        if self.action in ['fibers']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=['get'])
    def fibers(self, request):
        """Returns a unique list of fiber types found in the fiber_json column."""
        # Complexity notes:
        # - Let n = number of active BrandFiberLookup rows scanned.
        # - Let m = average size/number of fiber entries in each fiber_json value.
        # - Let f = number of unique fiber names found.
        # - Parsing and collecting fibers is O(n * m).
        # - Sorting the unique fiber list is O(f log f).
        # - Overall: O(n * m + f log f).
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

    @action(detail=False, methods=['get'])
    def clothing_types(self, request):
        """Returns a unique list of clothing_type values."""
        # Complexity notes:
        # - Let n = number of active rows considered by the queryset.
        # - Filtering/distinct work is linear in the rows considered.
        # - Database ordering is handled by the DB engine.
        # - Simplified: O(n)
        types = BrandFiberLookup.objects.filter(is_active=True).values_list('clothing_type', flat=True).distinct().order_by('clothing_type')
        return Response(list(types))

    @action(detail=False, methods=['get'])
    def brands(self, request):
        """Returns a unique list of brands, optionally filtered by clothing_type."""
        # Complexity notes:
        # - Let n = number of active rows considered by the queryset.
        # - Filtering/distinct work is linear in the rows considered.
        # - Database ordering is handled by the DB engine.
        # - Simplified: O(n)
        clothing_type = request.query_params.get('clothing_type')
        queryset = BrandFiberLookup.objects.filter(is_active=True)
        if clothing_type:
            queryset = queryset.filter(clothing_type=clothing_type)
        
        brands = queryset.values_list('brand', flat=True).distinct().order_by('brand')
        return Response(list(brands))

    def get_queryset(self):
        # Complexity: O(n log n), where n is the number of active rows,
        # because order_by sorts by brand, then clothing_type.
        return BrandFiberLookup.objects.filter(is_active=True).order_by('brand', 'clothing_type')

