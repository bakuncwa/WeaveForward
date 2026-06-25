import logging
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .services import InferenceService
from .authentication import ApiKeyAuthentication

logger = logging.getLogger(__name__)


@api_view(["POST"])
@authentication_classes([ApiKeyAuthentication])
@permission_classes([])
def infer(request):
    items = request.data.get("items", [])
    tuabs = request.data.get("tuabs", [])

    if not items or not tuabs:
        return Response(
            {"error": "Both 'items' and 'tuabs' are required and must be non-empty."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        predictions = InferenceService.infer(items, tuabs)
    except ValueError as e:
        return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        logger.exception("Inference failed")
        return Response({"error": "Inference failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({"predictions": predictions}, status=status.HTTP_200_OK)
