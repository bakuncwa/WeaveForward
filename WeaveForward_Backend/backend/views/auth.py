from django.db import transaction
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken

from ..models import SubscriptionStatus, SubscriptionTier, User, UserAccountStatus, UserRole
from ..serializers import (
    CustomTokenObtainPairSerializer,
    DonorRegisterSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    TUABRegisterSerializer,
)
from ..services.audit_service import get_client_ip, log_audit
from ..services.auth_service import (
    clear_auth_cookies,
    enforce_csrf,
    REFRESH_COOKIE_NAME,
    generate_reset_token,
    get_request_base_url,
    set_auth_cookies,
)
from ..services.email_service import send_password_reset_email, send_verification_email
from ..services.upload_service import build_upload_url



class CookieTokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get(REFRESH_COOKIE_NAME) or request.data.get("refresh")
        if not refresh_token:
            return Response({"detail": "Refresh token is required."}, status=status.HTTP_401_UNAUTHORIZED)

        using_cookie_refresh = request.COOKIES.get(REFRESH_COOKIE_NAME) is not None
        if using_cookie_refresh:
            try:
                enforce_csrf(request)
            except Exception as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        try:
            if not serializer.is_valid():
                response = Response(serializer.errors, status=status.HTTP_401_UNAUTHORIZED)
                if using_cookie_refresh:
                    clear_auth_cookies(response)
                return response
        except (TokenError, InvalidToken) as e:
            response = Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)
            if using_cookie_refresh:
                clear_auth_cookies(response)
            return response

        refresh = RefreshToken(refresh_token)
        user = User.objects.only(
            "role", "status", "created_at", "first_name", "last_name",
            "business_name", "upload", "maya_customer_id", "maya_card_id",
        ).filter(user_id=refresh["user_id"]).first()
        if not user:
            response = Response({"detail": "User not found."}, status=status.HTTP_401_UNAUTHORIZED)
            clear_auth_cookies(response)
            return response
        access = refresh.access_token
        access["role"] = user.role
        access["status"] = user.status
        access["created_at"] = user.created_at.isoformat()
        access["first_name"] = user.first_name or ""
        access["last_name"] = user.last_name or ""
        access["business_name"] = user.business_name or ""
        access["upload"] = build_upload_url(user.upload, {"request": request})
        access["is_subscribed"] = user.subscriptions.filter(
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED],
            end_date__gt=timezone.now(),
        ).exists()
        access["has_billing"] = (
            user.maya_customer_id is not None
            and user.maya_card_id is not None
            and user.subscriptions.filter(
                status=SubscriptionStatus.ACTIVE,
                subscription_tier=SubscriptionTier.PRO,
                end_date__gt=timezone.now(),
            ).exists()
        )

        response_data = {"message": "Session refreshed.", "access": str(access)}
        if refreshed_token := serializer.validated_data.get("refresh"):
            response_data["refresh"] = refreshed_token

        response = Response(response_data, status=status.HTTP_200_OK)
        if using_cookie_refresh:
            set_auth_cookies(
                response,
                str(access),
                serializer.validated_data.get("refresh"),
            )
        return response



class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.filter(email=email).first()

            if user and user.is_active:
                uidb64, token = generate_reset_token(user)
                frontend_base_url = get_request_base_url(request)
                reset_link = f"{frontend_base_url}/reset-password-confirm/?uidb64={uidb64}&token={token}"
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




class TokenViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = CustomTokenObtainPairSerializer(
            data=request.data,
            context={'request': request, 'view': self}
        )
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data.copy()
        refresh_token = validated_data.get("refresh")
        access = RefreshToken(refresh_token).access_token
        access["upload"] = build_upload_url(serializer.user.upload, {"request": request})
        validated_data["access"] = str(access)
        validated_data["refresh"] = refresh_token

        response = Response(validated_data, status=status.HTTP_200_OK)
        set_auth_cookies(response, str(access), refresh_token)
        
        # Force CSRF cookie to be set on login
        from django.middleware.csrf import get_token
        get_token(request)
        
        return response

    def destroy(self, request, *args, **kwargs):
        refresh_cookie = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if refresh_cookie:
            try:
                enforce_csrf(request)
            except Exception as exc:
                response = Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
                clear_auth_cookies(response)
                return response

        response = Response({"message": "Successfully logged out"}, status=status.HTTP_205_RESET_CONTENT)
        clear_auth_cookies(response)
        return response


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        uidb64 = request.data.get('uidb64')
        token = request.data.get('token')

        try:
            from django.utils.encoding import force_str
            from django.utils.http import urlsafe_base64_decode
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except Exception:
            return Response({'error': 'Invalid link'}, status=status.HTTP_400_BAD_REQUEST)

        if user.status != UserAccountStatus.EMAIL_UNVERIFIED:
            return Response({'error': 'This email has already been verified.'}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth.tokens import default_token_generator
        if not default_token_generator.check_token(user, token):
            return Response({'error': 'Invalid or expired token'}, status=status.HTTP_400_BAD_REQUEST)

        if user.role == UserRole.DONOR:
            user.status = UserAccountStatus.ACTIVE
        else:
            user.status = UserAccountStatus.UNDER_REVIEW
        user.save(update_fields=['status', 'operational_status'])

        return Response({'message': 'Email verified successfully.'}, status=status.HTTP_200_OK)


class ResendVerificationEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({'email': 'This field is required.'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email, status=UserAccountStatus.EMAIL_UNVERIFIED).first()
        if user:
            uidb64, token = generate_reset_token(user)
            frontend_base_url = get_request_base_url(request)
            verify_link = f"{frontend_base_url}/verify-email/?uidb64={uidb64}&token={token}"
            display_name = user.business_name or f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
            send_verification_email(user.email, verify_link, display_name)

        return Response({'message': 'If that email is pending verification, a new verification link has been sent.'}, status=status.HTTP_200_OK)

