import json
import os
from io import BytesIO
from PIL import Image as PILImage
from datetime import timedelta
from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone

from ..models import Donation, DonationItem, Upload, User, DonationStatus, DonationItemConditionRating, Order, OrderStatus, PaymentStatus, DonationDeliveryMethod
from ..serializers.donations import DonationCreateSerializer, DonorDonationUpdateSerializer, AdminDonationUpdateSerializer
from .lalamove_service import cancel_lalamove_order, reverse_or_refund_payment
from .location_service import get_city_and_barangay
from .audit_service import log_audit, get_client_ip
from .prediction_service import run_predictions_for_donation
from rest_framework.exceptions import PermissionDenied, APIException, NotFound


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
        raise PermissionDenied("Only registered businesses can mark donations as in-transit.")
    
    if user.status != 'ACTIVE':
        raise PermissionDenied("Your business account must be active to mark donations as in-transit.")

    if donation.claimed_by_tuab != user:
        raise PermissionDenied("You can only manage donations that have been claimed by your own business.")

    if donation.delivery_method != 'PICKUP':
        exc = APIException("Only pick-up donations can be manually marked as in-transit. Delivery donations are tracked automatically by our logistics partner.")
        exc.status_code = 409
        raise exc

    if donation.status != DonationStatus.CLAIMED:
        exc = APIException(f"This donation cannot be marked as in-transit because its current status is {donation.status.lower().replace('_', ' ')}.")
        exc.status_code = 409
        raise exc

    with transaction.atomic():
        # Pessimistically lock the donation row to prevent concurrent modifications
        donation = Donation.objects.select_for_update().get(pk=donation.pk)

        # Re-verify the status under the lock to prevent race conditions
        if donation.status != DonationStatus.CLAIMED:
            exc = APIException(f"This donation cannot be marked as in-transit because its current status is {donation.status.lower().replace('_', ' ')}.")
            exc.status_code = 409
            raise exc

        donation.status = DonationStatus.IN_TRANSIT
        donation.updated_at = timezone.now()
        donation.save(update_fields=["status", "updated_at"])
        
        log_audit(
            actor=user,
            entity_type="donations",
            action="STATUS_CHANGE",
            ip_address=ip_address,
            fields_modified=["status"]
        )
    
    return {"detail": "Donation successfully marked as in-transit."}

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
    # Use request.FILES to check for new image
    image_file = request.FILES.get('donation_image')

    with transaction.atomic():
        # 1. Handle Image update
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

        # 2. Update Header (This will save the donation once)
        donation = serializer.save()

        # 3. Handle Items (Atomic)
        if items_data is not None:
            for item_patch in items_data:
                item_id = item_patch.get('item_id')
                is_archived = item_patch.get('is_archived', False)

                if item_id:
                    # Update or Archive
                    try:
                        item_obj = DonationItem.objects.select_for_update().get(pk=item_id, donation=donation)
                    except DonationItem.DoesNotExist:
                        raise NotFound("One of the donation items you are trying to edit could not be found.")

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

        # 5. AI Prediction Trigger
        # If this fails (technical error), the transaction rolls back and the donation is NOT updated.
        # We run predictions if items or location fields were modified.
        if (items_data is not None) or ('pickup_latitude' in v_data) or ('pickup_longitude' in v_data):
            try:
                run_predictions_for_donation(donation.donation_id)
            except Exception as e:
                raise ValueError(f"Donation update failed due to AI matching error: {str(e)}")

    return donation


