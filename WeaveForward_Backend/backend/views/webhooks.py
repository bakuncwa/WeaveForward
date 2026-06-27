from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..services.audit_service import get_client_ip
from ..services.subscription_service import (
    _activate_subscription_from_maya_verification,
    process_expired_subscriptions,
)
from ..services.donation_service import process_auto_archive_donations
from ..services.email_service import process_donor_preferred_pickup_date_has_past_emails
from ..services.lalamove_service import process_lalamove_webhook

# Webhook uses ngrok: https://raquel-washiest-heike.ngrok-free.dev/api/webhooks/
MAYA_WEBHOOK_IPS = {'3.1.199.75', '13.229.160.234'}
LALAMOVE_WEBHOOK_IP = '52.76.164.226'


@api_view(['POST'])
@permission_classes([AllowAny])
def webhooks(request):
    # Complexity notes:
    # - Single webhook event routing is O(1) before handing off to the provider-specific handler.
    # - Maya/Lalamove single-event handlers are O(1) for the local database work.
    # - Cloud Scheduler batch trigger is O(r), where r is the number of expired rows processed
    #   by the batch jobs it invokes.
    client_ip = get_client_ip(request)
    payload = request.data if isinstance(request.data, dict) else {}

    # 1. Authenticate Cloud Scheduler via secret header
    scheduler_secret = request.headers.get('X-Scheduler-Secret')
    if scheduler_secret and scheduler_secret == settings.SCHEDULER_SECRET:
        cancelled_subs = process_expired_subscriptions()
        pickup_passed_emails = process_donor_preferred_pickup_date_has_past_emails()
        archived_donations = process_auto_archive_donations()
        return Response({
            "detail": "Successfully processed subscriptions, pickup-date notices, and auto-archived donations.",
            "results": {
                "cancelled_subscriptions_count": cancelled_subs,
                "pickup_passed_emails_count": pickup_passed_emails,
                "archived_donations_count": archived_donations,
            }
        }, status=200)


    # 2. Authenticate Maya and Lalamove via IP checks
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    x_forwarded_ips = [ip.strip() for ip in x_forwarded_for.split(',')] if x_forwarded_for else []

    is_maya = (client_ip in MAYA_WEBHOOK_IPS) or any(ip in MAYA_WEBHOOK_IPS for ip in x_forwarded_ips)
    is_lalamove = (client_ip == LALAMOVE_WEBHOOK_IP) or (LALAMOVE_WEBHOOK_IP in x_forwarded_ips)

    if is_maya:
        result = _activate_subscription_from_maya_verification(payload)
    elif is_lalamove:
        result = process_lalamove_webhook(payload, client_ip)
    else:
        result = {
            "status_code": 403,
            "detail": "Webhook source IP is not allowlisted.",
        }

    return Response({"detail": result["detail"]}, status=result["status_code"])


