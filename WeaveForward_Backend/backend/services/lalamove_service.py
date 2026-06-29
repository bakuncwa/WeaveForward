import hmac
import hashlib
import json
import time
import uuid
import requests
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .audit_service import log_audit
from ..models import User, UserRole, Donation, Order, OrderStatus, DonationStatus, OrderPayment, PaymentStatus, DonationDeliveryMethod


SUBSCRIPTION_COVERED_PAYMENT_PREFIX = "subscription-covered-"


def get_lalamove_quotation(pickup_lat, pickup_lng, pickup_address, dropoff_lat, dropoff_lng, dropoff_address, schedule_at):
    """
    Fetches a delivery quotation from Lalamove API.
    """
    api_key = settings.LALAMOVE_API_KEY
    api_secret = settings.LALAMOVE_API_SECRET
    base_url = settings.LALAMOVE_BASE_URL
    path = "/v3/quotations"
    
    # Ensure coordinates are formatted to 7 decimal places as requested
    formatted_pickup_lat = "{:.7f}".format(float(pickup_lat))
    formatted_pickup_lng = "{:.7f}".format(float(pickup_lng))
    formatted_dropoff_lat = "{:.7f}".format(float(dropoff_lat))
    formatted_dropoff_lng = "{:.7f}".format(float(dropoff_lng))

    data = {
        "data": {
            "scheduleAt": schedule_at,
            "serviceType": "MOTORCYCLE",
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
        try:
            err = response.json()
        except ValueError:
            err = "Lalamove request failed."
        return {"error": err, "status_code": response.status_code}
        
    return response.json()


def reverse_or_refund_payment(payment_record, amount):
    """
    Attempts to Void (DELETE) first. If it is already settled (different day),
    automatically falls back to a Refund (POST).
    """
    if not payment_record.payment_reference or payment_record.payment_reference.startswith(SUBSCRIPTION_COVERED_PAYMENT_PREFIX) or amount <= 0:
        return False

    headers = {
        'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
        'Content-Type': 'application/json'
    }
    
    # 1. Try Voiding (DELETE)
    void_url = f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/payments/{payment_record.payment_reference}"
    try:
        void_resp = requests.delete(void_url, json={"reason": "Delivery failure reversal."}, headers=headers, timeout=30)
        if void_resp.status_code == 200:
            # Create a new reversal/refund payment record with a negative amount
            OrderPayment.objects.create(
                order=payment_record.order,
                amount=-payment_record.amount,
                status=PaymentStatus.SUCCESS,
                payment_reference=f"void-{payment_record.payment_reference}"
            )
            return True
        else:
            pass
    except Exception as e:
        pass

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
            # Create a new reversal/refund payment record with a negative amount
            OrderPayment.objects.create(
                order=payment_record.order,
                amount=-payment_record.amount,
                status=PaymentStatus.SUCCESS,
                payment_reference=f"refund-{payment_record.payment_reference}"
            )
            return True
        else:
            pass
    except Exception as e:
        pass

    return False


def process_lalamove_webhook(payload, client_ip):
    if not payload:
        return {"status_code": 200, "detail": "Lalamove webhook URL verified successfully."}

    if not (payload.get("signature") and payload.get("timestamp") and payload.get("data")):
        return {"status_code": 400, "detail": "Missing signature verification details."}

    signature, timestamp, data_obj = payload["signature"], payload["timestamp"], payload["data"]

    message = f"{timestamp}\r\nPOST\r\n/api/webhooks\r\n\r\n{json.dumps(data_obj, separators=(',', ':'))}"
    calculated_signature = hmac.new(settings.LALAMOVE_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_signature, signature):
        return {"status_code": 401, "detail": "Invalid Lalamove webhook signature."}

    if payload.get("eventType") == "ORDER_AMOUNT_CHANGED":
        # Per-order delivery charges are covered by the active PRO subscription.
        return {"status_code": 200, "detail": "Order amount change acknowledged; no individual delivery charge applied."}

        # Individual order charge path disabled while PRO subscription covers delivery.
        order_data = data_obj["order"]
        with transaction.atomic():
            try:
                order_record = Order.objects.select_for_update().get(lalamove_order_id=order_data["orderId"])
            except Order.DoesNotExist:
                return {"status_code": 200, "detail": f"Order with lalamove_order_id {order_data.get('orderId')} not found; webhook acknowledged."}
            total_price = Decimal(str(order_data["price"]["totalPrice"]))
            paid_amount = sum((p.amount for p in order_record.payments.filter(status=PaymentStatus.SUCCESS)), Decimal("0.00"))
            amount = total_price - paid_amount
            if amount <= 0:
                return {"status_code": 200, "detail": "Order amount change did not require an additional charge."}
            tuab = order_record.donation.claimed_by_tuab
            if not tuab or not tuab.maya_customer_id or not tuab.maya_card_id:
                return {"status_code": 200, "detail": "Order amount change could not be charged because the TUAB has no valid payment method."}
            reference = f"edit-{order_record.order_id}-{int(timezone.now().timestamp())}"[:36]
            payment = OrderPayment.objects.create(order=order_record, amount=amount, status=PaymentStatus.FAILED, payment_reference=reference)
            maya_url = f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/customers/{tuab.maya_customer_id}/cards/{tuab.maya_card_id}/payments"
            maya_payload = {"totalAmount": {"amount": float(amount), "currency": "PHP"}, "cardId": tuab.maya_card_id, "requestReferenceNumber": reference}

        response = requests.post(
            maya_url,
            json=maya_payload,
            headers={"Authorization": settings.MAYA_SANDBOX_SECRET_BASIC_AUTH, "Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )
        response_json = response.json()
        if response.status_code == 200 and response_json.get("status") == "PAYMENT_SUCCESS":
            with transaction.atomic():
                payment = OrderPayment.objects.select_for_update().get(pk=payment.pk)
                order_record = Order.objects.select_for_update().get(pk=order_record.pk)
                if payment.status != PaymentStatus.FAILED or order_record.lalamove_order_id != order_data["orderId"]:
                    return {"status_code": 409, "detail": "Order amount change could not be finalized because the order state changed during payment."}
                payment.status = PaymentStatus.SUCCESS
                payment.payment_reference = response_json.get("id")
                payment.save(update_fields=["status", "payment_reference", "updated_at"])
            return {"status_code": 200, "detail": "Order amount change charged successfully."}
        return {"status_code": 502, "detail": f"Maya payment failed: {response_json.get('message') or response_json.get('error') or 'Payment could not be completed.'}"}

    if payload.get("eventType") != "ORDER_STATUS_CHANGED":
        return {"status_code": 200, "detail": f"Webhook event type {payload.get('eventType')} ignored."}

    order_data = data_obj.get("order", {})
    lalamove_order_id, status, previous_status = order_data.get("orderId"), order_data.get("status"), order_data.get("previousStatus")

    if not lalamove_order_id:
        return {"status_code": 400, "detail": "Missing orderId in Lalamove webhook payload."}

    payment_ids_to_refund = []
    webhook_response = None

    with transaction.atomic():
        try:
            order_record = Order.objects.select_for_update().get(lalamove_order_id=lalamove_order_id)
        except Order.DoesNotExist:
            return {"status_code": 200, "detail": f"Order with lalamove_order_id {lalamove_order_id} not found; webhook acknowledged."}



        # =========================================================================
        # LALAMOVE STATUS TRANSITIONS
        # =========================================================================

        # "" -> "ASSIGNING_DRIVER"
        if previous_status == "" and status == "ASSIGNING_DRIVER":
            return {"status_code": 200, "detail": "Order status is already ASSIGNING_DRIVER. No status update required."}

        # "ASSIGNING_DRIVER" (or "") -> "ON_GOING"
        if previous_status in ["ASSIGNING_DRIVER", ""] and status == "ON_GOING":
            order_record.status = OrderStatus.ON_GOING
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])

            donation_record = order_record.donation
            donation_record.updated_at = timezone.now()
            donation_record.save(update_fields=["updated_at"])
            return {"status_code": 200, "detail": "Order status updated to ON_GOING successfully."}

        # "ON_GOING" -> "PICKED_UP"
        if previous_status in ["ON_GOING", ""] and status == "PICKED_UP":
            order_record.status = OrderStatus.PICKED_UP
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])

            donation_record = order_record.donation
            if donation_record.status not in [DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT]:
                return {"status_code": 200, "detail": "Order status updated to PICKED_UP. Donation status was left unchanged."}
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
        if previous_status in ["PICKED_UP", ""] and status == "COMPLETED":
            order_record.status = OrderStatus.COMPLETED
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])

            donation_record = order_record.donation
            donation_record.updated_at = timezone.now()
            donation_record.save(update_fields=["updated_at"])
            return {"status_code": 200, "detail": "Order status updated to COMPLETED successfully."}

        # "ON_GOING" -> "ASSIGNING_DRIVER" (Driver Rejected / Reassigning)
        if previous_status == "ON_GOING" and status == "ASSIGNING_DRIVER":
            if order_record.no_reassigned >= 1:
                order_record.status = OrderStatus.FAILED
                order_record.no_reassigned = 2
                order_record.updated_at = timezone.now()
                order_record.save(update_fields=["status", "no_reassigned", "updated_at"])

                donation_record = order_record.donation
                if donation_record.status not in [DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT]:
                    return {"status_code": 200, "detail": "Order failed due to max driver rejections. Donation status was left unchanged."}
                admin_user = User.objects.filter(role=UserRole.ADMIN).first()
                if admin_user:
                    log_audit(
                        actor=admin_user,
                        entity_type="donations",
                        action="STATUS_CHANGE",
                        ip_address=client_ip,
                        fields_modified=["status", "delivery_method"]
                    )
                donation_record.status = DonationStatus.CLAIMED
                donation_record.delivery_method = DonationDeliveryMethod.PICKUP
                donation_record.updated_at = timezone.now()
                donation_record.save(update_fields=["status", "delivery_method", "updated_at"])
                payment_ids_to_refund = []
                webhook_response = {"status_code": 200, "detail": "Order failed due to max driver rejections. Donation converted to PICKUP."}
            else:
                order_record.status = OrderStatus.ASSIGNING_DRIVER
                order_record.no_reassigned += 1
                order_record.updated_at = timezone.now()
                order_record.save(update_fields=["status", "no_reassigned", "updated_at"])

                donation_record = order_record.donation
                donation_record.updated_at = timezone.now()
                donation_record.save(update_fields=["updated_at"])
                return {"status_code": 200, "detail": "Order status reverted to ASSIGNING_DRIVER and reassignment count incremented."}

        # Any -> "EXPIRED"
        if status == "EXPIRED":
            order_record.status = OrderStatus.FAILED
            order_record.updated_at = timezone.now()
            order_record.save(update_fields=["status", "updated_at"])

            donation_record = order_record.donation
            if donation_record.status not in [DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT]:
                return {"status_code": 200, "detail": "Order expired and failed. Donation status was left unchanged."}
            admin_user = User.objects.filter(role=UserRole.ADMIN).first()
            if admin_user:
                log_audit(
                    actor=admin_user,
                    entity_type="donations",
                    action="STATUS_CHANGE",
                    ip_address=client_ip,
                    fields_modified=["status", "delivery_method"]
                )
            donation_record.status = DonationStatus.CLAIMED
            donation_record.delivery_method = DonationDeliveryMethod.PICKUP
            donation_record.updated_at = timezone.now()
            donation_record.save(update_fields=["status", "delivery_method", "updated_at"])

            payment_ids_to_refund = []
            webhook_response = {"status_code": 200, "detail": "Order expired and failed. Donation converted to PICKUP."}

    if webhook_response:
        for payment_record in OrderPayment.objects.filter(pk__in=payment_ids_to_refund):
            reverse_or_refund_payment(payment_record, payment_record.amount)
        return webhook_response

    return {"status_code": 200, "detail": "Lalamove webhook signature verified successfully."}