def admin_update_donation(*, request, donation) -> Donation:
    """
    Orchestrates the donation update process for an Admin:
    1. Validates via AdminDonationUpdateSerializer.
    2. Updates header fields (including image handling if provided).
    3. Handles atomic item updates (Add, Update, Archive).
    4. Handles associated Order updates if dropoff location is supplied.
    5. Runs side effects (Audit log, AI prediction trigger on items change).
    """
    serializer = AdminDonationUpdateSerializer(donation, data=request.data, context={'request': request}, partial=True)
    serializer.is_valid(raise_exception=True)
    v_data = serializer.validated_data
    items_data = v_data.pop('items', None)
    v_data.pop('donation_image', None)  # Ensure it doesn't get set directly
    image_file = request.FILES.get('donation_image')

    dropoff_address = v_data.pop('dropoff_display_address', None)
    dropoff_lat = v_data.pop('dropoff_latitude', None)
    dropoff_lng = v_data.pop('dropoff_longitude', None)

    with transaction.atomic():
        # 1. Handle Image update
        if image_file:
            try:
                img = PILImage.open(image_file)
                if img.mode != 'RGB': 
                    img = img.convert('RGB')
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

        # 2. Update Donation model fields
        for k, v in v_data.items():
            setattr(donation, k, v)
        donation.save()

        # 3. Handle Items (Atomic updates)
        if items_data is not None:
            for item_patch in items_data:
                item_id = item_patch.get('item_id')
                is_archived = item_patch.get('is_archived', False)

                if item_id:
                    # Update or Archive
                    try:
                        item_obj = DonationItem.objects.select_for_update().get(pk=item_id, donation=donation)
                    except DonationItem.DoesNotExist:
                        raise NotFound("One of the donation items you are trying to edit could not be found.")

                    if is_archived:
                        item_obj.is_archived = True
                    else:
                        if 'lookup' in item_patch: 
                            item_obj.lookup = item_patch['lookup']
                        if 'weight_kg' in item_patch: 
                            item_obj.weight_kg = item_patch['weight_kg']
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

        # 4. Update associated Order dropoff fields if present
        if dropoff_address is not None or dropoff_lat is not None or dropoff_lng is not None:
            order = donation.orders.select_for_update().filter(status__in=['ASSIGNING_DRIVER', 'ON_GOING', 'PICKED_UP']).first()
            if order:
                if dropoff_address is not None:
                    order.dropoff_display_address = dropoff_address
                if dropoff_lat is not None:
                    order.dropoff_latitude = dropoff_lat
                if dropoff_lng is not None:
                    order.dropoff_longitude = dropoff_lng
                order.save()

                if order.lalamove_order_id:
                    from .lalamove_service import update_lalamove_order
                    res = update_lalamove_order(
                        lalamove_order_id=order.lalamove_order_id,
                        pickup_lat=donation.pickup_latitude,
                        pickup_lng=donation.pickup_longitude,
                        pickup_address=donation.pickup_display_address or "N/A",
                        dropoff_lat=order.dropoff_latitude,
                        dropoff_lng=order.dropoff_longitude,
                        dropoff_address=order.dropoff_display_address,
                        pickup_name=f"{donation.donor.first_name or ''} {donation.donor.last_name or ''}".strip(),
                        pickup_phone=donation.donor.contact_no,
                        dropoff_name=(
                            f"{(donation.claimed_by_tuab.first_name if donation.claimed_by_tuab else '') or ''} "
                            f"{(donation.claimed_by_tuab.last_name if donation.claimed_by_tuab else '') or ''}"
                        ).strip() or (donation.claimed_by_tuab.business_name if donation.claimed_by_tuab else ""),
                        dropoff_phone=donation.claimed_by_tuab.contact_no if donation.claimed_by_tuab else None,
                    )
                    if "error" in res:
                        err = json.loads(res["error"]) if isinstance(res["error"], str) and res["error"].startswith("{") else res["error"]
                        msg = next((item.get("message") or item.get("detail") for item in (err.get("errors") or []) if isinstance(item, dict) and (item.get("message") or item.get("detail"))), err.get("message") or err.get("detail") or str(err)) if isinstance(err, dict) else str(err)
                        exc = APIException(f"Failed to update dropoff with Lalamove: {msg}")
                        exc.status_code = res.get("status_code", 400)
                        raise exc

        # 5. Audit Logging
        log_audit(
            actor=request.user,
            entity_type="donations",
            action="STATUS_CHANGE",
            ip_address=get_client_ip(request),
            fields_modified=list(request.data.keys())
        )

        # 6. AI Prediction Trigger
        if (items_data is not None) or ('pickup_latitude' in v_data) or ('pickup_longitude' in v_data):
            try:
                run_predictions_for_donation(donation.donation_id)
            except Exception as e:
                raise ValueError(f"Donation update failed due to AI matching error: {str(e)}")

    return donation


