from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.settings import api_settings

from ..models import User

ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"


def enforce_csrf(request):
    check = CSRFCheck(lambda request: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        raw_token = request.COOKIES.get(ACCESS_COOKIE_NAME)

        if raw_token is None:
            return None

        enforce_csrf(request)

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token


def set_auth_cookies(response, access_token, refresh_token=None):
    if access_token:
        response.set_cookie(
            ACCESS_COOKIE_NAME,
            access_token,
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            max_age=int(api_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
        )
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            refresh_token,
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            max_age=int(api_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        )


def clear_auth_cookies(response):
    response.delete_cookie(
        ACCESS_COOKIE_NAME,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def generate_reset_token(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return uid, token

def validate_reset_token(uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
        if default_token_generator.check_token(user, token):
            return user
    except Exception:
        pass
    return None

def reset_user_password(user, new_password):
    user.set_password(new_password)
    # Clear 2FA as requested
    user.is_2fa_enabled = False
    user.totp_secret = None
    user.save()
