# Django transaction and timezone imports
from django.db import transaction
from django.utils import timezone

# DRF APIException classes for automatic REST response handling
from rest_framework.exceptions import APIException, PermissionDenied, NotFound

# Models and service helpers
from ..models import Donation, DonationStatus, Order, OrderStatus, PaymentStatus, DonationDeliveryMethod
from .audit_service import log_audit
from .lalamove_service import cancel_lalamove_order, reverse_or_refund_payment





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
                    exc = APIException(f"Lalamove cancellation failed. We were unable to cancel the delivery at this time. Please try again. Error detail: {lalamove_res['error']}")
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
                exc = APIException(f"This donation cannot be cancelled because its current status is {donation.status.lower()}.")
                exc.status_code = 409
                raise exc
