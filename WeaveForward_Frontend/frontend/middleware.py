import requests
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .constants import BACKEND_BASE_URL
from .services import api_call, apply_backend_auth_cookies, clear_frontend_auth_cookies


PROTECTED_PREFIXES = ('/donor/', '/tuab/', '/admin/')
GUEST_ONLY_PATHS = {
    '/',
    '/select-role/',
    '/register/donor/',
    '/register/tuab/',
    '/forgot-password/',
    '/reset-password-confirm/',
}
PUBLIC_PASSTHROUGH_PATHS = {'/api/location/lookup/', '/logout/'}
AUTH_STATE_VALID = 'valid'
AUTH_STATE_INVALID = 'invalid'
AUTH_STATE_UNAVAILABLE = 'unavailable'


class TokenRefreshMiddleware:
    """
    Frontend auth policy:
    - Protected pages require a valid backend profile.
    - Guest-only pages redirect away when a valid session exists.
    - Invalid sessions clear cookies.
    - No-session guest requests are allowed through normally.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        request.user_profile = None

        if path in PUBLIC_PASSTHROUGH_PATHS:
            return self.get_response(request)

        access_token = request.COOKIES.get('access_token')
        refresh_token = request.COOKIES.get('refresh_token')
        refresh_response = None
        should_clear_cookies = False
        auth_state = None

        # Anonymous users are allowed to see guest-only pages.
        if path in GUEST_ONLY_PATHS and not access_token and not refresh_token:
            return self.get_response(request)

        # Protected pages must have some auth material to continue.
        if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) and not access_token and not refresh_token:
            return redirect('login')

        if access_token:
            request.user_profile, auth_state = self._fetch_profile(request)

        if not request.user_profile and refresh_token:
            refresh_response, refresh_state = self._refresh_session(request)
            if refresh_response:
                request.user_profile, auth_state = self._fetch_profile(request)
            elif refresh_state == AUTH_STATE_UNAVAILABLE:
                auth_state = AUTH_STATE_UNAVAILABLE
            else:
                auth_state = refresh_state or auth_state

        if (access_token or refresh_token) and auth_state == AUTH_STATE_UNAVAILABLE and not request.user_profile:
            if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) or path in GUEST_ONLY_PATHS:
                response = render(request, 'frontend/503.html', status=503)
                if refresh_response:
                    apply_backend_auth_cookies(response, refresh_response)
                return response

        # Cookies exist, but we still could not confirm a valid logged-in user.
        if (access_token or refresh_token) and not request.user_profile and auth_state != AUTH_STATE_UNAVAILABLE:
            should_clear_cookies = True
            if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
                response = redirect('login')
                clear_frontend_auth_cookies(response)
                return response

        # Logged-in users should not stay on guest-only pages like login/register.
        if path in GUEST_ONLY_PATHS and request.user_profile:
            response = self._redirect_for_profile(request.user_profile)
            if refresh_response:
                apply_backend_auth_cookies(response, refresh_response)
            return response

        # --- RBAC Enforcement ---
        # Ensure users can only access their designated prefixes.
        if request.user_profile:
            role = request.user_profile.get('role')
            # If they are in a protected area not meant for their role, redirect them to their correct dashboard.
            if path.startswith('/admin/') and role != 'Admin':
                return self._redirect_for_profile(request.user_profile)
            if path.startswith('/tuab/') and role != 'TUAB':
                return self._redirect_for_profile(request.user_profile)
            if path.startswith('/donor/') and role != 'Donor':
                return self._redirect_for_profile(request.user_profile)

        response = self.get_response(request)

        if should_clear_cookies:
            clear_frontend_auth_cookies(response)
        if refresh_response:
            apply_backend_auth_cookies(response, refresh_response)

        return response

    def _fetch_profile(self, request):
        try:
            response = requests.request(
                'GET',
                f"{BACKEND_BASE_URL.rstrip('/')}/users/me",
                cookies=dict(request.COOKIES.items()),
            )
        except Exception:
            return None, AUTH_STATE_UNAVAILABLE

        if response.status_code == 200:
            return response.json(), AUTH_STATE_VALID

        if response.status_code in {401, 403}:
            return None, AUTH_STATE_INVALID

        return None, AUTH_STATE_UNAVAILABLE

    def _refresh_session(self, request):
        try:
            response = api_call(request, 'POST', 'token/refresh')
        except Exception:
            return None, AUTH_STATE_UNAVAILABLE

        if response.status_code != 200:
            if response.status_code in {401, 403}:
                return None, AUTH_STATE_INVALID
            return None, AUTH_STATE_UNAVAILABLE

        new_access_token = response.cookies.get('access_token')
        if not new_access_token:
            return None, AUTH_STATE_UNAVAILABLE

        request.COOKIES['access_token'] = new_access_token

        rotated_refresh_token = response.cookies.get('refresh_token')
        if rotated_refresh_token:
            request.COOKIES['refresh_token'] = rotated_refresh_token

        return response, AUTH_STATE_VALID

    def _redirect_for_profile(self, profile):
        role = profile.get('role')
        if role == 'Admin':
            return redirect('/admin/donors/')
        if role == 'TUAB':
            return redirect('tuab_dashboard')
        return redirect('donor_browse_businesses')
