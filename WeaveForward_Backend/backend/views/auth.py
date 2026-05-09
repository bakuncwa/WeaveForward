from django.conf import settings
from django.db import transaction

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
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
from ..services.auth_service import enforce_csrf, generate_reset_token, set_js_auth_cookies
from ..services.email_service import send_password_reset_email


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class CookieTokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_cookie = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if refresh_cookie:
            try:
                enforce_csrf(request)
            except Exception as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        refresh_token = request.data.get("refresh") or refresh_cookie
        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_401_UNAUTHORIZED)

        response = Response(serializer.validated_data, status=status.HTTP_200_OK)
        set_js_auth_cookies(
            response,
            serializer.validated_data.get("access"),
            serializer.validated_data.get("refresh"),
        )
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh") or request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Successfully logged out"}, status=status.HTTP_205_RESET_CONTENT)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.filter(email=email).first()

            if user and user.is_active:
                uidb64, token = generate_reset_token(user)
                reset_link = f"{settings.FRONTEND_URL}/reset-password-confirm/?uidb64={uidb64}&token={token}"
                send_password_reset_email(email, reset_link)

            return Response(
                {"message": "If that email exists, a password reset link has been sent."},
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if serializer.is_valid():
            ip_address = get_client_ip(request)
            with transaction.atomic():
                user = serializer.save()
                log_audit(
                    actor=user,
                    entity_type='users',
                    action='CREDENTIAL_UPDATE',
                    ip_address=ip_address,
                    fields_modified=['password', 'is_2fa_enabled', 'totp_secret'],
                )
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
            serializer.save()
            return Response({"message": "Registration successful."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
