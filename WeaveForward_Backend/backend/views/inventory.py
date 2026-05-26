"""
Inventory views for TUAB raw material management.
Provides real-time stock level monitoring and audit history tracking.
"""

from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Q, Count, DecimalField
from django.db.models.functions import TruncDate
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound

from decimal import Decimal, InvalidOperation
from ..models import InventoryLedger, InventoryLifecycleStatus, InventoryExitState
from ..serializers.inventory import (
    InventoryLedgerSerializer,
    InventoryAuditHistorySerializer,
    InventorySnapshotSummarySerializer
)
from ..utils.view_mixins import PaginatedResponseMixin


class InventoryViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, PaginatedResponseMixin):
    """
    ViewSet for managing TUAB inventory ledger entries.
    
    Endpoints:
        GET /inventory/ - List all inventory items for authenticated TUAB
        GET /inventory/{inventory_id}/ - Get specific inventory item details
        GET /inventory/snapshot/summary/ - Get inventory aggregation summary
        GET /inventory/{inventory_id}/audit-history/ - Get audit timeline for item
    """
    permission_classes = [IsAuthenticated]
    serializer_class = InventoryLedgerSerializer

    def get_queryset(self):
        """
        Get inventory ledger entries.
        Only TUABs can access inventory for their own donations.
        """
        user = self.request.user
        
        # Only TUABs can access inventory
        if user.role != 'TUAB':
            return InventoryLedger.objects.none()
        
        # Get inventory from donations claimed by this TUAB
        queryset = InventoryLedger.objects.filter(
            source_donation__claimed_by_tuab=user,
            lifecycle_status=InventoryLifecycleStatus.ACTIVE
        ).select_related(
            'source_donation',
            'source_donation__donor',
            'source_donation__upload'
        ).prefetch_related(
            'source_donation__items__lookup'
        ).order_by('-ingested_at')
        
        return queryset

    def list(self, request, *args, **kwargs):
        """
        List inventory items with pagination.
        Includes basic item information and audit status flags.
        """
        if request.user.role != 'TUAB':
            raise PermissionDenied("Only TUABs can view inventory.")
        
        queryset = self.get_queryset()
        return self.get_paginated_response_data(queryset)

    def retrieve(self, request, *args, **kwargs):
        """
        Get detailed information about a specific inventory item.
        Includes source donation details, current stock levels, and audit history.
        """
        instance = self.get_object()
        
        # Verify ownership
        if instance.source_donation.claimed_by_tuab != request.user:
            raise PermissionDenied("Access denied.")
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def snapshot(self, request):
        """
        Get inventory snapshot summary with:
        - Total items count
        - Total weight aggregation
        - Items requiring audit (>30 days old)
        - Category-wise breakdown
        """
        if request.user.role != 'TUAB':
            raise PermissionDenied("Only TUABs can view inventory snapshots.")
        
        queryset = self.get_queryset()
        
        # Calculate aggregates
        totals = queryset.aggregate(
            total_items=Count('inventory_id'),
            total_weight_kg=Sum('current_weight_kg', output_field=DecimalField()),
        )
        
        # Count items requiring audit (>30 days since last update)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        audit_required_count = queryset.filter(updated_at__lt=thirty_days_ago).count()
        
        # Aggregate by category
        category_summary = []
        category_data = queryset.values('source_donation__items__lookup__category').annotate(
            category_count=Count('inventory_id'),
            category_weight=Sum('current_weight_kg', output_field=DecimalField())
        )
        
        for cat in category_data:
            if cat.get('source_donation__items__lookup__category'):
                category_summary.append({
                    'category': cat['source_donation__items__lookup__category'],
                    'items_count': cat['category_count'],
                    'total_weight_kg': cat['category_weight']
                })
        
        # Build response
        summary_data = {
            'total_items': totals['total_items'] or 0,
            'total_weight_kg': totals['total_weight_kg'] or 0,
            'audit_required_count': audit_required_count,
            'category_summary': category_summary
        }
        
        serializer = InventorySnapshotSummarySerializer(summary_data)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def audit_history(self, request, pk=None):
        """
        Get audit timeline for a specific inventory item.
        Shows all updates, usage tracking, and status changes.
        """
        instance = self.get_object()
        
        # Verify ownership
        if instance.source_donation.claimed_by_tuab != request.user:
            raise PermissionDenied("Access denied.")
        
        # For now, return current state (audit trail DB table can be added in future)
        serializer = InventoryAuditHistorySerializer(instance)
        return Response({
            'inventory_id': instance.inventory_id,
            'current_state': serializer.data,
            'audit_entries': [
                {
                    'timestamp': instance.ingested_at,
                    'action': 'CREATED',
                    'weight_kg': instance.weight_before_kg,
                    'notes': 'Initial ingestion from donation'
                },
                {
                    'timestamp': instance.updated_at,
                    'action': 'UPDATED',
                    'weight_kg': instance.current_weight_kg,
                    'notes': instance.notes or 'Stock update'
                }
            ]
        })

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

    @action(detail=True, methods=['patch'])
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

        low_stock = instance.current_weight_kg < instance.low_stock_threshold
        serializer = self.get_serializer(instance)
        return Response({**serializer.data, 'low_stock_alert': low_stock}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'])
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

        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'])
    def restore(self, request, pk=None):
        """
        Restore a recently archived inventory item (undo within grace period).
        """
        instance = self.get_object()
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

        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)
