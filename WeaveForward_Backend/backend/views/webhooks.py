from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..services.audit_service import get_client_ip
from ..services.subscription_service import _activate_subscription_from_maya_verification

# Webhook uses ngrok: https://raquel-washiest-heike.ngrok-free.dev/api/webhooks/
MAYA_WEBHOOK_IPS = {'3.1.199.75', '13.229.160.234'}
LALAMOVE_WEBHOOK_IP = '52.76.164.226'


@api_view(['POST'])
@permission_classes([AllowAny])
def webhooks(request):
    client_ip = get_client_ip(request)
    payload = request.data if isinstance(request.data, dict) else {}

    if client_ip in MAYA_WEBHOOK_IPS:
        result = _activate_subscription_from_maya_verification(payload)
    elif client_ip == LALAMOVE_WEBHOOK_IP:
        result = {
            "status_code": 200,
            "detail": "Lalamove webhook scaffold acknowledged. No business logic is active yet.",
        }
    else:
        result = {
            "status_code": 403,
            "detail": "Webhook source IP is not allowlisted.",
        }

    return Response({"detail": result["detail"]}, status=result["status_code"])
