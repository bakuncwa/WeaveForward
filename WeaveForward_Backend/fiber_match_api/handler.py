import hashlib, hmac
import json
import logging

from django.conf import settings

from .services import InferenceService

logger = logging.getLogger(__name__)


def handle_prediction(body: dict, api_key: str):
    parts = (api_key or "").split(" ")
    if len(parts) != 2 or parts[0] != "ApiKey":
        return 401, {"error": "Invalid API key"}

    hashed = hmac.new(settings.SECRET_KEY.encode(), parts[1].encode(), hashlib.sha256).hexdigest()[:50]
    from backend.models import ApiToken
    if not ApiToken.objects.filter(token=hashed).exists():
        return 401, {"error": "Invalid API key"}

    items = body.get("items", [])
    tuabs = body.get("tuabs", [])
    if not items or not tuabs:
        return 400, {"error": "Both 'items' and 'tuabs' are required and must be non-empty."}

    try:
        predictions = InferenceService.infer(items, tuabs)
    except ValueError as e:
        return 503, {"error": str(e)}
    except Exception:
        logger.exception("Inference failed")
        return 500, {"error": "Inference failed."}

    return 200, {"predictions": predictions}
