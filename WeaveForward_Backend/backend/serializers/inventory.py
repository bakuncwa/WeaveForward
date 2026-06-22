"""
Serializers for Inventory management.
Handles InventoryLedger serialization for viewing and managing raw material stock levels.
"""

import json
from rest_framework import serializers
from django.utils import timezone
from django.utils.dateparse import parse_datetime
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
    notes = serializers.SerializerMethodField()
    
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

    def get_notes(self, obj):
        raw_notes = obj.notes
        if not raw_notes:
            return raw_notes
        try:
            notes_payload = json.loads(raw_notes)
        except (TypeError, json.JSONDecodeError):
            return raw_notes
        if not isinstance(notes_payload, dict):
            return raw_notes

        usage_events = notes_payload.get('production_context')
        if not isinstance(usage_events, list):
            return raw_notes

        for event in usage_events:
            if not isinstance(event, dict) or not event.get('at'):
                continue
            dt = parse_datetime(str(event['at']))
            if not dt:
                continue
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_default_timezone())
            event['at'] = timezone.localtime(dt).isoformat()

        return json.dumps(notes_payload, separators=(',', ':'))
    
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
        for item in obj.source_donation.items.all():
            if item.lookup:
                return item.lookup.product_name
        return None