def cancel_lalamove_order(lalamove_order_id):
    # Lalamove credentials from settings
    api_key = settings.LALAMOVE_API_KEY
    api_secret = settings.LALAMOVE_API_SECRET
    base_url = settings.LALAMOVE_BASE_URL
    path = f"/v3/orders/{lalamove_order_id}"
    # DELETE request body must be empty string
    body = ""
    timestamp = str(int(time.time() * 1000))
    method = "DELETE"
    # Construct signature payload
    signature_payload = f"{timestamp}\r\n{method}\r\n{path}\r\n\r\n{body}"
    signature = hmac.new(
        api_secret.encode('utf-8'),
        signature_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    # Construct required headers
    headers = {
        "Authorization": f"hmac {api_key}:{timestamp}:{signature}",
        "Market": "PH",
        "Request-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    # Invoke DELETE request to cancel order
    response = requests.delete(f"{base_url}{path}", headers=headers)
    # If API does not return success, return error dictionary
    if response.status_code not in [200, 204]:
        return {"error": "Failed to cancel delivery order. Please contact the Logistics Provider for assistance.", "status_code": response.status_code}
    # Return success status code
    return {"status_code": response.status_code}


def update_lalamove_order(
    lalamove_order_id,
    pickup_lat,
    pickup_lng,
    pickup_address,
    dropoff_lat,
    dropoff_lng,
    dropoff_address,
    pickup_name=None,
    pickup_phone=None,
    dropoff_name=None,
    dropoff_phone=None,
):
    api_key = settings.LALAMOVE_API_KEY
    api_secret = settings.LALAMOVE_API_SECRET
    base_url = settings.LALAMOVE_BASE_URL
    path = f"/v3/orders/{lalamove_order_id}"

    formatted_pickup_lat = "{:.7f}".format(float(pickup_lat))
    formatted_pickup_lng = "{:.7f}".format(float(pickup_lng))
    formatted_dropoff_lat = "{:.7f}".format(float(dropoff_lat))
    formatted_dropoff_lng = "{:.7f}".format(float(dropoff_lng))

    data = {
        "data": {
            "stops": [
                {
                    "coordinates": {
                        "lat": formatted_pickup_lat,
                        "lng": formatted_pickup_lng
                    },
                    "address": pickup_address,
                    "name": pickup_name or "",
                    "phone": pickup_phone or "",
                },
                {
                    "coordinates": {
                        "lat": formatted_dropoff_lat,
                        "lng": formatted_dropoff_lng
                    },
                    "address": dropoff_address,
                    "name": dropoff_name or "",
                    "phone": dropoff_phone or "",
                }
            ]
        }
    }

    timestamp = str(int(time.time() * 1000))
    method = "PATCH"
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

    response = requests.patch(f"{base_url}{path}", headers=headers, data=body)
    if response.status_code not in [200, 201, 204]:
        return {"error": "Failed to update delivery order. Please contact the Logistics Provider for assistance.", "status_code": response.status_code}
    return response.json() if response.status_code in [200, 201] else {"status_code": response.status_code}


def get_lalamove_order_driver(lalamove_order_id):
    api_key = settings.LALAMOVE_API_KEY
    api_secret = settings.LALAMOVE_API_SECRET
    base_url = settings.LALAMOVE_BASE_URL
    path = f"/v3/orders/{lalamove_order_id}"

    timestamp = str(int(time.time() * 1000))
    method = "GET"
    body = ""

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

    response = requests.get(f"{base_url}{path}", headers=headers)

    if response.status_code != 200:
        try:
            err = response.json()
        except ValueError:
            err = "Failed to retrieve order details."
        return {"error": err, "status_code": response.status_code}

    return response.json()


def get_lalamove_driver_details(lalamove_order_id, driver_id):
    api_key = settings.LALAMOVE_API_KEY
    api_secret = settings.LALAMOVE_API_SECRET
    base_url = settings.LALAMOVE_BASE_URL
    path = f"/v3/orders/{lalamove_order_id}/drivers/{driver_id}"

    timestamp = str(int(time.time() * 1000))
    method = "GET"
    body = ""

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

    response = requests.get(f"{base_url}{path}", headers=headers)

    if response.status_code != 200:
        try:
            err = response.json()
        except ValueError:
            err = "Failed to retrieve driver details."
        return {"error": err, "status_code": response.status_code}

    return response.json()


def process_expired_orders():
    """
    Finds all active/pending orders that are past their expires_at date
    and transitions them to FAILED, reverts the associated donation to PICKUP,
    and refunds the payment.
    """
    payment_ids_to_refund = []

    with transaction.atomic():
        now = timezone.now()
        expired_orders = Order.objects.select_for_update().filter(
            expires_at__lte=now
        ).exclude(
            status__in=[OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.FAILED]
        )

        expired_count = 0
        for order in expired_orders:
            # 1. Fail the order locally
            order.status = OrderStatus.FAILED
            order.updated_at = now
            order.save(update_fields=["status", "updated_at"])

            # 2. Revert the donation to CLAIMED with PICKUP delivery method
            donation = Donation.objects.select_for_update().get(pk=order.donation_id)
            donation.status = DonationStatus.CLAIMED
            donation.delivery_method = DonationDeliveryMethod.PICKUP
            donation.updated_at = now
            donation.save(update_fields=["status", "delivery_method", "updated_at"])

            # Log audit trail
            actor = User.objects.filter(role=UserRole.ADMIN).first()
            if actor:
                log_audit(
                    actor=actor,
                    entity_type="donations",
                    action="STATUS_CHANGE",
                    ip_address=None,
                    fields_modified=["status", "delivery_method"]
                )

            # 3. Refund the payment if it was successful
            payment_ids_to_refund.extend(
                order.payments
                .filter(status=PaymentStatus.SUCCESS, amount__gt=0)
                .exclude(payment_reference__startswith=SUBSCRIPTION_COVERED_PAYMENT_PREFIX)
                .values_list("pk", flat=True)
            )

            expired_count += 1

    for payment in OrderPayment.objects.filter(pk__in=payment_ids_to_refund):
        reverse_or_refund_payment(payment, payment.amount)

    return expired_count






