from django.db import transaction
from django.http import JsonResponse
from django.conf import settings

from rest_framework import status, viewsets, mixins
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.pagination import PageNumberPagination

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, Donation
from .serializers import (
    DonorRegisterSerializer, TUABRegisterSerializer, CustomTokenObtainPairSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer, DonationSerializer,
    UserSerializer
)
from .services.location_service import get_city_and_barangay as _get_location_data
from .services.audit_service import get_client_ip, log_audit
from .services.email_service import send_password_reset_email
from .services.auth_service import generate_reset_token

# --- AUTHENTICATION VIEWS ---

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
        except Exception:
            return Response(status=status.HTTP_400_BAD_REQUEST)

class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.get(email=email)
            
            uidb64, token = generate_reset_token(user)
            reset_link = f"{settings.FRONTEND_URL}/reset-password-confirm/?uidb64={uidb64}&token={token}"
            
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

class UserViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_queryset(self):
        # We define a broad queryset here; the list/retrieve methods handle the role-based blocking
        return User.objects.all().order_by('user_id')

    def list(self, request, *args, **kwargs):
        # Only Admins can list all users
        if request.user.role != 'Admin':
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        # Only Admins can retrieve ANY user; others can only retrieve THEMSELVES
        instance = self.get_object()
        if request.user.role != 'Admin' and instance.user_id != request.user.user_id:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        return super().retrieve(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

# --- REGISTRATION VIEWS ---

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        role = request.data.get('role')
        if role == 'Donor':
            serializer = DonorRegisterSerializer(data=request.data)
        elif role == 'TUAB':
            serializer = TUABRegisterSerializer(data=request.data)
        else:
            return Response({"error": "Invalid role specified."}, status=status.HTTP_400_BAD_REQUEST)

        if serializer.is_valid():
            ip_address = get_client_ip(request)
            with transaction.atomic():
                user = serializer.save()
                log_audit(actor=user, entity_type='User', action='POST', ip_address=ip_address)
            return Response({"message": "Registration successful."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([AllowAny])
def lookup_location(request):
    lat = request.query_params.get('lat')
    lng = request.query_params.get('lng')
    if not lat or not lng:
        return JsonResponse({'error': 'Coordinates required'}, status=400)
    location = _get_location_data(lat, lng)
    return JsonResponse(location) if location else JsonResponse({'error': 'Location not found in NCR'}, status=404)

# --- DONATION MANAGEMENT VIEWS ---

class DonationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = DonationSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Donation.objects.all()

        # Main List visibility (Hall of Fame)
        if user.role != 'Admin':
            # Everyone sees all donations except those that are ARCHIVED
            queryset = queryset.exclude(status='ARCHIVED')

        return queryset.prefetch_related(
            'items__lookup', 'orders__payments', 'donor', 'claimed_by_tuab'
        ).order_by('-submitted_at', '-donation_id')

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Returns the logged-in user's personal donation history."""
        user = request.user
        
        if user.role == 'Donor':
            queryset = Donation.objects.filter(donor=user)
        elif user.role == 'TUAB':
            queryset = Donation.objects.filter(claimed_by_tuab=user)
        else:
            queryset = Donation.objects.all()

        queryset = queryset.exclude(status='ARCHIVED').prefetch_related(
            'items__lookup', 'orders__payments', 'donor', 'claimed_by_tuab'
        ).order_by('-submitted_at', '-donation_id')

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
