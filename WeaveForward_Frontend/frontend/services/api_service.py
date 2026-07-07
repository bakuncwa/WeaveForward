import logging
import httpx
from ..constants import BACKEND_BASE_URL

logger = logging.getLogger(__name__)

async_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=10.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
)
# Disable cookie merging under concurrent requests
async_client._cookies.set_cookie_header = lambda _request: None
async_client._cookies.extract_cookies = lambda _response: None


async def api_call(request, method, endpoint, **kwargs):
    headers = kwargs.setdefault("headers", {})

    if csrf_token := request.COOKIES.get("csrftoken"):
        headers.setdefault("X-CSRFToken", csrf_token)
        headers.setdefault("Referer", BACKEND_BASE_URL)

    # Forward the original client IP chain to the backend.
    if forwarded_for := request.META.get("HTTP_X_FORWARDED_FOR"):
        headers.setdefault("X-Forwarded-For", forwarded_for)
    elif remote_addr := request.META.get("REMOTE_ADDR"):
        headers.setdefault("X-Forwarded-For", remote_addr)

    url = f"{BACKEND_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    cookies = dict(request.COOKIES.items())
    response = await async_client.request(method, url, cookies=cookies, **kwargs)
    if (
        response.status_code == 503
        and response.headers.get("server", "").lower() == "google frontend"
        and "text/html" in response.headers.get("content-type", "").lower()
        and "Service is disabled" in response.text
    ):
        raise httpx.RequestError("Backend unavailable.", request=response.request)

    if (
        response.status_code == 401
        and getattr(request, "user_profile", None)
        and endpoint.lstrip("/").split("?", 1)[0] != "auth/token/refresh"
    ):
        raise PermissionError("Backend unauthorized.")

    return response
