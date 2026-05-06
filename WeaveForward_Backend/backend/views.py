from django.http import JsonResponse
from .services.location_service import get_city_and_barangay

def get_city_and_barangay(request):
    """
    API endpoint to return barangay and city based on lat/lng.
    Usage: /api/get-city-and-barangay/?lat=14.5&lng=121.0
    """
    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid coordinates'}, status=400)

    location = get_city_and_barangay(lat, lng)
    
    if location:
        return JsonResponse(location)
    
    return JsonResponse({'error': 'Location not found in NCR'}, status=404)
