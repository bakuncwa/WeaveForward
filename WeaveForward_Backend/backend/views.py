from django.db import transaction
from django.http import JsonResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .serializers import DonorRegisterSerializer, TUABRegisterSerializer
from .services.location_service import get_city_and_barangay
from .services.audit_service import get_client_ip, log_audit

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        role = request.data.get('role')
        ip_address = get_client_ip(request)
        
        if role == 'Donor': serializer = DonorRegisterSerializer(data=request.data)
        elif role == 'TUAB': serializer = TUABRegisterSerializer(data=request.data)
        else: return Response({'error': 'Invalid or missing role'}, status=400)

        if serializer.is_valid():
            with transaction.atomic():
                user = serializer.save(role=role)
                log_audit(actor=user, entity_type='User', action='REGISTER', ip_address=ip_address)
            return Response({'message': f'{role} registered', 'user_id': user.user_id, 'email': user.email}, status=201)
        
        return Response(serializer.errors, status=400)

def get_city_and_barangay_view(request):
    try:
        lat, lng = float(request.GET.get('lat')), float(request.GET.get('lng'))
    except (TypeError, ValueError): return JsonResponse({'error': 'Invalid coordinates'}, status=400)
    
    location = get_city_and_barangay(lat, lng)
    return JsonResponse(location) if location else JsonResponse({'error': 'Location not found in NCR'}, status=404)
