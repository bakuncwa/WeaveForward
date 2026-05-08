from django.conf import settings
from django.db import transaction

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from ..models import User, UserRole
from ..serializers import (
    CustomTokenObtainPairSerializer,
    DonorRegisterSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    TUABRegisterSerializer,
)
from ..services.audit_service import get_client_ip, log_audit
from ..services.auth_service import generate_reset_token
from ..services.email_service import send_password_reset_email


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


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        role = request.data.get('role')
        if role == UserRole.DONOR:
            serializer = DonorRegisterSerializer(data=request.data)
        elif role == UserRole.TUAB:
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

