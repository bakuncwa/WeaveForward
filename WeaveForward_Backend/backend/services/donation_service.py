import json
import os
import requests
import hmac
import hashlib
import time
import base64
from decimal import Decimal
from io import BytesIO
from PIL import Image as PILImage
from datetime import timedelta
from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone
from django.conf import settings
from django.utils.dateparse import parse_datetime
import uuid

from ..models import Donation, DonationItem, Upload, User, DonationStatus, DonationItemConditionRating, Order, OrderPayment, OrderStatus, PaymentStatus, DonationDeliveryMethod, UserRole, InventoryLedger
from ..serializers.donations import DonationCreateSerializer, DonorDonationUpdateSerializer, AdminDonationUpdateSerializer
from .lalamove_service import cancel_lalamove_order, reverse_or_refund_payment, update_lalamove_order
from .location_service import get_city_and_barangay
from .audit_service import log_audit, get_client_ip
from .etag_service import build_updated_at_etag, matches_if_match
from .prediction_service import run_predictions_for_donation
from rest_framework.exceptions import PermissionDenied, APIException, NotFound


def _extract_external_error_message(error):
    if isinstance(error, str) and error.startswith("{"):
        try:
            error = json.loads(error)
        except ValueError:
            return error

    if isinstance(error, dict):
        errors = error.get("errors") or []
        message = next(
            (
                item.get("message") or item.get("detail")
                for item in errors
                if isinstance(item, dict) and (item.get("message") or item.get("detail"))
            ),
            None,
        )
        return message or error.get("message") or error.get("detail") or str(error)

    return str(error)


def _raise_external_api_error(prefix, result, default_status=400):
    exc = APIException(f"{prefix}: {_extract_external_error_message(result.get('error'))}")
    exc.status_code = result.get("status_code", default_status)
    raise exc


def _revert_failed_delivery_claim(*, donation_id, user_id, order_id, payment_id=None, reversal_reference=None):
    with transaction.atomic():
        donation = Donation.objects.select_for_update().get(pk=donation_id)
        order = Order.objects.select_for_update().get(pk=order_id)

        if donation.claimed_by_tuab_id == user_id and donation.delivery_method == DonationDeliveryMethod.DELIVERY and order.status == OrderStatus.FAILED:
            donation.status = DonationStatus.PENDING
            donation.claimed_by_tuab = None
            donation.delivery_method = None
            donation.updated_at = timezone.now()
            donation.save(update_fields=["status", "claimed_by_tuab", "delivery_method", "updated_at"])

        if payment_id and reversal_reference:
            payment = OrderPayment.objects.select_for_update().get(pk=payment_id)
            OrderPayment.objects.create(
                order=order,
                amount=-payment.amount,
                status=PaymentStatus.SUCCESS,
                payment_reference=reversal_reference,
            )


