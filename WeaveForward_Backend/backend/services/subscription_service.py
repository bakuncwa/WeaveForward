from calendar import monthrange
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .audit_service import log_audit
from ..models import (
    PaymentStatus,
    Subscription,
    SubscriptionPayment,
    SubscriptionStatus,
    SubscriptionTier,
    User,
    UserAccountStatus,
    UserRole,
)

MAYA_REQUEST_TIMEOUT_SECONDS = 30


def get_active_subscriptions_for_user(*, user):
    return list(
        Subscription.objects.select_for_update()
        .filter(user=user, status=SubscriptionStatus.ACTIVE)
    )


def _maya_headers(authorization_value):
    return {
        'Authorization': authorization_value,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _extract_error_detail(response):
    try:
        payload = response.json()
    except ValueError:
        return response.text or "Maya request failed."

    if isinstance(payload, dict):
        return payload.get('error') or payload.get('message') or payload.get('detail') or str(payload)
    return str(payload)


def _maya_post(*, url, payload, authorization_value):
    return requests.post(
        url,
        json=payload,
        headers=_maya_headers(authorization_value),
        timeout=MAYA_REQUEST_TIMEOUT_SECONDS,
    )


def _maya_delete(*, url, authorization_value):
    return requests.delete(
        url,
        headers=_maya_headers(authorization_value),
        timeout=MAYA_REQUEST_TIMEOUT_SECONDS,
    )


def subscribe_user(*, target_user_id, first_name, last_name, card, frontend_base_url):
    with transaction.atomic():
        try:
            user = User.objects.select_for_update().get(pk=target_user_id)
        except User.DoesNotExist:
            return {"status_code": 404, "detail": "User not found."}

        if user.status != UserAccountStatus.ACTIVE:
            return {"status_code": 409, "detail": "Only active TUAB users can subscribe."}

        active_subscriptions = get_active_subscriptions_for_user(user=user)
        if active_subscriptions:
            return {"status_code": 409, "detail": "User is already subscribed."}

        if not settings.MAYA_SANDBOX_SECRET_BASIC_AUTH or not settings.MAYA_SANDBOX_PUBLIC_BASIC_AUTH:
            return {"status_code": 500, "detail": "Maya sandbox credentials are not configured."}

        base_url = settings.MAYA_SANDBOX_BASE_URL.rstrip('/')

        customer_id = user.maya_customer_id

    if not customer_id:
        try:
            customer_response = _maya_post(
                url=f'{base_url}/customers',
                payload={
                    'firstName': first_name,
                    'lastName': last_name,
                },
                authorization_value=settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
            )
        except requests.RequestException as exc:
            return {
                "status_code": 502,
                "detail": f"Maya customer creation failed: {exc}",
            }
        if customer_response.status_code != 200:
            return {
                "status_code": 502,
                "detail": f"Maya customer creation failed: {_extract_error_detail(customer_response)}",
            }
        customer_payload = customer_response.json()
        customer_id = customer_payload['id']

    try:
        payment_token_response = _maya_post(
            url=f'{base_url}/payment-tokens',
            payload={'card': card},
            authorization_value=settings.MAYA_SANDBOX_PUBLIC_BASIC_AUTH,
        )
    except requests.RequestException as exc:
        return {
            "status_code": 502,
            "detail": f"Maya payment token creation failed: {exc}",
        }
    if payment_token_response.status_code != 200:
        return {
            "status_code": 502,
            "detail": f"Maya payment token creation failed: {_extract_error_detail(payment_token_response)}",
        }
    payment_token_payload = payment_token_response.json()

    payment_token_id = payment_token_payload['paymentTokenId']

    try:
        customer_card_response = _maya_post(
            url=f'{base_url}/customers/{customer_id}/cards',
            payload={
                'paymentTokenId': payment_token_id,
                'isDefault': True,
                'redirectUrl': {
                    'success': f"{frontend_base_url.rstrip('/')}/tuab/subscribe/?status=success",
                    'failure': f"{frontend_base_url.rstrip('/')}/tuab/subscribe/?status=failed",
                    'cancel': f"{frontend_base_url.rstrip('/')}/tuab/subscribe/?status=failed",
                }
            },
            authorization_value=settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
        )
    except requests.RequestException as exc:
        return {
            "status_code": 502,
            "detail": f"Maya card binding failed: {exc}",
        }
    if customer_card_response.status_code != 200:
        return {
            "status_code": 502,
            "detail": f"Maya card binding failed: {_extract_error_detail(customer_card_response)}",
        }
    customer_card_payload = customer_card_response.json()
    stored_card_token_id = customer_card_payload.get('cardTokenId') or payment_token_id

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=target_user_id)

        if user.status != UserAccountStatus.ACTIVE:
            return {
                "status_code": 409,
                "detail": "Only active TUAB users can subscribe.",
            }

        active_subscriptions = get_active_subscriptions_for_user(user=user)
        if active_subscriptions:
            return {
                "status_code": 409,
                "detail": "User is already subscribed.",
            }

        user.maya_customer_id = customer_id
        user.maya_card_id = stored_card_token_id
        user.save(update_fields=['maya_customer_id', 'maya_card_id', 'updated_at'])

    return {
        "status_code": 200,
        "detail": "Maya subscription setup succeeded. Card verification is still pending.",
        "fields_modified": ['maya_customer_id', 'maya_card_id'],
        "maya_customer_id": customer_id,
        "maya_card_id": stored_card_token_id,
        "cardTokenId": stored_card_token_id,
        "state": customer_card_payload.get('state'),
        "verificationUrl": customer_card_payload.get('verificationUrl'),
    }


