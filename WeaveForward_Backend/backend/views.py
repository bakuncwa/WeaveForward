from django.db import transaction
from django.http import JsonResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .serializers import (
    DonorRegisterSerializer, TUABRegisterSerializer, CustomTokenObtainPairSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer
)
from .services.location_service import get_city_and_barangay as _get_location_data
from .services.audit_service import get_client_ip, log_audit
from .services.email_service import send_password_reset_email
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User
from .constants import FRONTEND_URL
from rest_framework.permissions import AllowAny, IsAuthenticated

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"message": "Successfully logged out"}, status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)

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
                log_audit(actor=user, entity_type='User', action='POST', ip_address=ip_address)
            return Response({'message': f'{role} registered', 'user_id': user.user_id, 'email': user.email}, status=201)
        
        return Response(serializer.errors, status=400)

def lookup_location(request):
    """
    RESTful endpoint to lookup city and barangay based on lat/lng.
    """
    try:
        lat, lng = float(request.GET.get('lat')), float(request.GET.get('lng'))
    except (TypeError, ValueError): return JsonResponse({'error': 'Invalid coordinates'}, status=400)
    
    location = _get_location_data(lat, lng)
    return JsonResponse(location) if location else JsonResponse({'error': 'Location not found in NCR'}, status=404)

from .services.auth_service import generate_reset_token

class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.get(email=email)
            
            # Generate token and uid using service
            uidb64, token = generate_reset_token(user)
            
            # Build reset link (Frontend URL from constants)
            reset_link = f"{FRONTEND_URL}/reset-password-confirm/?uidb64={uidb64}&token={token}"
            
            # Send email
            email_sent = send_password_reset_email(email, reset_link)
            
            if email_sent:
                log_audit(actor=user, entity_type='User', action='POST', ip_address=get_client_ip(request))
                return Response({"message": "Password reset email sent."}, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Failed to send email. Resend may be restricting recipients on this API key."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if serializer.is_valid():
            ip_address = get_client_ip(request)
            with transaction.atomic():
                user = serializer.save()
                log_audit(actor=user, entity_type='User', action='PATCH', ip_address=ip_address)
            return Response({"message": "Password has been reset successfully. 2FA has been disabled."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
