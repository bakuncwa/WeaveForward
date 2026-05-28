import httpx
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import JsonResponse
from django.shortcuts import redirect, render

from .services import (
    api_call,
    apply_backend_auth_cookies,
)

AUTH_COOKIE_NAMES = ("access_token", "refresh_token", "user_role", "user_name", "user_email")


PROTECTED_PREFIXES = ("/donor/", "/tuab/", "/admin/", "/api/2fa/", "/api/materials/", "/api/donors/")
GUEST_ONLY_PATHS = {
    "/",
    "/select-role/",
    "/register/donor/",
    "/register/tuab/",
    "/forgot-password/",
    "/reset-password-confirm/",
}
PUBLIC_PASSTHROUGH_PATHS = {"/api/location/lookup/", "/logout/"}


class TokenRefreshMiddleware:
    sync_capable = False
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

    async def __call__(self, request):
        response = await self._process_request(request)
        if hasattr(request, "_pending_refresh_response"):
            apply_backend_auth_cookies(response, request._pending_refresh_response)
        return response

    async def _process_request(self, request):
        path = request.path
        request.user_profile = None

        if path in PUBLIC_PASSTHROUGH_PATHS:
            return await self.get_response(request)

        access_token = request.COOKIES.get("access_token")
        refresh_token = request.COOKIES.get("refresh_token")

        print(f"[MIDDLEWARE DEBUG] path={path} has_access={bool(access_token)} has_refresh={bool(refresh_token)}")

        # Fully anonymous visitors can view guest-only pages normally.
        if path in GUEST_ONLY_PATHS and not access_token and not refresh_token:
            print(f"[MIDDLEWARE DEBUG] DECISION: anonymous guest pass-through for {path}")
            return await self.get_response(request)

        # Protected routes require at least some auth cookie before we even try /users/me.
        if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) and not access_token and not refresh_token:
            print(f"[MIDDLEWARE DEBUG] DECISION: no auth cookies at all -> means you never logged in, or all cookies were already cleared by a previous failed refresh. Redirecting to login for {path}")
            return redirect("login")

        # Any request carrying auth cookies must be verified against the fresh /users/me backend profile.
        if access_token or refresh_token:
            print(f"[MIDDLEWARE DEBUG] DECISION: verifying auth via /users/me for {path}")
            try:
                profile_response = await api_call(request, "GET", "users/me")
            except httpx.RequestError:
                print(f"[MIDDLEWARE DEBUG] DECISION: /users/me threw RequestError (backend unreachable) for {path}")
                # If auth verification itself cannot reach the backend, show the maintenance page on auth-sensitive routes.
                if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) or path in GUEST_ONLY_PATHS:
                    return self._service_unavailable_response(request)
                return await self.get_response(request)

            print(f"[MIDDLEWARE DEBUG] /users/me status={profile_response.status_code} for {path}")

            if profile_response.status_code == 200:
                request.user_profile = profile_response.json()
                request.session["user_profile"] = request.user_profile
                print(f"[MIDDLEWARE DEBUG] DECISION: auth valid, profile role={request.user_profile.get('role')} for {path}")
            elif profile_response.status_code in {401, 403}:
                print(f"[MIDDLEWARE DEBUG] DECISION: /users/me returned {profile_response.status_code} -> your token is expired, revoked, or the backend rejected it. This is THE logout trigger. Reason is logged out by middleware. path={path}")
                # Expired or invalid auth should kick protected users back to login and clean guest cookies too.
                request.session.pop("user_profile", None)
                if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
                    print(f"[MIDDLEWARE DEBUG] DECISION: cleared all cookies + redirected to login for {path} -> you are now logged out. Fix: refresh token also expired or blacklisted, so the frontend's automatic refresh failed earlier.")
                    response = redirect("login")
                    for c in AUTH_COOKIE_NAMES:
                        response.delete_cookie(c, path="/")
                    return response
                print(f"[MIDDLEWARE DEBUG] DECISION: cleared stale cookies but still rendered the page for {path} (guest-only or public path)")
                response = await self.get_response(request)
                for c in AUTH_COOKIE_NAMES:
                    response.delete_cookie(c, path="/")
                return response
            else:
                print(f"[MIDDLEWARE DEBUG] DECISION: /users/me returned {profile_response.status_code} (not 200/401/403) -> backend is in an unexpected state. Showing 503 for {path}")
                # Unexpected auth backend responses are treated as temporary auth-service outages.
                if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) or path in GUEST_ONLY_PATHS:
                    return self._service_unavailable_response(request)

        # Already-authenticated users should not stay on login/register/forgot-password screens.
        if path in GUEST_ONLY_PATHS and request.user_profile:
            return self._redirect_for_profile(request.user_profile)

        if request.user_profile:
            role = request.user_profile.get("role")
            # Role-gated sections always redirect authenticated users back to the correct dashboard.
            if path.startswith("/admin/") and role != "Admin":
                return self._redirect_for_profile(request.user_profile)
            if path.startswith("/tuab/") and role != "TUAB":
                return self._redirect_for_profile(request.user_profile)
            if path.startswith("/donor/") and role != "Donor":
                return self._redirect_for_profile(request.user_profile)

        try:
            return await self.get_response(request)
        except httpx.RequestError:
            # Views can still surface backend outages after auth succeeds, so keep the same 503 fallback here.
            return self._service_unavailable_response(request)

    def _redirect_for_profile(self, profile):
        role = profile.get("role")
        if role == "Admin":
            return redirect("/admin/donors/")
        if role == "TUAB":
            return redirect("tuab_dashboard")
        return redirect("donor_browse_businesses")

    def _service_unavailable_response(self, request):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"error": "Service unavailable."}, status=503)
        return render(request, "frontend/503.html", status=503)
