from datetime import timedelta
from django.utils import timezone
from rest_framework import viewsets, permissions
from rest_framework.response import Response
from django.db.models import Sum

from ..models import InventoryLedger, InventoryLifecycleStatus, DonationItem


class InventoryViewSet(viewsets.ViewSet):
    """Simple read-only viewset providing inventory snapshot data."""

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def list(self, request):
        # Active inventory ledgers
        ledgers_qs = InventoryLedger.objects.filter(lifecycle_status=InventoryLifecycleStatus.ACTIVE).select_related('source_donation')

        now = timezone.now()
        ledgers = []
        total_weight = 0
        for l in ledgers_qs.order_by('-ingested_at'):
            days_since = (now - (l.updated_at or l.ingested_at)).days
            audit_required = days_since > 30
            donation = l.source_donation
            ledgers.append({
                'inventory_id': l.inventory_id,
                'source_donation_id': donation.donation_id if donation else None,
                'pickup_address': donation.pickup_display_address if donation else None,
                'current_weight_kg': float(l.current_weight_kg),
                'weight_before_kg': float(l.weight_before_kg),
                'ingested_at': l.ingested_at,
                'updated_at': l.updated_at,
                'audit_required': audit_required,
            })
            total_weight += float(l.current_weight_kg or 0)

        # Aggregate by material category (joins DonationItem -> BrandFiberLookup)
        category_qs = (
            DonationItem.objects
            .filter(donation__inventory_ledger_entries__lifecycle_status=InventoryLifecycleStatus.ACTIVE)
            .values('lookup__category')
            .annotate(total_weight_kg=Sum('weight_kg'))
            .order_by('-total_weight_kg')
        )

        category_summary = [
            {'category': c.get('lookup__category') or 'Unknown', 'total_weight_kg': float(c.get('total_weight_kg') or 0)}
            for c in category_qs
        ]

        return Response({
            'total_weight_kg': total_weight,
            'ledgers': ledgers,
            'category_summary': category_summary,
        })