def cancel_donation(*, user, donation, ip_address=None):
    # Enforce global role restriction: Only admins and donors can initiate cancellation
    if user.role not in ["Admin", "Donor"]:
        raise PermissionDenied("You are not authorized to cancel this donation.")

    # Execute cancellation orchestration inside a single atomic transaction
    with transaction.atomic():
        # Retrieve donation with database pessimistic locking to avoid race conditions
        donation = Donation.objects.select_for_update().get(pk=donation.pk)

        # Handle Donor-led cancellation path
        if user.role == "Donor":
            # Guard: Donor must be the original owner of the donation
            if donation.donor != user:
                raise PermissionDenied("You can only cancel donations that you originally created.")

            # Donors can only cancel when the status is PENDING
            if donation.status == DonationStatus.PENDING:
                donation.status, donation.updated_at = DonationStatus.CANCELLED, timezone.now(); donation.save(update_fields=["status", "updated_at"])
                
                # Write to the audit trail logging the status change
                log_audit(user, "donations", "STATUS_CHANGE", ip_address, ["status"])
                return {"detail": "Donation successfully cancelled."}

            # Donors are forbidden from cancelling any other status
            else:
                exc = APIException("This donation cannot be cancelled because it has already been claimed by a business.")
                exc.status_code = 409
                raise exc

        # Handle Admin-led cancellation path
        elif user.role == "Admin":
            # Case 1: Pending Donation Cancellation
            if donation.status == DonationStatus.PENDING:
                donation.status, donation.updated_at = DonationStatus.CANCELLED, timezone.now(); donation.save(update_fields=["status", "updated_at"])
                
                # Write to the audit trail logging the status change
                log_audit(user, "donations", "STATUS_CHANGE", ip_address, ["status"])
                return {"detail": "Donation successfully cancelled by admin."}

            # Case 2: Claimed Pickup Donation Cancellation
            elif donation.status == DonationStatus.CLAIMED and donation.delivery_method == DonationDeliveryMethod.PICKUP:
                donation.status, donation.updated_at = DonationStatus.CANCELLED, timezone.now(); donation.save(update_fields=["status", "updated_at"])
                
                # Write to the audit trail logging the status change
                log_audit(user, "donations", "STATUS_CHANGE", ip_address, ["status"])
                return {"detail": "Donation successfully cancelled by admin."}

            # Case 3: Claimed Delivery Donation Cancellation (requires external logistics cancellation and payment refund)
            elif donation.status == DonationStatus.CLAIMED and donation.delivery_method == DonationDeliveryMethod.DELIVERY:
                # Retrieve the active delivery order associated with this donation
                order = Order.objects.filter(donation=donation).exclude(status=OrderStatus.CANCELLED).first()
                if not order or not order.lalamove_order_id:
                    raise NotFound("Could not find an active delivery order associated with this donation.")

                # Terminate the order inside Lalamove API
                lalamove_res = cancel_lalamove_order(order.lalamove_order_id)
                if "error" in lalamove_res:
                    exc = APIException(f"Lalamove cancellation failed. We were unable to cancel the delivery at this time. Please try again. Error detail: {json.loads(lalamove_res['error'])['errors'][0]['message'] if lalamove_res['error'].startswith('{') else lalamove_res['error']}")
                    exc.status_code = 502
                    raise exc
                order.status, order.updated_at = OrderStatus.CANCELLED, timezone.now(); order.save(update_fields=["status", "updated_at"])

                donation.status, donation.updated_at = DonationStatus.CANCELLED, timezone.now(); donation.save(update_fields=["status", "updated_at"])

                # Refund the claiming TUAB's payment if it was captured successfully
                payment = order.payments.filter(status=PaymentStatus.SUCCESS).first()
                if payment and payment.payment_reference:
                    reverse_or_refund_payment(payment, payment.amount)

                # Write to the audit trail logging the status change
                log_audit(user, "donations", "STATUS_CHANGE", ip_address, ["status"])
                return {"detail": "Donation and associated delivery successfully cancelled by admin."}

            # Admin is forbidden from cancelling in any other status
            else:
                exc = APIException(f"This donation cannot be cancelled because its current status is {DonationStatus(donation.status).label}.")
                exc.status_code = 409
                raise exc


def archive_donation(*, user, donation, ip_address=None):

    # Enforce role restriction: Only admins can archive
    if user.role != "Admin":
        raise PermissionDenied("You are not authorized to archive this donation.")

    with transaction.atomic():
        # Retrieve donation with database pessimistic locking
        donation = Donation.objects.select_for_update().get(pk=donation.pk)

        # Check if there is an in-progress delivery order
        order = Order.objects.filter(donation=donation).exclude(
            status__in=[OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.FAILED]
        ).first()

        if order:
            if not order.lalamove_order_id:
                raise NotFound("Could not find an active delivery order associated with this donation.")

            # Terminate the order inside Lalamove API
            lalamove_res = cancel_lalamove_order(order.lalamove_order_id)
            if "error" in lalamove_res:
                exc = APIException(f"Lalamove cancellation failed. We were unable to cancel the delivery at this time. Please try again. Error detail: {json.loads(lalamove_res['error'])['errors'][0]['message'] if lalamove_res['error'].startswith('{') else lalamove_res['error']}")
                exc.status_code = 502
                raise exc

            order.status, order.updated_at = OrderStatus.CANCELLED, timezone.now()
            order.save(update_fields=["status", "updated_at"])

            # Refund the claiming TUAB's payment if it was captured successfully
            payment = order.payments.filter(status=PaymentStatus.SUCCESS).first()
            if payment and payment.payment_reference:
                reverse_or_refund_payment(payment, payment.amount)

        # Archive the donation
        donation.status, donation.updated_at = DonationStatus.ARCHIVED, timezone.now()
        donation.save(update_fields=["status", "updated_at"])

        # Write to the audit trail
        log_audit(user, "donations", "STATUS_CHANGE", ip_address, ["status"])

        return {"detail": "Donation successfully archived by admin."}
