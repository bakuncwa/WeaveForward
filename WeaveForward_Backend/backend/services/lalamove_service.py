import hmac
import hashlib
import json
import time
import uuid
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .audit_service import log_audit
from ..models import Order, OrderStatus, DonationStatus, OrderPayment, PaymentStatus, DonationDeliveryMethod

def get_lalamove_quotation(pickup_lat, pickup_lng, pickup_address, dropoff_lat, dropoff_lng, dropoff_address, schedule_at):
    """
    Fetches a delivery quotation from Lalamove API.
    """
    api_key = settings.LALAMOVE_API_KEY
    api_secret = settings.LALAMOVE_API_SECRET
    base_url = "https://rest.sandbox.lalamove.com"
    path = "/v3/quotations"
    
    # Ensure coordinates are formatted to 7 decimal places as requested
    formatted_pickup_lat = "{:.7f}".format(float(pickup_lat))
    formatted_pickup_lng = "{:.7f}".format(float(pickup_lng))
    formatted_dropoff_lat = "{:.7f}".format(float(dropoff_lat))
    formatted_dropoff_lng = "{:.7f}".format(float(dropoff_lng))

    data = {
        "data": {
            "scheduleAt": schedule_at,
            "serviceType": "SEDAN",
            "language": "en_PH",
            "stops": [
                {
                    "coordinates": {
                        "lat": formatted_pickup_lat,
                        "lng": formatted_pickup_lng
                    },
                    "address": pickup_address
                },
                {
                    "coordinates": {
                        "lat": formatted_dropoff_lat,
                        "lng": formatted_dropoff_lng
                    },
                    "address": dropoff_address
                }
            ]
        }
    }
    
    timestamp = str(int(time.time() * 1000))
    method = "POST"
    # Using separators=(',', ':') to match CryptoJS behavior (no extra spaces)
    body = json.dumps(data, separators=(',', ':'))
    
    signature_payload = f"{timestamp}\r\n{method}\r\n{path}\r\n\r\n{body}"
    signature = hmac.new(
        api_secret.encode('utf-8'),
        signature_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "Authorization": f"hmac {api_key}:{timestamp}:{signature}",
        "Market": "PH",
        "Request-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    response = requests.post(f"{base_url}{path}", headers=headers, data=body)
    
    if response.status_code != 201 and response.status_code != 200:
        return {"error": response.json(), "status_code": response.status_code}
        
    return response.json()


def reverse_or_refund_payment(payment_record, amount):
    """
    Attempts to Void (DELETE) first. If it is already settled (different day),
    automatically falls back to a Refund (POST).
    """
    headers = {
        'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
        'Content-Type': 'application/json'
    }
    
    # 1. Try Voiding (DELETE)
    void_url = f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/payments/{payment_record.payment_reference}"
    try:
        void_resp = requests.delete(void_url, json={"reason": "Delivery failure reversal."}, headers=headers, timeout=30)
        if void_resp.status_code == 200:
            print(f"[PAYMENT] Successfully VOIDED payment: {payment_record.payment_reference}", flush=True)
            payment_record.status = PaymentStatus.FAILED
            payment_record.updated_at = timezone.now()
            payment_record.save(update_fields=["status", "updated_at"])
            return True
        else:
            print(f"[PAYMENT] Void failed with status {void_resp.status_code}: {void_resp.text}. Proceeding to Refund...", flush=True)
    except Exception as e:
        print(f"[PAYMENT] Void connectivity error: {str(e)}. Proceeding to Refund...", flush=True)

    # 2. Try Refund Fallback (POST /refunds)
    refund_url = f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/payments/{payment_record.payment_reference}/refunds"
    refund_payload = {
        "totalAmount": {
            "amount": float(amount),
            "currency": "PHP"
        },
        "reason": "Delivery failure refund."
    }
    try:
        refund_resp = requests.post(refund_url, json=refund_payload, headers=headers, timeout=30)
        if refund_resp.status_code in [200, 201]:
            print(f"[PAYMENT] Successfully REFUNDED payment: {payment_record.payment_reference}", flush=True)
            payment_record.status = PaymentStatus.FAILED
            payment_record.updated_at = timezone.now()
            payment_record.save(update_fields=["status", "updated_at"])
            return True
        else:
            print(f"[PAYMENT] Refund failed: {refund_resp.text}", flush=True)
    except Exception as e:
        print(f"[PAYMENT] Refund connectivity error: {str(e)}", flush=True)

    return False


def process_lalamove_webhook(payload, client_ip):
    if not (payload.get("signature") and payload.get("timestamp") and payload.get("data")):
        print("[LALAMOVE WEBHOOK] [REJECTED] Rejecting: Missing signature, timestamp, or data.", flush=True)
        return {"status_code": 400, "detail": "Missing signature verification details."}

    signature, timestamp, data_obj = payload["signature"], payload["timestamp"], payload["data"]

    message = f"{timestamp}\r\nPOST\r\n/api/webhooks\r\n\r\n{json.dumps(data_obj, separators=(',', ':'))}"
    calculated_signature = hmac.new(settings.LALAMOVE_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_signature, signature):
        print(f"[LALAMOVE WEBHOOK] [UNAUTHORIZED] Signature mismatch. Calculated: {calculated_signature}, Provided: {signature}", flush=True)
        return {"status_code": 401, "detail": "Invalid Lalamove webhook signature."}

    if payload.get("eventType") != "ORDER_STATUS_CHANGED":
        return {"status_code": 200, "detail": f"Webhook event type {payload.get('eventType')} ignored."}

    order_data = data_obj.get("order", {})
    lalamove_order_id, status, previous_status = order_data.get("orderId"), order_data.get("status"), order_data.get("previousStatus")

    if not lalamove_order_id:
        print("[LALAMOVE WEBHOOK] [REJECTED] Missing orderId in payload order details.", flush=True)
        return {"status_code": 400, "detail": "Missing orderId in Lalamove webhook payload."}

    print(f"[LALAMOVE WEBHOOK] [TRANSITION] Context: {previous_status} -> {status}", flush=True)

    with transaction.atomic():
        try:
            order_record = Order.objects.select_for_update().get(lalamove_order_id=lalamove_order_id)
        except Order.DoesNotExist:
            print(f"[LALAMOVE WEBHOOK] [ERROR] Order not found: lalamove_order_id {lalamove_order_id}", flush=True)
            return {"status_code": 404, "detail": f"Order with lalamove_order_id {lalamove_order_id} not found."}

        # =========================================================================
        # LALAMOVE STATUS TRANSITIONS
        # =========================================================================

        # "" -> "ASSIGNING_DRIVER"
        if previous_status == "" and status == "ASSIGNING_DRIVER":
            print("[LALAMOVE WEBHOOK] [INFO] No action required: order already at ASSIGNING_DRIVER.", flush=True)
            return {"status_code": 200, "detail": "Order status is already ASSIGNING_DRIVER. No status update required."}

        # "ASSIGNING_DRIVER" -> "ON_GOING"
        if previous_status == "ASSIGNING_DRIVER" and status == "ON_GOING":
            print("[LALAMOVE WEBHOOK] [TRANSITION] ASSIGNING_DRIVER -> ON_GOING. Updating order status.", flush=True)
            order_record.status = OrderStatus.ON_GOING
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])
            return {"status_code": 200, "detail": "Order status updated to ON_GOING successfully."}

        # "ON_GOING" -> "PICKED_UP"
        if previous_status == "ON_GOING" and status == "PICKED_UP":
            print("[LALAMOVE WEBHOOK] [TRANSITION] ON_GOING -> PICKED_UP. Updating order status to PICKED_UP and donation status to IN_TRANSIT.", flush=True)
            order_record.status = OrderStatus.PICKED_UP
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])

            donation_record = order_record.donation
            if donation_record.claimed_by_tuab:
                log_audit(
                    actor=donation_record.claimed_by_tuab,
                    entity_type="donations",
                    action="STATUS_CHANGE",
                    ip_address=client_ip,
                    fields_modified=["status"]
                )
            donation_record.status = DonationStatus.IN_TRANSIT
            donation_record.updated_at = timezone.now()
            donation_record.save(update_fields=["status", "updated_at"])
            return {"status_code": 200, "detail": "Order status updated to PICKED_UP and donation updated to IN_TRANSIT successfully."}

        # "PICKED_UP" -> "COMPLETED"
        if previous_status == "PICKED_UP" and status == "COMPLETED":
            print("[LALAMOVE WEBHOOK] [TRANSITION] PICKED_UP -> COMPLETED. Updating order status to COMPLETED.", flush=True)
            order_record.status = OrderStatus.COMPLETED
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])
            return {"status_code": 200, "detail": "Order status updated to COMPLETED successfully."}

        # "ON_GOING" -> "ASSIGNING_DRIVER" (Driver Rejected / Reassigning)
        if previous_status == "ON_GOING" and status == "ASSIGNING_DRIVER":
            if order_record.no_reassigned >= 1:
                print(f"[LALAMOVE WEBHOOK] [WARNING] Max driver reassignments reached ({order_record.no_reassigned}). Failing order, reversing payment, and converting donation to PICKUP.", flush=True)
                order_record.status = OrderStatus.FAILED
                order_record.no_reassigned = 2
                order_record.updated_at = timezone.now()
                order_record.save(update_fields=["status", "no_reassigned", "updated_at"])

                donation_record = order_record.donation
                if donation_record.claimed_by_tuab:
                    log_audit(
                        actor=donation_record.claimed_by_tuab,
                        entity_type="donations",
                        action="STATUS_CHANGE",
                        ip_address=client_ip,
                        fields_modified=["status", "delivery_method"]
                    )
                donation_record.status = DonationStatus.CLAIMED
                donation_record.delivery_method = DonationDeliveryMethod.PICKUP
                donation_record.updated_at = timezone.now()
                donation_record.save(update_fields=["status", "delivery_method", "updated_at"])

                payment_record = order_record.payments.filter(status=PaymentStatus.SUCCESS).first()
                if payment_record and payment_record.payment_reference:
                    reverse_or_refund_payment(payment_record, payment_record.amount)

                return {"status_code": 200, "detail": "Order failed due to max driver rejections. Payment reversed/refunded, donation converted to PICKUP."}
            else:
                print(f"[LALAMOVE WEBHOOK] [TRANSITION] Driver rejected. Reassignment count incrementing from {order_record.no_reassigned} to {order_record.no_reassigned + 1}.", flush=True)
                order_record.status = OrderStatus.ASSIGNING_DRIVER
                order_record.no_reassigned += 1
                order_record.updated_at = timezone.now()
                order_record.save(update_fields=["status", "no_reassigned", "updated_at"])
                return {"status_code": 200, "detail": "Order status reverted to ASSIGNING_DRIVER and reassignment count incremented."}

        # Any -> "EXPIRED"
        if status == "EXPIRED":
            print(f"[LALAMOVE WEBHOOK] [WARNING] Order EXPIRED. Failing order, reversing payment, and converting donation to PICKUP.", flush=True)
            order_record.status = OrderStatus.FAILED
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])

            donation_record = order_record.donation
            if donation_record.claimed_by_tuab:
                log_audit(
                    actor=donation_record.claimed_by_tuab,
                    entity_type="donations",
                    action="STATUS_CHANGE",
                    ip_address=client_ip,
                    fields_modified=["status", "delivery_method"]
                )
            donation_record.status = DonationStatus.CLAIMED
            donation_record.delivery_method = DonationDeliveryMethod.PICKUP
            donation_record.updated_at = timezone.now()
            donation_record.save(update_fields=["status", "delivery_method", "updated_at"])

            payment_record = order_record.payments.filter(status=PaymentStatus.SUCCESS).first()
            if payment_record and payment_record.payment_reference:
                reverse_or_refund_payment(payment_record, payment_record.amount)

            return {"status_code": 200, "detail": "Order expired and failed. Payment reversed/refunded, donation converted to PICKUP."}

        print(f"[LALAMOVE WEBHOOK] [WARNING] Unhandled state transition: {previous_status} -> {status}", flush=True)

    return {"status_code": 200, "detail": "Lalamove webhook signature verified successfully."}


