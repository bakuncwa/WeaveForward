from django.db import models
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
import json

from ..models import BrandFiberLookup
from ..serializers.brandfiberlookups import BrandFiberLookupSerializer

class BrandFiberLookupViewset(viewsets.ReadOnlyModelViewSet):
    """
    Authenticated access to lookup for clothing material data.
    """
    serializer_class = BrandFiberLookupSerializer
    pagination_class = None  # Disable pagination as requested

    def get_permissions(self):
        if self.action in ['fibers']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

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

    @action(detail=False, methods=['get'])
    def clothing_types(self, request):
        """Returns a unique list of clothing_type values."""
        types = BrandFiberLookup.objects.filter(is_active=True).values_list('clothing_type', flat=True).distinct().order_by('clothing_type')
        return Response(list(types))

    @action(detail=False, methods=['get'])
    def brands(self, request):
        """Returns a unique list of brands, optionally filtered by clothing_type."""
        clothing_type = request.query_params.get('clothing_type')
        queryset = BrandFiberLookup.objects.filter(is_active=True)
        if clothing_type:
            queryset = queryset.filter(clothing_type=clothing_type)
        
        brands = queryset.values_list('brand', flat=True).distinct().order_by('brand')
        return Response(list(brands))

    def get_queryset(self):
        queryset = BrandFiberLookup.objects.filter(is_active=True).order_by('brand', 'clothing_type')
        
        params = self.request.query_params
        
        # General search across multiple fields
        search_query = params.get('q')
        if search_query:
            queryset = queryset.filter(
                models.Q(brand__icontains=search_query) |
                models.Q(clothing_type__icontains=search_query) |
                models.Q(category__icontains=search_query) |
                models.Q(fiber_json__icontains=search_query)
            )

        # Explicit filters
        for field in ['lookup_id', 'category', 'brand', 'clothing_type']:
            val = params.get(field)
            if val:
                if field == 'lookup_id':
                    queryset = queryset.filter(lookup_id=val)
                else:
                    queryset = queryset.filter(**{f"{field}__iexact": val})
        
        return queryset
