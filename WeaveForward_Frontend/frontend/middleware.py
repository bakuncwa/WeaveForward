import time
import jwt
import httpx
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import JsonResponse
from django.shortcuts import redirect, render

from .constants import TEXT_FIELD_MAX_LENGTH
from .services import api_call

AUTH_COOKIE_NAMES = ("access_token", "refresh_token", "user_role", "user_name", "user_email")

PROTECTED_PREFIXES = (
    "/donor/",
    "/tuab/",
    "/admin/",
    "/api/2fa/",
    "/api/materials/",
    "/api/donors/",
    "/api/tuab/",
)
GUEST_ONLY_PATHS = {
    "/",
    "/select-role/",
    "/register/donor/",
    "/register/tuab/",
    "/forgot-password/",
    "/reset-password-confirm/",
    "/verify-email/",
}
PUBLIC_PASSTHROUGH_PATHS = {"/api/location/lookup/", "/logout/"}


class QueryStringLengthLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if len(request.META.get("QUERY_STRING", "")) > TEXT_FIELD_MAX_LENGTH:
            message = f"Query string must be no more than {TEXT_FIELD_MAX_LENGTH} characters."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
                return JsonResponse({"detail": message}, status=400)

            return render(request, "frontend/400.html", {"message": message}, status=400)

        return self.get_response(request)


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

    @staticmethod
    def _decode_token(token):
        try:
            return jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        except jwt.DecodeError:
            return None

    async def _process_request(self, request):
        path = request.path
        request.user_profile = None

        if path in PUBLIC_PASSTHROUGH_PATHS:
            return await self.get_response(request)

        # 1. Block protected routes for unauthenticated users immediately
        has_token = request.COOKIES.get("access_token") or request.COOKIES.get("refresh_token")
        if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) and not has_token:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"error": "Your session has expired or your account is no longer active. Please log in again."},
                    status=401,
                )
            return redirect("login")

        # 2. Verify credentials if cookies are present
        if has_token:
            try:
                payload = None
                access_token = request.COOKIES.get("access_token")

                if access_token:
                    payload = self._decode_token(access_token)
                    if payload and payload.get("exp", 0) < time.time():
                        payload = None

                # Token expired or missing — try refresh
                if not payload and request.COOKIES.get("refresh_token"):
                    refresh_res = await api_call(request, "POST", "auth/token/refresh")
                    if refresh_res.status_code == 200:
                        for token_name in ("access_token", "refresh_token"):
                            if token_val := refresh_res.cookies.get(token_name):
                                request.COOKIES[token_name] = token_val
                        request._pending_refresh_response = refresh_res
                        new_token = request.COOKIES.get("access_token")
                        payload = self._decode_token(new_token) if new_token else None
                    elif hasattr(request, "session") and "user_profile" in request.session:
                        del request.session["user_profile"]

                if payload:
                    request.user_profile = {
                        'user_id': int(payload.get('user_id')) if payload.get('user_id') is not None else None,
                        'role': payload.get('role'),
                        'status': payload.get('status'),
                        'upload': payload.get('upload'),
                        'created_at': payload.get('created_at'),
                        'first_name': payload.get('first_name', ''),
                        'last_name': payload.get('last_name', ''),
                        'business_name': payload.get('business_name', ''),
                        'is_subscribed': payload.get('is_subscribed', False),
                        'has_billing': payload.get('has_billing', False),
                    }
                else:
                    request.session.pop("user_profile", None)
                    if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
                        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                            response = JsonResponse(
                                {"error": "Your session has expired or your account is no longer active. Please log in again."},
                                status=401,
                            )
                        else:
                            response = redirect("login")
                        for c in AUTH_COOKIE_NAMES:
                            response.delete_cookie(c, path="/")
                        return response
                    response = await self.get_response(request)
                    for c in AUTH_COOKIE_NAMES:
                        response.delete_cookie(c, path="/")
                    return response
            except httpx.RequestError:
                if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES) or path in GUEST_ONLY_PATHS:
                    return JsonResponse({"error": "Service unavailable."}, status=503) if request.headers.get("X-Requested-With") == "XMLHttpRequest" else render(request, "frontend/503.html", status=503)
                return await self.get_response(request)

        # 3. Redirect authenticated users away from guest pages or unauthorized role prefixes
        if request.user_profile:
            role = request.user_profile.get("role")
            if role is None:
                response = redirect("login")
                for c in AUTH_COOKIE_NAMES:
                    response.delete_cookie(c, path="/")
                return response
            elif (path in GUEST_ONLY_PATHS) or \
                 (path.startswith("/admin/") and role != "Admin") or \
                 (path.startswith("/tuab/") and role != "TUAB") or \
                 (path.startswith("/donor/") and role != "Donor"):
                return redirect("/admin/donors/" if role == "Admin" else "tuab_dashboard" if role == "TUAB" else "donor_browse_businesses")

        response = await self.get_response(request)
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, httpx.RequestError):
            return JsonResponse({"error": "Service unavailable."}, status=503) if request.headers.get("X-Requested-With") == "XMLHttpRequest" else render(request, "frontend/503.html", status=503)
        if isinstance(exception, PermissionError):
            response = JsonResponse(
                {"error": "Your session has expired or your account is no longer active. Please log in again."},
                status=401,
            ) if request.headers.get("X-Requested-With") == "XMLHttpRequest" else redirect("login")
            for c in AUTH_COOKIE_NAMES:
                response.delete_cookie(c, path="/")
            return response
        return None


def apply_backend_auth_cookies(frontend_response, backend_response):
    cookie_source = getattr(backend_response.cookies, "jar", backend_response.cookies)
    for c in cookie_source:
        if c.name in ("access_token", "refresh_token", "csrftoken"):
            max_age = max(int(c.expires - time.time()), 0) if c.expires is not None else None
            frontend_response.set_cookie(
                c.name,
                c.value,
                httponly=True,
                secure=c.secure,
                samesite=c._rest.get("SameSite", "Lax"),
                path="/",
                max_age=max_age,
            )
