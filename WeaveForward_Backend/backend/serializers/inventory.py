"""
Serializers for Inventory management.
Handles InventoryLedger serialization for viewing and managing raw material stock levels.
"""

from rest_framework import serializers
from ..models import InventoryLedger, Donation, DonationItem
from .brandfiberlookups import BrandFiberLookupSerializer


class InventoryItemDetailsSerializer(serializers.ModelSerializer):
    """Serializer for donation items within an inventory ledger entry."""
    lookup_details = BrandFiberLookupSerializer(source='lookup', read_only=True)
    clothing_type = serializers.SerializerMethodField()

    class Meta:
        model = DonationItem
        fields = [
            'item_id',
            'clothing_type',
            'condition_rating',
            'weight_kg',
            'lookup_details'
        ]

    def get_clothing_type(self, obj):
        return obj.lookup.clothing_type if obj.lookup else None


class InventoryDonorSerializer(serializers.ModelSerializer):
    """Serializer for donor information in inventory context."""
    
    class Meta:
        model = DonationItem.objects.model.__class__.__bases__[0]
        fields = ['user_id', 'first_name', 'last_name']


class InventorySourceDonationSerializer(serializers.ModelSerializer):
    """Serializer for source donation information in inventory ledger."""
    donor = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    
    class Meta:
        model = Donation
        fields = [
            'donation_id',
            'status',
            'donor',
            'preferred_pickup_date',
            'pickup_display_address',
            'pickup_latitude',
            'pickup_longitude',
            'items'
        ]
    
    def get_donor(self, obj):
        """Get donor information from the donation."""
        if obj.donor:
            return {
                'user_id': obj.donor.user_id,
                'first_name': obj.donor.first_name,
                'last_name': obj.donor.last_name
            }
        return None
    
    def get_items(self, obj):
        """Get items from the source donation."""
        items = obj.items.all()
        return InventoryItemDetailsSerializer(items, many=True).data


class InventoryLedgerSerializer(serializers.ModelSerializer):
    """Main serializer for inventory ledger entries with audit information."""
    source_donation = InventorySourceDonationSerializer(read_only=True)
    audit_required = serializers.SerializerMethodField()
    days_since_audit = serializers.SerializerMethodField()
    material_category = serializers.SerializerMethodField()
    
    class Meta:
        model = InventoryLedger
        fields = [
            'inventory_id',
            'source_donation',
            'usage_amount_kg',
            'weight_before_kg',
            'current_weight_kg',
            'lifecycle_status',
            'exit_state',
            'is_upcyclable',
            'low_stock_threshold',
            'was_forced_archived',
            'ingested_at',
            'updated_at',
            'archived_at',
            'audit_required',
            'days_since_audit',
            'material_category',
            'notes'
        ]
    
    def get_audit_required(self, obj):
        """Check if audit is required (items older than 30 days)."""
        from datetime import timedelta
        from django.utils import timezone
        
        thirty_days_ago = timezone.now() - timedelta(days=30)
        return obj.updated_at < thirty_days_ago
    
    def get_days_since_audit(self, obj):
        """Calculate days since last audit/update."""
        from django.utils import timezone
        
        days_diff = (timezone.now() - obj.updated_at).days
        return days_diff
    
    def get_material_category(self, obj):
        """Get the primary material category from source donation items."""
        items = obj.source_donation.items.all()
        if items.exists():
            first_item = items.first()
            if first_item.lookup:
                return first_item.lookup.category
        return None


class InventoryAuditHistorySerializer(serializers.ModelSerializer):
    """Serializer for inventory audit timeline."""
    
    class Meta:
        model = InventoryLedger
        fields = [
            'inventory_id',
            'ingested_at',
            'updated_at',
            'archived_at',
            'current_weight_kg',
            'usage_amount_kg',
            'lifecycle_status',
            'notes'
        ]


class InventorySnapshotSummarySerializer(serializers.Serializer):
    """Serializer for inventory snapshot summary with category aggregations."""
    total_items = serializers.IntegerField()
    total_weight_kg = serializers.DecimalField(max_digits=10, decimal_places=3)
    audit_required_count = serializers.IntegerField()
    category_summary = serializers.ListField()
    
    class Meta:
        fields = [
            'total_items',
            'total_weight_kg',
            'audit_required_count',
            'category_summary'
        ]