def create_donation(*, request):
    """
    Orchestrates the donation creation process in a hybrid way:
    1. Validates via DonationCreateSerializer.
    2. Calls serializer.save() to create the Donation header (handled in Serializer.create).
    3. Manually creates DonationItem records in this service layer.
    4. Handles side effects (Audit, Predictions).

    Complexity notes:
    - Let n = number of submitted donation items.
    - Let i = number of active items used by prediction inference.
    - Let t = number of eligible TUAB users.
    - Overall dominant cost is O(i * t) because prediction generation builds
      every active-item / TUAB pair.
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
            img = PILImage.open(image_file)
            if img.mode != 'RGB': img = img.convert('RGB')
            img.thumbnail((1024, 1024), PILImage.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=65, optimize=True)
            buffer.seek(0)
            filename = f"don_{donor_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            hashed_filename = f"{uuid.uuid4().hex}.jpg"
            path = default_storage.save(f"donations/{hashed_filename}", ContentFile(buffer.read(), name=hashed_filename))
            donation_upload = Upload.objects.create(file_path=path, name=hashed_filename)
            # We'll pass this to the serializer or set it on the instance
            # Since DonationCreateSerializer is already instantiated, we'll set it in the context or just save later.
            # Actually, DonationCreateSerializer.create is already defined.
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
            raise ValueError("Donation creation failed because AI matching is temporarily unavailable.")

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
        donation = Donation.objects.select_for_update().get(pk=donation.pk)
        serializer.instance = donation

        if donation.status != DonationStatus.PENDING:
            exc = APIException(f"This donation cannot be modified because its current status is {donation.status.lower().replace('_', ' ')}.")
            exc.status_code = 409
            raise exc

        # 1. Handle Image update
        if image_file:
            img = PILImage.open(image_file)
            if img.mode != 'RGB': img = img.convert('RGB')
            img.thumbnail((1024, 1024), PILImage.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=65, optimize=True)
            buffer.seek(0)
            filename = f"don_{donation.donor_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            hashed_filename = f"{uuid.uuid4().hex}.jpg"
            path = default_storage.save(f"donations/{hashed_filename}", ContentFile(buffer.read(), name=hashed_filename))
            donation.upload = Upload.objects.create(file_path=path, name=hashed_filename)

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
                raise ValueError("Donation update failed because AI matching is temporarily unavailable.")

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

    lalamove_update_payload = None
    lalamove_update_order_id = None
    lalamove_update_lalamove_order_id = None

    if dropoff_address is not None or dropoff_lat is not None or dropoff_lng is not None:
        with transaction.atomic():
            donation = Donation.objects.select_for_update().get(pk=donation.pk)

            if donation.status == DonationStatus.ARCHIVED:
                exc = APIException("Donations in archived status are immutable.")
                exc.status_code = 409
                raise exc

            if_match = request.headers.get('If-Match')
            if if_match and not matches_if_match(build_updated_at_etag(donation), if_match):
                exc = APIException("ETag does not match the current resource version.")
                exc.status_code = 412
                raise exc

            order = donation.orders.select_for_update().filter(status__in=['ASSIGNING_DRIVER', 'ON_GOING', 'PICKED_UP']).first()
            if order and order.lalamove_order_id:
                lalamove_update_order_id = order.pk
                lalamove_update_lalamove_order_id = order.lalamove_order_id
                lalamove_update_payload = {
                    "lalamove_order_id": order.lalamove_order_id,
                    "pickup_lat": v_data.get('pickup_latitude', donation.pickup_latitude),
                    "pickup_lng": v_data.get('pickup_longitude', donation.pickup_longitude),
                    "pickup_address": v_data.get('pickup_display_address', donation.pickup_display_address) or "N/A",
                    "dropoff_lat": dropoff_lat if dropoff_lat is not None else order.dropoff_latitude,
                    "dropoff_lng": dropoff_lng if dropoff_lng is not None else order.dropoff_longitude,
                    "dropoff_address": dropoff_address if dropoff_address is not None else order.dropoff_display_address,
                    "pickup_name": f"{donation.donor.first_name or ''} {donation.donor.last_name or ''}".strip(),
                    "pickup_phone": donation.donor.contact_no,
                    "dropoff_name": (
                        f"{(donation.claimed_by_tuab.first_name if donation.claimed_by_tuab else '') or ''} "
                        f"{(donation.claimed_by_tuab.last_name if donation.claimed_by_tuab else '') or ''}"
                    ).strip() or (donation.claimed_by_tuab.business_name if donation.claimed_by_tuab else ""),
                    "dropoff_phone": donation.claimed_by_tuab.contact_no if donation.claimed_by_tuab else None,
                }

        if lalamove_update_payload:
            res = update_lalamove_order(**lalamove_update_payload)
            if "error" in res:
                _raise_external_api_error("Failed to update dropoff with Lalamove", res)

    with transaction.atomic():
        donation = Donation.objects.select_for_update().get(pk=donation.pk)
        serializer.instance = donation

        if donation.status == DonationStatus.ARCHIVED:
            exc = APIException("Donations in archived status are immutable.")
            exc.status_code = 409
            raise exc

        if_match = request.headers.get('If-Match')
        if if_match and not matches_if_match(build_updated_at_etag(donation), if_match):
            exc = APIException("ETag does not match the current resource version.")
            exc.status_code = 412
            raise exc

        # 1. Handle Image update
        if image_file:
            img = PILImage.open(image_file)
            if img.mode != 'RGB': 
                img = img.convert('RGB')
            img.thumbnail((1024, 1024), PILImage.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=65, optimize=True)
            buffer.seek(0)
            filename = f"don_{donation.donor_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            hashed_filename = f"{uuid.uuid4().hex}.jpg"
            path = default_storage.save(f"donations/{hashed_filename}", ContentFile(buffer.read(), name=hashed_filename))
            donation.upload = Upload.objects.create(file_path=path, name=hashed_filename)

        # 2. Update Donation model fields
        if 'is_flagged' in v_data and not v_data['is_flagged']:
            v_data['flag_reason'] = None
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
            if lalamove_update_order_id:
                order = donation.orders.select_for_update().filter(pk=lalamove_update_order_id).first()
                if (
                    not order
                    or order.lalamove_order_id != lalamove_update_lalamove_order_id
                    or order.status not in ['ASSIGNING_DRIVER', 'ON_GOING', 'PICKED_UP']
                ):
                    exc = APIException("Dropoff update could not be finalized because the delivery order changed during the Lalamove update.")
                    exc.status_code = 409
                    raise exc
            else:
                order = donation.orders.select_for_update().filter(status__in=['ASSIGNING_DRIVER', 'ON_GOING', 'PICKED_UP']).first()
            if order:
                if dropoff_address is not None:
                    order.dropoff_display_address = dropoff_address
                if dropoff_lat is not None:
                    order.dropoff_latitude = dropoff_lat
                if dropoff_lng is not None:
                    order.dropoff_longitude = dropoff_lng
                order.save()

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
                raise ValueError("Donation update failed because AI matching is temporarily unavailable.")

    return donation


def cancel_donation(*, user, donation, ip_address=None):
    # Enforce global role restriction: Only admins and donors can initiate cancellation
    if user.role not in ["Admin", "Donor"]:
        raise PermissionDenied("You are not authorized to cancel this donation.")

    payment_ids_to_refund = []

    # Execute local cancellation checks and state changes inside short transactions
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
                exc = APIException("This donation cannot be cancelled. Please contact the WeaveForward administrators for assistance.")
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
                order = Order.objects.select_for_update().filter(donation=donation).exclude(status=OrderStatus.CANCELLED).first()
                if not order or not order.lalamove_order_id:
                    raise NotFound("Could not find an active delivery order associated with this donation.")

                lalamove_order_id = order.lalamove_order_id
                order_id = order.pk

            # Admin is forbidden from cancelling in any other status
            else:
                exc = APIException(f"This donation cannot be cancelled because its current status is {DonationStatus(donation.status).label}.")
                exc.status_code = 409
                raise exc

    # Terminate the order outside the database transaction
    lalamove_res = cancel_lalamove_order(lalamove_order_id)
    if "error" in lalamove_res:
        _raise_external_api_error(
            "Lalamove cancellation failed. We were unable to cancel the delivery at this time. Please try again. Error detail",
            lalamove_res,
            default_status=502,
        )

    with transaction.atomic():
        donation = Donation.objects.select_for_update().get(pk=donation.pk)
        order = Order.objects.select_for_update().get(pk=order_id)

        if donation.status != DonationStatus.CLAIMED or donation.delivery_method != DonationDeliveryMethod.DELIVERY or order.status == OrderStatus.CANCELLED:
            exc = APIException("This donation can no longer be cancelled because its state changed during delivery cancellation.")
            exc.status_code = 409
            raise exc

        order.status, order.updated_at = OrderStatus.CANCELLED, timezone.now()
        order.save(update_fields=["status", "updated_at"])

        donation.status, donation.updated_at = DonationStatus.CANCELLED, timezone.now()
        donation.save(update_fields=["status", "updated_at"])

        payment_ids_to_refund = list(order.payments.filter(status=PaymentStatus.SUCCESS, amount__gt=0).values_list("pk", flat=True))

        # Write to the audit trail logging the status change
        log_audit(user, "donations", "STATUS_CHANGE", ip_address, ["status"])

    for payment in OrderPayment.objects.filter(pk__in=payment_ids_to_refund):
        reverse_or_refund_payment(payment, payment.amount)

    return {"detail": "Donation and associated delivery successfully cancelled by admin."}


def archive_donation(*, user, donation, ip_address=None):

    if user.role != "Admin":
        raise PermissionDenied("You are not authorized to archive this donation.")

    order_id = None
    lalamove_order_id = None
    payment_ids_to_refund = []

    with transaction.atomic():
        # Retrieve donation with database pessimistic locking
        donation = Donation.objects.select_for_update().get(pk=donation.pk)

        # Check if there is an in-progress delivery order
        order = Order.objects.select_for_update().filter(donation=donation).exclude(
            status__in=[OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.FAILED]
        ).first()

        if order:
            if not order.lalamove_order_id:
                raise NotFound("Could not find an active delivery order associated with this donation.")
            order_id = order.pk
            lalamove_order_id = order.lalamove_order_id

    if lalamove_order_id:
        lalamove_res = cancel_lalamove_order(lalamove_order_id)
        if "error" in lalamove_res:
            _raise_external_api_error(
                "Lalamove cancellation failed. We were unable to cancel the delivery at this time. Please try again. Error detail",
                lalamove_res,
                default_status=502,
            )

    with transaction.atomic():
        donation = Donation.objects.select_for_update().get(pk=donation.pk)

        if order_id:
            order = Order.objects.select_for_update().get(pk=order_id)
            if order.status in [OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.FAILED]:
                exc = APIException("This donation can no longer be archived because its delivery state changed during cancellation.")
                exc.status_code = 409
                raise exc
            order.status, order.updated_at = OrderStatus.CANCELLED, timezone.now()
            order.save(update_fields=["status", "updated_at"])

            payment_ids_to_refund = list(order.payments.filter(status=PaymentStatus.SUCCESS, amount__gt=0).values_list("pk", flat=True))

        # Archive the donation
        donation.status, donation.updated_at = DonationStatus.ARCHIVED, timezone.now()
        donation.save(update_fields=["status", "updated_at"])

        # Write to the audit trail
        log_audit(user, "donations", "STATUS_CHANGE", ip_address, ["status"])

    for payment in OrderPayment.objects.filter(pk__in=payment_ids_to_refund):
        reverse_or_refund_payment(payment, payment.amount)

    return {"detail": "Donation successfully archived."}


def process_auto_archive_donations():
    """
    Finds all active/pending donations that are past their auto_archive_at date
    and archives them directly.
    """
    with transaction.atomic():
        now = timezone.now()
        expired_donations = Donation.objects.select_for_update().filter(
            auto_archive_at__lte=now
        ).exclude(status__in=[DonationStatus.ARCHIVED, DonationStatus.CANCELLED])

        archived_count = 0
        admin_user = User.objects.filter(role=UserRole.ADMIN).first()

        for donation in expired_donations:
            donation.status = DonationStatus.ARCHIVED
            donation.updated_at = now
            donation.save(update_fields=['status', 'updated_at'])

            # Log audit event for the auto-archived donation directly
            log_audit(
                actor=admin_user or donation.donor,
                entity_type="donations",
                action="STATUS_CHANGE",
                ip_address=None,
                fields_modified=["status"]
            )
            archived_count += 1

    return archived_count


def sign_quotation_data(data):
    """
    Signs quotation data for the view using HMAC-SHA256. 
    This provides a stateless mechanism for verifying quotation integrity.
    """
    data_json = json.dumps(data, separators=(',', ':'), sort_keys=True, default=str)
    data_b64 = base64.urlsafe_b64encode(data_json.encode()).decode().rstrip('=')
    signature = hmac.new(settings.SECRET_KEY.encode(), data_b64.encode(), hashlib.sha256).hexdigest()
    return f"{data_b64}.{signature}"



def claim_donation(user, donation, claim_params, ip_address=None):
    """
    Orchestrates the donation claiming process while keeping external API calls
    outside database transactions.
    """
    delivery_method = claim_params.get('delivery_method')

    if delivery_method == 'PICKUP':
        with transaction.atomic():
            donation = Donation.objects.select_for_update().get(pk=donation.pk)
            user = User.objects.select_for_update().get(pk=user.pk)

            if user.operational_status != 'ACTIVE':
                raise PermissionDenied("Only operational TUABs can claim donations.")
            if donation.status != DonationStatus.PENDING:
                exc = APIException("This donation is no longer available to be claimed.")
                exc.status_code = 409
                raise exc
            if Donation.objects.filter(claimed_by_tuab=user, status__in=[DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT]).count() >= user.max_active_claims:
                exc = APIException(f"You have reached your active claim limit of {user.max_active_claims} active claims. Please complete or cancel your existing claims first.")
                exc.status_code = 409
                raise exc

            donation.status, donation.claimed_by_tuab, donation.delivery_method = DonationStatus.CLAIMED, user, DonationDeliveryMethod.PICKUP
            donation.save()
            log_audit(user, 'donations', 'STATUS_CHANGE', ip_address, ['status', 'claimed_by_tuab', 'delivery_method'])
            return {"detail": "Donation successfully claimed for pickup."}

    quotation_token = claim_params.get('quotation_token')
    if not quotation_token:
        exc = APIException("Malformed or expired quotation token.")
        exc.status_code = 400
        raise exc

    try:
        data_b64, token_signature = quotation_token.split('.')
        if not hmac.compare_digest(hmac.new(settings.SECRET_KEY.encode(), data_b64.encode(), hashlib.sha256).hexdigest(), token_signature):
            exc = APIException("Invalid quotation signature.")
            exc.status_code = 400
            raise exc

        token_data = json.loads(base64.urlsafe_b64decode(data_b64 + '=' * (4 - len(data_b64) % 4)).decode())
        if token_data.get('expires_at', 0) < int(time.time()):
            exc = APIException("Quotation has expired.")
            exc.status_code = 400
            raise exc

        charge_amount = float(token_data['amount'])
        lalamove_quotation_id = token_data['quotationId']
        pickup_stop_id = token_data['stopId_1']
        dropoff_stop_id = token_data['stopId_2']
        order_scheduled_at = parse_datetime(token_data.get('schedule_at')) if token_data.get('schedule_at') else timezone.now()
    except APIException:
        raise
    except Exception:
        exc = APIException("Malformed or expired quotation token.")
        exc.status_code = 400
        raise exc

    if order_scheduled_at < timezone.now():
        exc = APIException("The selected delivery schedule is in the past. Please request a new quotation with a later time within the pickup window.")
        exc.status_code = 409
        raise exc

    with transaction.atomic():
        donation = Donation.objects.select_for_update().get(pk=donation.pk)
        user = User.objects.select_for_update().get(pk=user.pk)

        if user.operational_status != 'ACTIVE':
            raise PermissionDenied("Only operational TUABs can claim donations.")
        if donation.status != DonationStatus.PENDING:
            exc = APIException("This donation is no longer available to be claimed.")
            exc.status_code = 409
            raise exc
        if Donation.objects.filter(claimed_by_tuab=user, status__in=[DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT]).count() >= user.max_active_claims:
            exc = APIException(f"You have reached your active claim limit of {user.max_active_claims} active claims. Please complete or cancel your existing claims first.")
            exc.status_code = 409
            raise exc
        if not all([user.maya_customer_id, user.maya_card_id]):
            exc = APIException("Your payment details are not fully configured. Please setup your credit card in your profile before claiming deliveries.")
            exc.status_code = 400
            raise exc

        quoted_dropoff_address = token_data.get('dropoff_address') or user.display_address or "N/A"
        quoted_dropoff_lat = Decimal(str(token_data.get('dropoff_latitude') if token_data.get('dropoff_latitude') is not None else user.latitude or 0))
        quoted_dropoff_lng = Decimal(str(token_data.get('dropoff_longitude') if token_data.get('dropoff_longitude') is not None else user.longitude or 0))

        donation.status, donation.claimed_by_tuab, donation.delivery_method = DonationStatus.CLAIMED, user, DonationDeliveryMethod.DELIVERY
        donation.save(update_fields=["status", "claimed_by_tuab", "delivery_method", "updated_at"])

        order_record = Order.objects.create(donation=donation, status=OrderStatus.FAILED, dropoff_display_address=quoted_dropoff_address, dropoff_latitude=quoted_dropoff_lat, dropoff_longitude=quoted_dropoff_lng, scheduled_at=order_scheduled_at, expires_at=order_scheduled_at + timedelta(hours=2))
        payment_record = OrderPayment.objects.create(order=order_record, amount=Decimal(str(charge_amount)), status=PaymentStatus.FAILED, payment_reference=f"claim-{donation.donation_id}-{int(timezone.now().timestamp())}")

        maya_url = f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/customers/{user.maya_customer_id}/cards/{user.maya_card_id}/payments"
        maya_card_id = user.maya_card_id
        donor_name = f"{donation.donor.first_name} {donation.donor.last_name}".strip()
        donor_phone = donation.donor.contact_no
        tuab_name = f"{user.first_name} {user.last_name}".strip()
        tuab_phone = user.contact_no

    maya_payment_id = None
    try:
        maya_resp = requests.post(maya_url, json={'totalAmount': {'amount': charge_amount, 'currency': 'PHP'}, 'cardId': maya_card_id, 'requestReferenceNumber': payment_record.payment_reference}, headers={'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH, 'Content-Type': 'application/json', 'Accept': 'application/json'}, timeout=30)
        maya_json = maya_resp.json()
        if maya_resp.status_code == 200 and maya_json.get('status') == 'PAYMENT_SUCCESS':
            maya_payment_id = maya_json.get('id')
        else:
            _revert_failed_delivery_claim(donation_id=donation.pk, user_id=user.pk, order_id=order_record.pk)
            exc = APIException(f"Maya payment failed: {maya_json.get('message', maya_resp.text)}")
            exc.status_code = 502
            raise exc
    except APIException:
        raise
    except Exception as e:
        _revert_failed_delivery_claim(donation_id=donation.pk, user_id=user.pk, order_id=order_record.pk)
        exc = APIException(f"Maya connectivity error: {str(e)}")
        exc.status_code = 502
        raise exc

    l_payload = {"data": {"quotationId": lalamove_quotation_id, "sender": {"stopId": pickup_stop_id, "name": donor_name, "phone": donor_phone}, "recipients": [{"stopId": dropoff_stop_id, "name": tuab_name, "phone": tuab_phone}], "metadata": {"notes": "Fragile items"}}}
    l_ts, l_body = str(int(time.time() * 1000)), json.dumps(l_payload, separators=(',', ':'))
    l_sig = hmac.new(settings.LALAMOVE_API_SECRET.encode(), f"{l_ts}\r\nPOST\r\n/v3/orders\r\n\r\n{l_body}".encode(), hashlib.sha256).hexdigest()

    lalamove_success = False
    lalamove_error_msg = "Unknown logistics error"
    lalamove_order_id = None
    try:
        l_resp = requests.post("https://rest.sandbox.lalamove.com/v3/orders", data=l_body, headers={"Authorization": f"hmac {settings.LALAMOVE_API_KEY}:{l_ts}:{l_sig}", "Market": "PH", "Request-ID": str(uuid.uuid4()), "Content-Type": "application/json", "Accept": "application/json"}, timeout=30)
        if l_resp.status_code in [200, 201]:
            lalamove_order_id = l_resp.json().get("data", {}).get("orderId")
            lalamove_success = True
        else:
            lalamove_error_msg = l_resp.text
    except Exception as e:
        lalamove_error_msg = str(e)

    if not lalamove_success:
        void_success = False
        try:
            void_resp = requests.delete(
                f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/payments/{maya_payment_id}",
                json={"reason": "Automatic reversal due to logistics failure."},
                headers={'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH, 'Content-Type': 'application/json'},
                timeout=30
            )
            void_success = void_resp.status_code == 200
        except Exception:
            pass

        _revert_failed_delivery_claim(
            donation_id=donation.pk,
            user_id=user.pk,
            order_id=order_record.pk,
            payment_id=payment_record.pk,
            reversal_reference=f"void-{maya_payment_id}" if void_success else None,
        )
        exc = APIException(
            f"Delivery placement failed: {lalamove_error_msg}. " +
            ("Payment has been automatically reversed." if void_success else "Automatic payment reversal failed. Please contact support for a manual refund.")
        )
        exc.status_code = 502
        raise exc

    with transaction.atomic():
        donation = Donation.objects.select_for_update().get(pk=donation.pk)
        order_record = Order.objects.select_for_update().get(pk=order_record.pk)
        payment_record = OrderPayment.objects.select_for_update().get(pk=payment_record.pk)

        if donation.claimed_by_tuab_id != user.pk or donation.delivery_method != DonationDeliveryMethod.DELIVERY or order_record.status != OrderStatus.FAILED:
            exc = APIException("Donation claim could not be finalized because its state changed during delivery scheduling.")
            exc.status_code = 409
            raise exc

        order_record.lalamove_order_id = lalamove_order_id
        order_record.status = OrderStatus.ASSIGNING_DRIVER
        order_record.updated_at = timezone.now()
        order_record.save(update_fields=["lalamove_order_id", "status", "updated_at"])

        payment_record.payment_reference = maya_payment_id
        payment_record.status = PaymentStatus.SUCCESS
        payment_record.updated_at = timezone.now()
        payment_record.save(update_fields=["payment_reference", "status", "updated_at"])

        log_audit(user, 'donations', 'STATUS_CHANGE', ip_address, ['status', 'claimed_by_tuab', 'delivery_method'])

    return {"detail": "Donation successfully claimed and delivery scheduled.", "lalamove_order_id": lalamove_order_id}


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

        # Archive prediction records for the resolved donation only if items were modified
        if items_data is not None:
            try:
                run_predictions_for_donation(donation.donation_id)
            except Exception:
                pass  # Fail-safe to ensure resolution still completes even if prediction archiving errors out

    return {"detail": f"Donation successfully resolved as {validated_data['status'].lower()}."}


def unclaim_tuab_donations(*, tuab):
    with transaction.atomic():
        # Lock and load all donations claimed by this TUAB to prevent race conditions and deadlocks during unclaiming
        affected_donations = list(Donation.objects.select_for_update().filter(claimed_by_tuab=tuab).order_by('donation_id'))

        # Guard: Block archiving if any claimed delivery is currently in progress (CLAIMED or IN_TRANSIT with DELIVERY method)
        if any(donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT) and donation.delivery_method == DonationDeliveryMethod.DELIVERY for donation in affected_donations):
            return {
                "status_code": 409,
                "detail": "Archiving is not allowed while an associated delivery is in progress.",
                "changed_donations": [],
            }

        for donation in affected_donations:
            # Case 1: Claimed Pickup (safe to unclaim directly)
            if donation.status == DonationStatus.CLAIMED and donation.delivery_method == DonationDeliveryMethod.PICKUP:
                donation.claimed_by_tuab = None
                donation.delivery_method = None
                donation.status = DonationStatus.PENDING
                donation.updated_at = timezone.now()
                donation.save(update_fields=['claimed_by_tuab', 'delivery_method', 'status', 'updated_at'])

            # Case 2: In-Transit Pickup (self-pickup, safe to unclaim directly)
            elif donation.status == DonationStatus.IN_TRANSIT and donation.delivery_method == DonationDeliveryMethod.PICKUP:
                donation.claimed_by_tuab = None
                donation.delivery_method = None
                donation.status = DonationStatus.PENDING
                donation.updated_at = timezone.now()
                donation.save(update_fields=['claimed_by_tuab', 'delivery_method', 'status', 'updated_at'])

        return {
            "status_code": 204,
            "detail": None,
            "changed_donations": [donation for donation in affected_donations if donation.claimed_by_tuab is None],
        }


def archive_donor_donations(*, donor):
    with transaction.atomic():
        # Lock and load all donations owned by this Donor to prevent concurrency issues during archiving
        affected_donations = list(Donation.objects.select_for_update().filter(donor=donor).order_by('donation_id'))

        # Guard: Block archiving if any owned delivery is currently in progress (CLAIMED or IN_TRANSIT with DELIVERY method)
        if any(donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT) and donation.delivery_method == DonationDeliveryMethod.DELIVERY for donation in affected_donations):
            return {
                "status_code": 409,
                "detail": "Archiving is not allowed while an associated delivery is in progress.",
                "changed_donations": [],
            }

        for donation in affected_donations:
            # Case 1: Pending Donation (safe to archive directly)
            if donation.status == DonationStatus.PENDING:
                donation.status = DonationStatus.ARCHIVED
                donation.updated_at = timezone.now()
                donation.save(update_fields=['status', 'updated_at'])

            # Case 2: Claimed or In-Transit Pickup Donation (pickup method, safe to archive directly)
            elif (
                donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT)
                and donation.delivery_method == DonationDeliveryMethod.PICKUP
            ):
                donation.status = DonationStatus.ARCHIVED
                donation.updated_at = timezone.now()
                donation.save(update_fields=['status', 'updated_at'])

        return {
            "status_code": 204,
            "detail": None,
            "changed_donations": [donation for donation in affected_donations if donation.status == DonationStatus.ARCHIVED],
        }

