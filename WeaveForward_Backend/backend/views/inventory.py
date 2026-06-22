"""
Inventory views for TUAB raw material management.
Provides real-time stock level monitoring.
"""

import json
from django.utils import timezone
from rest_framework import viewsets, mixins, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound

from decimal import Decimal, InvalidOperation
from collections import defaultdict
from ..models import InventoryLedger, InventoryLifecycleStatus, InventoryExitState
from ..permissions import IsActiveTUAB
from ..serializers.inventory import InventoryLedgerSerializer
from ..utils.view_mixins import PaginatedResponseMixin
from ..services.audit_service import get_client_ip, log_audit


class InventoryViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, PaginatedResponseMixin):
    """
    ViewSet for managing TUAB inventory ledger entries.

    Endpoints:
        GET /inventory/ - List all inventory items for authenticated TUAB
    """
    permission_classes = [IsActiveTUAB]
    serializer_class = InventoryLedgerSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['=inventory_id', '=source_donation__donation_id', 'source_donation__donor__first_name', 'source_donation__donor__last_name']

    def get_queryset(self):
        user = self.request.user

        queryset = InventoryLedger.objects.filter(
            source_donation__claimed_by_tuab=user
        )
        if self.request.query_params.get('status') != 'all':
            queryset = queryset.filter(lifecycle_status=InventoryLifecycleStatus.ACTIVE)

        return queryset.select_related(
            'source_donation',
            'source_donation__donor',
            'source_donation__upload'
        ).prefetch_related(
            'source_donation__items__lookup'
        ).order_by('-ingested_at')

    # Overall time complexity:
    # O((n log n) + (p * k) + (n * k) + (n * k * f) + c)
    # Simplified: O((n log n) + (n * k * f))
    # n = matching inventory ledger rows, p = page size,
    # k = average donation items per inventory entry,
    # f = average fiber components per item,
    # c = unique fiber categories.
    def list(self, request, *args, **kwargs):
        # Big-O variables:
        # n = matching inventory ledger rows
        # p = paginated inventory rows returned in this response
        # k = average donation items per inventory entry
        # f = average fiber components per donation item
        # c = unique fiber categories in the summary

        # O(n log n) if the database must sort for order_by('-ingested_at');
        # closer to O(n) if a useful index satisfies the ordering.
        base_qs = self.get_queryset()
        queryset = self.filter_queryset(base_qs)

        # O(p * k): serializes the current page, including each source donation's items.
        response = self.get_paginated_response_data(queryset)
        
        # Calculate summary using optimized .values() query to avoid DRF serialization
        # O(n * k): produces one joined row per inventory entry and donation item.
        rows = base_qs.values(
            'inventory_id',
            'current_weight_kg',
            'source_donation__items__weight_kg',
            'source_donation__items__lookup__fiber_json'
        )
        
        # O(n * k): groups joined item rows by inventory_id and totals original item weights.
        inv_data = {}
        for row in rows:
            inventory_id = row['inventory_id']
            current_inventory_weight = float(row['current_weight_kg'])
            item_original_weight = float(row['source_donation__items__weight_kg'])
            item_fiber_json = row['source_donation__items__lookup__fiber_json']

            if inventory_id not in inv_data:
                inv_data[inventory_id] = {
                    'current': 0.0,
                    'total_orig': 0.0,
                    'items': [],
                }

            inventory_data = inv_data[inventory_id]
            inventory_data['current'] = current_inventory_weight
            inventory_data['total_orig'] += item_original_weight
            
            inventory_data['items'].append((item_original_weight, item_fiber_json))
            
        fiber_weights = defaultdict(float)
        # O(n * k * f): visits every inventory entry, each item, and each fiber component.
        for inventory_entry in inv_data.values():
            current_inventory_weight = inventory_entry['current']
            original_total_weight = inventory_entry['total_orig']

            for item_original_weight, item_fiber_json in inventory_entry['items']:
                item_share = item_original_weight / original_total_weight
                item_current_weight = current_inventory_weight * item_share

                item_fibers = json.loads(item_fiber_json)

                for fiber_name, fiber_percent in item_fibers.items():
                    fiber_weight = item_current_weight * (float(fiber_percent) / 100.0)
                    fiber_weights[fiber_name] += fiber_weight
                            
        # O(c): converts the category totals dictionary into response objects.
        category_summary = []
        for fiber_name, total_weight in fiber_weights.items():
            category_summary.append({
                'category': fiber_name,
                'total_weight_kg': round(total_weight, 2),
            })
        
        if isinstance(response.data, dict):
            response.data['category_summary'] = category_summary
            
        return response

    @action(detail=False, methods=['get'])
    def export(self, request):
        """
        Generate downloadable inventory snapshot with location and metadata.
        Returns CSV/JSON format suitable for external processing.
        """
        queryset = InventoryLedger.objects.filter(
            source_donation__claimed_by_tuab=request.user,
        ).select_related(
            'source_donation',
            'source_donation__donor',
            'source_donation__upload'
        ).prefetch_related(
            'source_donation__items__lookup'
        ).order_by('-updated_at')
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

        raw_usage = request.data.get('usage_amount_kg', 0)
        try:
            usage = Decimal(str(raw_usage)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            return Response({'error': 'Please enter a valid number for usage amount.'}, status=status.HTTP_400_BAD_REQUEST)

        if usage <= 0:
            return Response({'error': 'Usage amount must be greater than zero and at most 2 decimal places.'}, status=status.HTTP_400_BAD_REQUEST)
        if usage > instance.current_weight_kg:
            return Response({'error': 'Negative stock not allowed. Usage exceeds current stock.'}, status=status.HTTP_400_BAD_REQUEST)

        before_weight = instance.current_weight_kg
        after_weight = (before_weight - usage).quantize(Decimal('0.01'))

        raw_notes = instance.notes
        try:
            notes_payload = json.loads(raw_notes) if raw_notes else {}
            if not isinstance(notes_payload, dict):
                notes_payload = {'text': raw_notes}
        except (TypeError, json.JSONDecodeError):
            notes_payload = {'text': raw_notes}

        if request.data.get('notes'):
            notes_payload['text'] = request.data.get('notes')

        usage_events = notes_payload.get('production_context')
        if not isinstance(usage_events, list):
            usage_events = []
        usage_events.append({
            'used': str(usage),
            'before': str(before_weight),
            'after': str(after_weight),
            'at': timezone.localtime(timezone.now()).isoformat(),
        })
        notes_payload['production_context'] = usage_events

        instance.usage_amount_kg = (instance.usage_amount_kg + usage).quantize(Decimal('0.01'))
        instance.current_weight_kg = after_weight
        instance.notes = json.dumps(notes_payload, separators=(',', ':'))
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
            return Response({'error': 'Exit state must be Upcycled, Shredded, or Landfill.'}, status=status.HTTP_400_BAD_REQUEST)

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

        # Allow restore only within 10 seconds of archiving.
        if instance.archived_at and (timezone.now() - instance.archived_at).total_seconds() > 10:
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
