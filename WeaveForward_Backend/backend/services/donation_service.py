import os
from io import BytesIO
from PIL import Image as PILImage
from datetime import timedelta
from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone

from ..models import Donation, DonationItem, Upload, User, DonationStatus, DonationItemConditionRating
from ..serializers.donations import DonationCreateSerializer, DonorDonationUpdateSerializer
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

        # 2. Handle Image (Moved before save to avoid double save)
        image_file = request.FILES.get('donation_image')
        if image_file:
            # We don't save yet, just set the attribute
            try:
                img = PILImage.open(image_file)
                if img.mode != 'RGB': img = img.convert('RGB')
                img.thumbnail((1024, 1024), PILImage.Resampling.LANCZOS)
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=65, optimize=True)
                buffer.seek(0)
                filename = f"don_{donor_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                path = default_storage.save(f"donations/{filename}", ContentFile(buffer.read(), name=filename))
                donation_upload = Upload.objects.create(file_path=path, name=filename[:50])
                # We'll pass this to the serializer or set it on the instance
                # Since DonationCreateSerializer is already instantiated, we'll set it in the context or just save later.
                # Actually, DonationCreateSerializer.create is already defined.
            except Exception:
                path = default_storage.save(f"donations/{image_file.name}", image_file)
                donation_upload = Upload.objects.create(file_path=path, name=image_file.name[:50])
        else:
            donation_upload = None

        # 3. Create Donation Header (Single save with upload)
        donation = serializer.save(upload=donation_upload)

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
        # If this fails (technical error), the transaction rolls back and the donation is NOT created.
        try:
            run_predictions_for_donation(donation.donation_id)
        except Exception as e:
            raise ValueError(f"Donation creation failed due to AI matching error: {str(e)}")

    return donation

def mark_donation_in_transit(*, user, donation, ip_address=None):
    """
    Marks a donation as IN_TRANSIT.
    Constraints:
    - User role must be TUAB.
    - User status must be ACTIVE.
    - User must be the one who claimed the donation.
    - Delivery method must be PICKUP.
    - Current status must be CLAIMED.
    """
    if user.role != 'TUAB':
        return {"status_code": 403, "detail": "Only TUABs can mark donations as in-transit."}
    
    if user.status != 'ACTIVE':
        return {"status_code": 403, "detail": "Only active users can mark donations as in-transit."}

    if donation.claimed_by_tuab != user:
        return {"status_code": 403, "detail": "You do not own this donation."}

    if donation.delivery_method != 'PICKUP':
        return {"status_code": 409, "detail": "Only PICKUP donations can be manually marked as in-transit."}

    if donation.status != DonationStatus.CLAIMED:
        return {"status_code": 409, "detail": f"Donation must be CLAIMED to be marked as IN_TRANSIT. Current status: {donation.status}"}

    with transaction.atomic():
        donation.status = DonationStatus.IN_TRANSIT
        donation.save()
        
        log_audit(
            actor=user,
            entity_type="donations",
            action="STATUS_CHANGE",
            ip_address=ip_address,
            fields_modified=["status"]
        )
    
    return {"status_code": 200, "detail": "Donation marked as in-transit."}

def donor_update_donation(*, request, donation):
    """
    Orchestrates the donation update process for a Donor:
    1. Validates via DonorDonationUpdateSerializer.
    2. Updates header fields (Metadata, Image).
    3. Handles atomic item updates (Add, Update, Archive).
    4. Handles side effects (Audit, Re-running predictions).
    """
    serializer = DonorDonationUpdateSerializer(donation, data=request.data, context={'request': request}, partial=True)
    serializer.is_valid(raise_exception=True)
    v_data = serializer.validated_data
    items_data = v_data.get('items')
    # Use request.data to check if key was present (for partial updates)
    has_image_update = 'donation_image' in request.data
    image_file = request.FILES.get('donation_image')

    with transaction.atomic():
        # 1. Handle Image update (Before serializer.save to avoid double save)
        if has_image_update:
            if image_file:
                try:
                    img = PILImage.open(image_file)
                    if img.mode != 'RGB': img = img.convert('RGB')
                    img.thumbnail((1024, 1024), PILImage.Resampling.LANCZOS)
                    buffer = BytesIO()
                    img.save(buffer, format='JPEG', quality=65, optimize=True)
                    buffer.seek(0)
                    filename = f"don_{donation.donor_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    path = default_storage.save(f"donations/{filename}", ContentFile(buffer.read(), name=filename))
                    donation.upload = Upload.objects.create(file_path=path, name=filename[:50])
                except Exception:
                    path = default_storage.save(f"donations/{image_file.name}", image_file)
                    donation.upload = Upload.objects.create(file_path=path, name=image_file.name[:50])
            else:
                donation.upload = None

        # 2. Update Header (This will save the donation once)
        donation = serializer.save()

        # 3. Handle Items (Atomic)
        if items_data is not None:
            for item_patch in items_data:
                item_id = item_patch.get('item_id')
                is_archived = item_patch.get('is_archived', False)

                if item_id:
                    # Update or Archive
                    item_obj = DonationItem.objects.select_for_update().get(pk=item_id, donation=donation)
                    if is_archived:
                        item_obj.is_archived = True
                    else:
                        if 'lookup' in item_patch: item_obj.lookup = item_patch['lookup']
                        if 'weight_kg' in item_patch: item_obj.weight_kg = item_patch['weight_kg']
                        if 'condition_rating' in item_patch: 
                            item_obj.condition_rating = item_patch['condition_rating'].upper().replace(" ", "_")
                    item_obj.save()
                elif not is_archived:
                    # Create New
                    DonationItem.objects.create(
                        donation=donation,
                        lookup=item_patch['lookup'],
                        weight_kg=item_patch['weight_kg'],
                        condition_rating=item_patch['condition_rating'].upper().replace(" ", "_")
                    )

        # 4. Audit Logging
        log_audit(
            actor=request.user,
            entity_type="donations",
            action="STATUS_CHANGE",
            ip_address=get_client_ip(request),
            fields_modified=list(v_data.keys())
        )


    return donation
