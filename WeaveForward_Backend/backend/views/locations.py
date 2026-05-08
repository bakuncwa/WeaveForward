from django.http import JsonResponse

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from ..services.location_service import get_city_and_barangay as _get_location_data


@api_view(['GET'])
@permission_classes([AllowAny])
def lookup_location(request):
    lat = request.query_params.get('lat')
    lng = request.query_params.get('lng')
    if not lat or not lng:
        return JsonResponse({'error': 'Coordinates required'}, status=400)
    location = _get_location_data(lat, lng)
    return JsonResponse(location) if location else JsonResponse({'error': 'Location not found in NCR'}, status=404)

