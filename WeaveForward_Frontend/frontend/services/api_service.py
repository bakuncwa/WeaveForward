import logging
import httpx
from ..constants import BACKEND_BASE_URL

logger = logging.getLogger(__name__)


async_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
)
# Disable cookie merging under concurrent requests
async_client._cookies.set_cookie_header = lambda _request: None
async_client._cookies.extract_cookies = lambda _response: None


async def api_call(request, method, endpoint, **kwargs):
    if csrf_token := request.COOKIES.get("csrftoken"):
        kwargs.setdefault("headers", {}).setdefault("X-CSRFToken", csrf_token)

    url = f"{BACKEND_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    cookies = dict(request.COOKIES.items())
    response = await async_client.request(method, url, cookies=cookies, **kwargs)

    if response.status_code == 401:
        request._session_expired = True

    return response
