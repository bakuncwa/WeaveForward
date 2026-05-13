import time
from django.shortcuts import redirect, render

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
    - Protected pages require a valid backend profile (cached for 5 minutes).
    - Transparently handles token refreshing via api_call.
    - Invalid sessions clear cookies and redirect to login.
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
        auth_state = None

        # Anonymous users are allowed to see guest-only pages.
        # Also allow through if on a guest page with only a refresh_token (no access_token).
        # This avoids burning two backend round-trips just to clear stale cookies.
        if path in GUEST_ONLY_PATHS and not access_token:
            if not refresh_token:
                return self.get_response(request)
            # Has a stale refresh_token but no access_token — let them see the page but clear the cookie.
            response = self.get_response(request)
            clear_frontend_auth_cookies(response)
            return response

        # Protected pages must have some auth material to continue.
        if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) and not access_token and not refresh_token:
            return redirect('login')

        # Attempt to get profile (using cache if available)
        if access_token or refresh_token:
            request.user_profile, auth_state = self._fetch_profile(request)

        # Handle system unavailability (Backend Down)
        if (access_token or refresh_token) and not request.user_profile and auth_state == AUTH_STATE_UNAVAILABLE:
            if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) or path in GUEST_ONLY_PATHS:
                response = render(request, 'frontend/503.html', status=503)
                return self._finalize_response(request, response)

        # Handle invalid sessions (Archived or Expired Session)
        if (access_token or refresh_token) and not request.user_profile and auth_state == AUTH_STATE_INVALID:
            if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
                response = redirect('login')
                clear_frontend_auth_cookies(response)
                return response

            # Guest page with invalid cookies — show the page but clean up the dead cookies.
            response = self.get_response(request)
            clear_frontend_auth_cookies(response)
            return response

        # Logged-in users should not stay on guest-only pages like login/register.
        if path in GUEST_ONLY_PATHS and request.user_profile:
            response = self._redirect_for_profile(request.user_profile)
            return self._finalize_response(request, response)

        # --- RBAC Enforcement ---
        if request.user_profile:
            role = request.user_profile.get('role')
            if path.startswith('/admin/') and role != 'Admin':
                response = self._redirect_for_profile(request.user_profile)
                return self._finalize_response(request, response)
            if path.startswith('/tuab/') and role != 'TUAB':
                response = self._redirect_for_profile(request.user_profile)
                return self._finalize_response(request, response)
            if path.startswith('/donor/') and role != 'Donor':
                response = self._redirect_for_profile(request.user_profile)
                return self._finalize_response(request, response)

        response = self.get_response(request)

        # Post-view Kill-Switch: If a view's api_call discovered the user is archived
        # (deleting the session cache), redirect to login immediately instead of
        # showing a broken page with no data.
        if request.user_profile and 'user_profile' not in request.session:
            if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
                response = redirect('login')
                clear_frontend_auth_cookies(response)
                return response

        return self._finalize_response(request, response)

    def _finalize_response(self, request, response):
        """
        Ensures that any tokens refreshed during the request are applied to the response.
        """
        if hasattr(request, '_pending_refresh_response'):
            apply_backend_auth_cookies(response, request._pending_refresh_response)
        return response

    def _fetch_profile(self, request):
        """
        Retrieves user profile with a 5-minute session-based cache.
        """
        # 1. Try to use session cache
        profile = request.session.get('user_profile')
        last_verified = request.session.get('user_profile_verified_at', 0)
        now = time.time()

        # If we have a cached profile and it's less than 5 minutes old, use it.
        if profile and (now - last_verified < 300):
            return profile, AUTH_STATE_VALID

        # 2. Cache miss or expired: Call Backend
        try:
            response = api_call(request, 'GET', 'users/me')
        except Exception:
            return None, AUTH_STATE_UNAVAILABLE

        if response.status_code == 200:
            data = response.json()
            # Save to session (this will be stored in the signed cookie)
            request.session['user_profile'] = data
            request.session['user_profile_verified_at'] = now
            return data, AUTH_STATE_VALID

        if response.status_code in {401, 403}:
            # Ensure the cache is wiped if the backend explicitly rejects the user
            if 'user_profile' in request.session:
                del request.session['user_profile']
            return None, AUTH_STATE_INVALID

        return None, AUTH_STATE_UNAVAILABLE

    def _redirect_for_profile(self, profile):
        role = profile.get('role')
        if role == 'Admin':
            return redirect('/admin/donors/')
        if role == 'TUAB':
            return redirect('tuab_dashboard')
        return redirect('donor_browse_businesses')
