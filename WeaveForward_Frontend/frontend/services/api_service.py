import logging
import os
import time

import httpx
from asgiref.sync import sync_to_async

from ..constants import BACKEND_BASE_URL


logger = logging.getLogger(__name__)



class _RequestsShim:
    """Compatibility shim so older tests can patch requests.request."""

    request = None


requests = _RequestsShim()


async_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    cookies=None,
)
# Disable cookie merging in the shared client jar.
# httpx._send_single_request calls set_cookie_header (overwrites the Cookie
# header with jar contents) and extract_cookies (writes response Set-Cookie
# into the jar).  Under concurrent requests users would pick up each other's
# auth cookies, so both are made no-ops.  We pass all needed cookies explicitly
# via the cookies= kwarg and read response cookies directly from response.cookies.
async_client._cookies.set_cookie_header = lambda _request: None
async_client._cookies.extract_cookies = lambda _response: None






async def api_call(request, method, endpoint, **kwargs):
    """
    Use this function when calling the backend; it handles csrf and token refresh.
    """
    if csrf_token := request.COOKIES.get("csrftoken"):
        kwargs.setdefault("headers", {}).setdefault("X-CSRFToken", csrf_token)

    url = f"{BACKEND_BASE_URL.rstrip('/')}/{(endpoint := endpoint.lstrip('/'))}"

    # This does the request
    response = await _dispatch_request(method, url, endpoint=endpoint, cookies=dict(request.COOKIES.items()), **kwargs)

    if response.status_code == 401 and (refresh_token := request.COOKIES.get("refresh_token")):
        try:
            refresh_cookies = {"refresh_token": refresh_token}
            refresh_headers = {}
            if csrf_token := request.COOKIES.get("csrftoken"):
                refresh_cookies["csrftoken"] = csrf_token
                refresh_headers["X-CSRFToken"] = csrf_token

            refresh_res = await _dispatch_request(
                "POST",
                f"{BACKEND_BASE_URL.rstrip('/')}/auth/token/refresh",
                endpoint="auth/token/refresh",
                cookies=refresh_cookies,
                headers=refresh_headers,
            )
            if refresh_res.status_code == 200:
                new_access = refresh_res.cookies.get("access_token")
                new_refresh = refresh_res.cookies.get("refresh_token")
                if new_access:
                    request.COOKIES["access_token"] = new_access
                if new_refresh:
                    request.COOKIES["refresh_token"] = new_refresh
                request._pending_refresh_response = refresh_res

                # Retry original request with new cookies inlined
                response = await _dispatch_request(method, url, endpoint=endpoint, cookies=dict(request.COOKIES.items()), **kwargs)
            elif hasattr(request, "session") and "user_profile" in request.session:
                del request.session["user_profile"]
        except httpx.RequestError:
            raise

    return response


def apply_backend_auth_cookies(frontend_response, backend_response):
    cookie_source = getattr(backend_response.cookies, "jar", backend_response.cookies)
    for backend_cookie in cookie_source:
        if backend_cookie.name not in ("access_token", "refresh_token", "csrftoken"):
            continue

        max_age = None
        if backend_cookie.expires is not None:
            max_age = max(int(backend_cookie.expires - time.time()), 0)

        frontend_response.set_cookie(
            backend_cookie.name,
            backend_cookie.value,
            httponly=True,
            secure=backend_cookie.secure,
            samesite=backend_cookie._rest.get("SameSite", "Lax"),
            path="/",
            max_age=max_age,
        )


async def _dispatch_request(method, url, endpoint, **kwargs):
    if callable(requests.request):
        return await sync_to_async(requests.request)(method, url, **kwargs)
    try:
        return await async_client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        logger.warning("Backend request failed", extra={"endpoint": endpoint, "method": method.upper(), "error": repr(exc)})
        raise
