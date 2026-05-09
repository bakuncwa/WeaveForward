import base64
import json
import time
import requests
from django.shortcuts import redirect
from .constants import BACKEND_BASE_URL
from .services import apply_backend_auth_cookies, clear_frontend_auth_cookies


def is_token_expired(token):
    """Manually decode JWT payload to check 'exp' field without external libraries."""
    try:
        # JWT format is header.payload.signature
        _, payload_b64, _ = token.split('.')
        # Add padding if needed for base64 decoding
        missing_padding = len(payload_b64) % 4
        if missing_padding:
            payload_b64 += '=' * (4 - missing_padding)

        payload_json = base64.b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        return payload.get('exp', 0) < time.time()
    except Exception:
        return True  # Treat as expired if we can't parse it


class GuestOnlyMiddleware:
    """Redirect authenticated users away from guest-only pages."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Removed '/' from this list to prevent the redirect loop
        guest_only_paths = {'/select-role/', '/register/donor/', '/register/tuab/', '/forgot-password/', '/reset-password-confirm/'}

        if request.path in guest_only_paths and request.COOKIES.get('access_token'):
            return redirect('login')

        return self.get_response(request)


class TokenRefreshMiddleware:
    """Automatically refreshes the access token if it's missing or expired but a refresh token exists."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        guest_only_paths = {'/', '/select-role/', '/register/donor/', '/register/tuab/', '/forgot-password/', '/reset-password-confirm/'}

        access = request.COOKIES.get('access_token')
        refresh = request.COOKIES.get('refresh_token')

        # SMART CHECK: Refresh if access is missing OR if it is expired
        if refresh and (not access or is_token_expired(access)):
            try:
                refresh_url = f"{BACKEND_BASE_URL}token/refresh/"
                res = requests.post(
                    refresh_url,
                    cookies={'refresh_token': refresh},
                    headers={'X-CSRFToken': request.COOKIES.get('csrftoken')}
                )

                if res.status_code == 200:
                    # Update current request so the view sees the new token immediately
                    request.COOKIES['access_token'] = res.cookies.get('access_token')
                    request._refresh_res = res
                elif request.path not in guest_only_paths:
                    # Refresh failed and we aren't on a guest page -> Session is dead
                    response = redirect('login')
                    clear_frontend_auth_cookies(response)
                    return response
            except Exception:
                pass

        response = self.get_response(request)

        # Apply new cookies to the browser response if a refresh happened
        if hasattr(request, '_refresh_res'):
            apply_backend_auth_cookies(response, request._refresh_res)

        return response
