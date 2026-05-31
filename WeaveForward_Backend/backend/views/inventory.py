"""
Inventory views for TUAB raw material management.
Provides real-time stock level monitoring.
"""

import json
from django.utils import timezone
from rest_framework import viewsets, mixins, status, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound

from decimal import Decimal, InvalidOperation
from collections import defaultdict
from ..models import InventoryLedger, InventoryLifecycleStatus, InventoryExitState
from ..serializers.inventory import InventoryLedgerSerializer
from ..utils.view_mixins import PaginatedResponseMixin
from ..services.audit_service import get_client_ip, log_audit


class InventoryViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, PaginatedResponseMixin):
    """
    ViewSet for managing TUAB inventory ledger entries.

    Endpoints:
        GET /inventory/ - List all inventory items for authenticated TUAB
    """
    permission_classes = [IsAuthenticated]
    serializer_class = InventoryLedgerSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['=inventory_id', '=source_donation__donation_id', 'source_donation__donor__first_name', 'source_donation__donor__last_name']

    def get_queryset(self):
        user = self.request.user

        if user.role != 'TUAB':
            return InventoryLedger.objects.none()

        return InventoryLedger.objects.filter(
            source_donation__claimed_by_tuab=user,
            lifecycle_status=InventoryLifecycleStatus.ACTIVE
        ).select_related(
            'source_donation',
            'source_donation__donor',
            'source_donation__upload'
        ).prefetch_related(
            'source_donation__items__lookup'
        ).order_by('-ingested_at')

    def list(self, request, *args, **kwargs):
        if request.user.role != 'TUAB':
            raise PermissionDenied("Only TUABs can view inventory.")

        base_qs = self.get_queryset()
        queryset = self.filter_queryset(base_qs)
        response = self.get_paginated_response_data(queryset)
        
        # Calculate summary using optimized .values() query to avoid DRF serialization
        rows = base_qs.values(
            'inventory_id',
            'current_weight_kg',
            'source_donation__items__weight_kg',
            'source_donation__items__lookup__fiber_json'
        )
        
        inv_data = defaultdict(lambda: {'current': 0.0, 'total_orig': 0.0, 'items': []})
        for row in rows:
            i_id = row['inventory_id']
            inv_data[i_id]['current'] = float(row['current_weight_kg'] or 0)
            orig_w = float(row['source_donation__items__weight_kg'] or 0)
            inv_data[i_id]['total_orig'] += orig_w
            
            f_json = row['source_donation__items__lookup__fiber_json'] or ''
            inv_data[i_id]['items'].append((orig_w, f_json))
            
        fiber_weights = defaultdict(float)
        # Time Complexity: O(N * I * F) where:
        # N = number of inventory ledger rows
        # I = number of donation items per inventory entry
        # F = number of fiber components per item
        for data in inv_data.values():
            if data['total_orig'] <= 0: continue
            for w, fiber_str in data['items']:
                item_current_weight = data['current'] * (w / data['total_orig'])
                
                if fiber_str:
                    try:
                        parsed_json = json.loads(fiber_str)
                        if isinstance(parsed_json, dict):
                            for name, pct in parsed_json.items():
                                try:
                                    fiber_weights[str(name).strip().capitalize()] += item_current_weight * (float(pct) / 100.0)
                                except (ValueError, TypeError):
                                    pass
                    except Exception:
                        pass
                            
        category_summary = [
            {'category': f, 'total_weight_kg': round(w, 2)}
            for f, w in sorted(fiber_weights.items(), key=lambda x: x[1], reverse=True)
        ]
        
        if isinstance(response.data, dict):
            response.data['category_summary'] = category_summary
            
        return response

    @action(detail=False, methods=['get'])
    def export(self, request):
        """
        Generate downloadable inventory snapshot with location and metadata.
        Returns CSV/JSON format suitable for external processing.
        """
        if request.user.role != 'TUAB':
            raise PermissionDenied("Only TUABs can export inventory.")
        
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'format': 'json',
            'generated_at': timezone.now().isoformat(),
            'tuab_id': request.user.user_id,
            'tuab_location': {
                'address': request.user.display_address,
                'latitude': request.user.latitude,
                'longitude': request.user.longitude
            },
            'inventory_items': serializer.data
        })

    @action(detail=True, methods=['post'])
    def update_usage(self, request, pk=None):
        """
        Log material consumption: subtracts usage_amount_kg from current_weight_kg.
        Blocks if usage would result in negative stock.
        """
        instance = self.get_object()
        if instance.source_donation.claimed_by_tuab != request.user:
            raise PermissionDenied("Access denied.")
        if instance.lifecycle_status != InventoryLifecycleStatus.ACTIVE:
            return Response({'error': 'Item is not in active inventory.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            usage = Decimal(str(request.data.get('usage_amount_kg', 0)))
        except (InvalidOperation, TypeError):
            return Response({'error': 'Invalid usage amount.'}, status=status.HTTP_400_BAD_REQUEST)

        if usage <= 0:
            return Response({'error': 'Usage amount must be greater than zero.'}, status=status.HTTP_400_BAD_REQUEST)
        if usage > instance.current_weight_kg:
            return Response({'error': 'Negative stock not allowed. Usage exceeds current stock.'}, status=status.HTTP_400_BAD_REQUEST)

        instance.usage_amount_kg += usage
        instance.current_weight_kg -= usage
        instance.notes = request.data.get('notes') or instance.notes
        instance.save()

        # Log audit trail
        log_audit(
            actor=request.user,
            entity_type='inventory_ledger',
            action='CONSUMPTION_LOG',
            ip_address=get_client_ip(request),
            fields_modified=['usage_amount_kg', 'current_weight_kg', 'notes']
        )

        low_stock = instance.current_weight_kg < instance.low_stock_threshold
        serializer = self.get_serializer(instance)
        return Response({**serializer.data, 'low_stock_alert': low_stock}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """
        Archive an inventory item with an exit state (UPCYCLED, SHREDDED, LANDFILL).
        If item still has stock, requires force confirmation (was_forced_archived=True).
        """
        instance = self.get_object()
        if instance.source_donation.claimed_by_tuab != request.user:
            raise PermissionDenied("Access denied.")
        if instance.lifecycle_status == InventoryLifecycleStatus.ARCHIVED:
            return Response({'error': 'Item is already archived.'}, status=status.HTTP_400_BAD_REQUEST)

        exit_state_raw = (request.data.get('exit_state') or '').upper()
        valid_exit_states = [c[0] for c in InventoryExitState.choices]
        if exit_state_raw not in valid_exit_states:
            return Response({'error': f'Invalid exit state. Choose from: {", ".join(valid_exit_states)}'}, status=status.HTTP_400_BAD_REQUEST)

        instance.lifecycle_status = InventoryLifecycleStatus.ARCHIVED
        instance.exit_state = exit_state_raw
        instance.archived_at = timezone.now()
        instance.was_forced_archived = instance.current_weight_kg > 0
        instance.save()

        # Log audit trail
        log_audit(
            actor=request.user,
            entity_type='inventory_ledger',
            action='STATUS_CHANGE',
            ip_address=get_client_ip(request),
            fields_modified=['lifecycle_status', 'exit_state', 'archived_at', 'was_forced_archived']
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """
        Restore a recently archived inventory item (undo within grace period).
        """
        try:
            instance = InventoryLedger.objects.select_related('source_donation').get(pk=pk)
        except InventoryLedger.DoesNotExist:
            raise NotFound("Inventory item not found.")

        if instance.source_donation.claimed_by_tuab != request.user:
            raise PermissionDenied("Access denied.")
        if instance.lifecycle_status != InventoryLifecycleStatus.ARCHIVED:
            return Response({'error': 'Item is not archived.'}, status=status.HTTP_400_BAD_REQUEST)

        # Allow restore only within 30 seconds of archiving
        if instance.archived_at and (timezone.now() - instance.archived_at).total_seconds() > 30:
            return Response({'error': 'Undo window has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        instance.lifecycle_status = InventoryLifecycleStatus.ACTIVE
        instance.exit_state = None
        instance.archived_at = None
        instance.was_forced_archived = False
        instance.save()

        # Log audit trail
        log_audit(
            actor=request.user,
            entity_type='inventory_ledger',
            action='STATUS_CHANGE',
            ip_address=get_client_ip(request),
            fields_modified=['lifecycle_status', 'exit_state', 'archived_at', 'was_forced_archived']
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)