def _activate_subscription_from_maya_verification(payload):
    maya_card_token_id = payload.get('paymentTokenId') or (payload.get('fundSource') or {}).get('id')
    if not maya_card_token_id:
        return {"status_code": 200, "detail": "Maya webhook ignored because no card token was present."}

    failed_verification = (
        payload.get('status') in ['AUTH_FAILED', 'PAYMENT_FAILED']
        and Decimal(str(payload.get('amount'))) == Decimal('10.00')
    )

    if failed_verification and maya_card_token_id:
        with transaction.atomic():
            user = User.objects.select_for_update().get(role=UserRole.TUAB, maya_card_id=maya_card_token_id)
            user.maya_card_id, user.updated_at = None, timezone.now(); user.save(update_fields=['maya_card_id', 'updated_at'])
        return {"status_code": 200, "detail": "Maya card verification failed and the card token was cleared."}

    verified = (
        payload.get('status') == 'PAYMENT_SUCCESS'
        and payload.get('isPaid') is True
        and Decimal(str(payload.get('amount'))) == Decimal('10.00')
    )
    if not verified:
        return {"status_code": 200, "detail": "Maya webhook acknowledged with no subscription action taken."}

    # Verify-then-Trust: Double check with Maya API
    v_resp = requests.get(
        f"https://pg-sandbox.paymaya.com/payments/v1/payments/{payload.get('id')}",
        headers=_maya_headers(settings.MAYA_SANDBOX_SECRET_BASIC_AUTH),
        timeout=10
    )
    if v_resp.status_code != 200 or v_resp.json().get('status') not in ['PAYMENT_SUCCESS', 'VOIDED']:
        return {"status_code": 200, "detail": "Maya verification failed."}

    with transaction.atomic():
        user = User.objects.select_for_update().get(role=UserRole.TUAB, maya_card_id=maya_card_token_id)

        if user.status != UserAccountStatus.ACTIVE:
            return {"status_code": 200, "detail": "Maya webhook ignored because the matched TUAB is not active."}
        if get_active_subscriptions_for_user(user=user):
            return {"status_code": 200, "detail": "Maya webhook ignored because the matched TUAB is already subscribed."}
        if not all((settings.MAYA_SANDBOX_SECRET_BASIC_AUTH, settings.MAYA_SANDBOX_BASE_URL, user.maya_customer_id, user.maya_card_id)):
            return {"status_code": 500, "detail": "Maya subscription charge is not fully configured for the matched user."}

        request_reference_number = payload.get('id') or f"user-{user.user_id}-{int(timezone.now().timestamp())}"
        request_reference_number = request_reference_number[:36]
        user_id = user.pk
        maya_customer_id = user.maya_customer_id
        maya_card_id = user.maya_card_id

    charge_response = _maya_post(
        url=f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/customers/{maya_customer_id}/cards/{maya_card_id}/payments",
        payload={
            'totalAmount': {'amount': 499.00, 'currency': 'PHP'},
            'cardId': maya_card_id,
            'requestReferenceNumber': request_reference_number,
        },
        authorization_value=settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
    )
    if charge_response.status_code != 200:
        return {"status_code": 502, "detail": f"Maya subscription charge failed: {_extract_error_detail(charge_response)}"}

    charge_payload = charge_response.json()
    charged = (
        charge_payload.get('status') == 'PAYMENT_SUCCESS'
        and charge_payload.get('isPaid') is True
        and Decimal(str(charge_payload.get('amount'))) == Decimal('499.00')
    )
    if not charged:
        return {"status_code": 502, "detail": "Maya subscription charge did not complete successfully."}

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)

        if user.status != UserAccountStatus.ACTIVE:
            return {"status_code": 409, "detail": "Subscription activation could not be finalized because the matched TUAB is not active."}
        if user.maya_card_id != maya_card_id or user.maya_customer_id != maya_customer_id:
            return {"status_code": 409, "detail": "Subscription activation could not be finalized because the Maya card changed during payment."}
        if get_active_subscriptions_for_user(user=user):
            return {"status_code": 409, "detail": "Subscription activation could not be finalized because the user is already subscribed."}

        start_date = timezone.now()
        next_year = start_date.year + (1 if start_date.month == 12 else 0)
        next_month = 1 if start_date.month == 12 else start_date.month + 1
        SubscriptionPayment.objects.create(
            subscription=Subscription.objects.create(
                user=user,
                status=SubscriptionStatus.ACTIVE,
                subscription_tier=SubscriptionTier.PRO,
                start_date=start_date,
                end_date=start_date.replace(
                    year=next_year,
                    month=next_month,
                    day=min(start_date.day, monthrange(next_year, next_month)[1]),
                ),
            ),
            amount=Decimal('499.00'),
            status=PaymentStatus.SUCCESS,
            payment_reference=request_reference_number,
        )

    return {"status_code": 200, "detail": "Maya card verification succeeded and the subscription was activated."}


