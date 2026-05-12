import os
from datetime import timedelta
from django.db import transaction
from django.core.files.storage import default_storage
from django.utils import timezone

from ..models import Donation, DonationItem, Upload, User, DonationStatus, DonationItemConditionRating
from ..serializers.donations import DonationCreateSerializer
from .location_service import get_city_and_barangay
from .audit_service import log_audit, get_client_ip
from .prediction_service import run_predictions_for_donation

def create_donation(*, request):
    """
    Orchestrates the donation creation process in a hybrid way:
    1. Validates via DonationCreateSerializer.
    2. Calls serializer.save() to create the Donation header (handled in Serializer.create).
    3. Manually creates DonationItem records in this service layer.
    4. Handles side effects (Audit, Predictions).
    """
    serializer = DonationCreateSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    
    # Extract items_data before serializer.save() pops it
    items_data = serializer.validated_data.get('items')
    donor_id = serializer.validated_data.get('donor_user_id')

    with transaction.atomic():
        # 1. Identity Locking
        User.objects.select_for_update().get(pk=donor_id)

        # 2. Create Donation Header (triggers DonationCreateSerializer.create)
        donation = serializer.save()

        # 3. Create Donation Items (handled in service as requested)
        donation_items = [
            DonationItem(
                donation=donation,
                lookup_id=item['lookup_id'],
                condition_rating=item['condition_rating'].upper().replace(" ", "_"),
                weight_kg=item['weight_kg']
            )
            for item in items_data
        ]
        DonationItem.objects.bulk_create(donation_items)

        # 4. Audit Logging
        log_audit(
            actor=request.user,
            entity_type="donations",
            action="STATUS_CHANGE",
            ip_address=get_client_ip(request),
            fields_modified={
                "donation_id": donation.donation_id,
                "donor_id": donation.donor_id,
                "upload_id": donation.upload_id,
                "status": donation.status,
                "auto_archive_at": donation.auto_archive_at.isoformat() if donation.auto_archive_at else None,
                "pickup_city": donation.pickup_city,
                "pickup_barangay": donation.pickup_barangay,
                "pickup_latitude": str(donation.pickup_latitude),
                "pickup_longitude": str(donation.pickup_longitude),
                "preferred_pickup_date": donation.preferred_pickup_date.isoformat() if donation.preferred_pickup_date else None,
                "preferred_pickup_window_start": str(donation.preferred_pickup_window_start),
                "preferred_pickup_window_end": str(donation.preferred_pickup_window_end)
            }
        )

        # 5. AI Prediction Trigger
        run_predictions_for_donation(donation.donation_id)

    return donation
