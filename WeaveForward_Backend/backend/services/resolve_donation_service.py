from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, APIException, NotFound

from ..models import (
    Donation, DonationStatus, DonationItem, DonationDeliveryMethod, Order, OrderStatus, InventoryLedger
)
from .audit_service import log_audit


def resolve_donation(*, user, donation, validated_data, ip_address=None):
    # Execute inside a single atomic transaction
    with transaction.atomic():
        # Retrieve donation with database pessimistic locking
        donation = Donation.objects.select_for_update().get(pk=donation.pk)

        # Validate delivery method conditions
        if donation.delivery_method == DonationDeliveryMethod.PICKUP:
            if donation.status != DonationStatus.IN_TRANSIT:
                exc = APIException("A pick-up donation must be in-transit to be resolved.")
                exc.status_code = 409
                raise exc
        else:
            if donation.status != DonationStatus.IN_TRANSIT or not donation.orders.filter(status=OrderStatus.COMPLETED).exists():
                exc = APIException("A delivery donation must be in-transit and its associated order must be completed to be resolved.")
                exc.status_code = 409
                raise exc

        # Perform the resolution update
        if validated_data['status'] == DonationStatus.REJECTED:
            donation.status = DonationStatus.REJECTED
            donation.rejection_reason = validated_data.get('rejection_reason')
        else:
            donation.status = DonationStatus.RECEIVED
            donation.rejection_reason = None
            
        donation.updated_at = timezone.now()
        donation.save(update_fields=["status", "rejection_reason", "updated_at"])

        # Handle items updates (copied from donation_service.py)
        items_data = validated_data.get('items')
        if items_data is not None:
            # Lock all existing items for this donation at once to prevent deadlocks and reduce DB queries
            existing_items = {item.pk: item for item in donation.items.select_for_update()}

            for item_patch in items_data:
                item_id = item_patch.get('item_id')
                is_archived = item_patch.get('is_archived', False)

                if item_id:
                    item_obj = existing_items.get(item_id)
                    if not item_obj:
                        raise NotFound("One of the donation items you are trying to edit could not be found.")
                else:
                    item_obj = None

                if item_obj and is_archived:
                    item_obj.is_archived = True
                    item_obj.save()
                elif item_obj:
                    if 'lookup' in item_patch:
                        item_obj.lookup = item_patch['lookup']
                    if 'weight_kg' in item_patch:
                        item_obj.weight_kg = item_patch['weight_kg']
                    if 'condition_rating' in item_patch:
                        item_obj.condition_rating = item_patch['condition_rating'].upper().replace(" ", "_")
                    item_obj.save()
                elif not item_id and not is_archived:
                    DonationItem.objects.create(
                        donation=donation,
                        lookup=item_patch['lookup'],
                        weight_kg=item_patch['weight_kg'],
                        condition_rating=item_patch['condition_rating'].upper().replace(" ", "_")
                    )

        # Create a single inventory ledger record for the entire received donation
        if validated_data['status'] == DonationStatus.RECEIVED:
            total_active_weight = sum(item.weight_kg for item in donation.items.filter(is_archived=False))
            InventoryLedger.objects.create(
                source_donation=donation,
                usage_amount_kg=Decimal("0.000"),
                weight_before_kg=total_active_weight,
                current_weight_kg=total_active_weight,
            )
            # Log audit trail for the new inventory ledger record
            log_audit(
                actor=user,
                entity_type="inventory_ledger",
                action="CONSUMPTION_LOG",
                ip_address=ip_address,
                fields_modified=["source_donation", "usage_amount_kg", "weight_before_kg", "current_weight_kg"]
            )

        # Log audit trail
        log_audit(
            actor=user,
            entity_type="donations",
            action="STATUS_CHANGE",
            ip_address=ip_address,
            fields_modified=list(validated_data.keys())
        )

    return {"detail": f"Donation successfully resolved as {validated_data['status'].lower()}."}