def unsubscribe_user(*, target_user_id, actor=None, ip_address=None):
    """
    Cancels all active subscriptions for a user and clears their Maya payment information.
    Uses transaction.atomic() and select_for_update() for data consistency and locking.
    """
    with transaction.atomic():
        try:
            user = User.objects.select_for_update().get(pk=target_user_id)
        except User.DoesNotExist:
            return {
                "status_code": 404,
                "detail": "User not found.",
                "user_updated": False,
                "cancelled_subscriptions_count": 0
            }

        active_subscriptions = get_active_subscriptions_for_user(user=user)

        if not active_subscriptions:
            return {
                "status_code": 409,
                "detail": "User does not have an active subscription.",
                "user_updated": False,
                "cancelled_subscriptions_count": 0
            }

        now = timezone.now()
        for sub in active_subscriptions:
            sub.status = SubscriptionStatus.CANCELLED
            sub.updated_at = now

        if active_subscriptions:
            Subscription.objects.bulk_update(active_subscriptions, ['status', 'updated_at'])

        old_card_id = user.maya_card_id
        user.maya_card_id = None
        user.save(update_fields=['maya_card_id', 'updated_at'])

        log_audit(
            actor=actor or user,
            entity_type="users",
            action="STATUS_CHANGE",
            ip_address=ip_address,
            fields_modified=["maya_card_id"]
        )

    # Outside atomic — best-effort Maya card deletion
    if user.maya_customer_id and old_card_id:
        try:
            _maya_delete(
                url=f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/customers/{user.maya_customer_id}/cards/{old_card_id}",
                authorization_value=settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
            )
        except requests.RequestException:
            pass

    return {
        "status_code": 200,
        "detail": "Successfully unsubscribed.",
        "user_updated": True,
        "cancelled_subscriptions_count": len(active_subscriptions)
    }



def process_expired_subscriptions():
    """
    Finds all active subscriptions that have expired (end_date <= now).
    Tries to charge the user's Maya card and extend by one month;
    cancels the subscription if payment fails.
    """
    now = timezone.now()
    expired_subs = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        end_date__lte=now
    )
    admin_user = User.objects.filter(role=UserRole.ADMIN).first()
    cancelled_count = 0
    for sub in expired_subs:
        user = User.objects.get(pk=sub.user_id)
        renewed = False
        try:
            resp = _maya_post(
                url=f"{settings.MAYA_SANDBOX_BASE_URL.rstrip('/')}/customers/{user.maya_customer_id}/cards/{user.maya_card_id}/payments",
                payload={
                    'totalAmount': {'amount': 499.00, 'currency': 'PHP'},
                    'cardId': user.maya_card_id,
                    'requestReferenceNumber': f"renew-{user.user_id}-{int(now.timestamp())}"[:36],
                },
                authorization_value=settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
            )
            body = resp.json() if resp.status_code == 200 else {}
            if body.get('status') == 'PAYMENT_SUCCESS' and body.get('isPaid') is True and Decimal(str(body.get('amount'))) == Decimal('499.00'):
                sub.end_date = sub.end_date + timezone.timedelta(days=30)
                sub.save(update_fields=['end_date', 'updated_at'])
                SubscriptionPayment.objects.create(
                    subscription=sub, amount=Decimal('499.00'),
                    status=PaymentStatus.SUCCESS, payment_reference=f"renew-{user.user_id}-{int(now.timestamp())}"[:36],
                )
                renewed = True
        except (requests.RequestException, InvalidOperation, TypeError, ValueError):
            pass

        if not renewed:
            unsubscribe_user(target_user_id=sub.user_id, actor=admin_user)
            cancelled_count += 1

    return cancelled_count



