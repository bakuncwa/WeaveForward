import requests
import json
import hmac
import hashlib
import time
import uuid
import base64
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.utils.dateparse import parse_datetime
from ..models import Donation, Order, OrderPayment, OrderStatus, PaymentStatus, DonationStatus, User, DonationDeliveryMethod
from .audit_service import log_audit

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
    Orchestrates the donation claiming process.
    
    This function manages the atomicity of the claim process, including:
    1. Cryptographic token verification for delivery quotations.
    2. Maya payment processing.
    3. Lalamove delivery order creation.
    4. Automatic transaction reversal (Void) if downstream logistics fail.
    """
    delivery_method = claim_params.get('delivery_method')
    
    with transaction.atomic():
        # 0. Concurrency Control: Lock records and verify availability
        donation = Donation.objects.select_for_update().get(pk=donation.pk)
        user = User.objects.select_for_update().get(pk=user.pk)
        
        if donation.status != DonationStatus.PENDING:
            return {"status_code": 409, "detail": "Donation is no longer available."}

        if Donation.objects.filter(claimed_by_tuab=user, status__in=[DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT]).count() >= user.max_active_claims:
            return {"status_code": 409, "detail": "Active claim limit reached."}

        # --- PICKUP WORKFLOW ---
        if delivery_method == 'PICKUP':
            donation.status, donation.claimed_by_tuab, donation.delivery_method = DonationStatus.CLAIMED, user, DonationDeliveryMethod.PICKUP
            donation.save()
            log_audit(user, 'donations', 'STATUS_CHANGE', ip_address, ['status', 'claimed_by_tuab', 'delivery_method'])
            return {"status_code": 200, "detail": "Donation successfully claimed for pickup."}

        # --- DELIVERY WORKFLOW ---
        quotation_token = claim_params.get('quotation_token')
        try:
            # Verify cryptographic integrity and expiry
            data_b64, token_signature = quotation_token.split('.')
            if not hmac.compare_digest(hmac.new(settings.SECRET_KEY.encode(), data_b64.encode(), hashlib.sha256).hexdigest(), token_signature):
                return {"status_code": 400, "detail": "Invalid quotation signature."}
            
            token_data = json.loads(base64.urlsafe_b64decode(data_b64 + '=' * (4 - len(data_b64) % 4)).decode())
            if token_data.get('expires_at', 0) < int(time.time()):
                return {"status_code": 400, "detail": "Quotation has expired."}
            
            charge_amount, lalamove_quotation_id, pickup_stop_id, dropoff_stop_id, sch_str = float(token_data['amount']), token_data['quotationId'], token_data['stopId_1'], token_data['stopId_2'], token_data.get('schedule_at')
            order_scheduled_at = parse_datetime(sch_str) if sch_str else timezone.now()
        except Exception:
            return {"status_code": 400, "detail": "Malformed or expired quotation token."}

        if not all([user.maya_customer_id, user.maya_card_id]):
            return {"status_code": 400, "detail": "Payment details are not configured for this user."}

        # B. Robust Record Management: Pre-create records to ensure traceability during failures
        maya_reference = f"claim-{donation.donation_id}-{int(timezone.now().timestamp())}"
        order_expires_at = order_scheduled_at + timedelta(hours=2)
        order_record = Order.objects.create(donation=donation, status=OrderStatus.FAILED, dropoff_display_address=user.display_address or "N/A", dropoff_latitude=user.latitude or 0, dropoff_longitude=user.longitude or 0, scheduled_at=order_scheduled_at, expires_at=order_expires_at)
        payment_record = OrderPayment.objects.create(order=order_record, amount=Decimal(str(charge_amount)), status=PaymentStatus.FAILED, payment_reference=maya_reference)

        # C. Payment Integration: Maya Vault Charge
        maya_url = f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/customers/{user.maya_customer_id}/cards/{user.maya_card_id}/payments"
        try:
            maya_resp = requests.post(maya_url, json={'totalAmount': {'amount': charge_amount, 'currency': 'PHP'}, 'cardId': user.maya_card_id, 'requestReferenceNumber': maya_reference[:36]}, headers={'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH, 'Content-Type': 'application/json', 'Accept': 'application/json'}, timeout=30)
            maya_json = maya_resp.json()
            if maya_resp.status_code == 200 and maya_json.get('status') == 'PAYMENT_SUCCESS':
                maya_payment_id = maya_json.get('id')
                payment_record.status = PaymentStatus.SUCCESS
                payment_record.save()
            else:
                return {"status_code": 502, "detail": f"Maya payment failed: {maya_json.get('message', maya_resp.text)}"}
        except Exception as e:
            return {"status_code": 502, "detail": f"Maya connectivity error: {str(e)}"}

        # D. Logistics Integration: Lalamove Order Creation
        l_payload = {"data": {"quotationId": lalamove_quotation_id, "sender": {"stopId": pickup_stop_id, "name": f"{donation.donor.first_name} {donation.donor.last_name}".strip(), "phone": donation.donor.contact_no}, "recipients": [{"stopId": dropoff_stop_id, "name": f"{user.first_name} {user.last_name}".strip(), "phone": user.contact_no}], "metadata": {"notes": "Fragile items"}}}
        l_ts, l_body = str(int(time.time() * 1000)), json.dumps(l_payload, separators=(',', ':'))
        l_sig = hmac.new(settings.LALAMOVE_API_SECRET.encode(), f"{l_ts}\r\nPOST\r\n/v3/orders\r\n\r\n{l_body}".encode(), hashlib.sha256).hexdigest()
        
        lalamove_success = False
        lalamove_error_msg = "Unknown logistics error"
        try:
            l_resp = requests.post("https://rest.sandbox.lalamove.com/v3/orders", data=l_body, headers={"Authorization": f"hmac {settings.LALAMOVE_API_KEY}:{l_ts}:{l_sig}", "Market": "PH", "Request-ID": str(uuid.uuid4()), "Content-Type": "application/json", "Accept": "application/json"}, timeout=30)
            if l_resp.status_code in [200, 201]:
                order_record.lalamove_order_id, order_record.status = l_resp.json().get("data", {}).get("orderId"), OrderStatus.ASSIGNING_DRIVER
                order_record.save()
                donation.status, donation.claimed_by_tuab, donation.delivery_method = DonationStatus.CLAIMED, user, DonationDeliveryMethod.DELIVERY
                donation.save()
                log_audit(user, 'donations', 'STATUS_CHANGE', ip_address, ['status', 'claimed_by_tuab', 'delivery_method'])
                lalamove_success = True
            else:
                lalamove_error_msg = l_resp.text
        except Exception as e:
            lalamove_error_msg = str(e)

        # E. Compensating Transaction: Automatic Reversal (Void) if logistics placement fails
        if not lalamove_success:
            void_resp = requests.delete(f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/payments/{maya_payment_id}", json={"reason": "Automatic reversal due to logistics failure."}, headers={'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH, 'Content-Type': 'application/json'}, timeout=30)
            if void_resp.status_code == 200:
                payment_record.status = PaymentStatus.FAILED
            payment_record.save()
            return {"status_code": 502, "detail": f"Delivery placement failed: {lalamove_error_msg}. " + ("Payment has been automatically reversed." if void_resp.status_code == 200 else "Manual refund may be required.")}

        return {"status_code": 200, "detail": "Donation successfully claimed and delivery scheduled.", "lalamove_order_id": order_record.lalamove_order_id}

    return {"status_code": 500, "detail": "Internal system error during orchestration."}
