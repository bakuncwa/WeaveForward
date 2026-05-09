import time

import requests
from ..constants import BACKEND_BASE_URL


def api_call(request, method, endpoint, **kwargs):
    """
    Make a backend request using the browser's cookies as the auth source.
    """
    headers = kwargs.pop('headers', {})
    method = method.upper()
    csrf_token = request.COOKIES.get('csrftoken')

    if method not in {'GET', 'HEAD', 'OPTIONS', 'TRACE'} and csrf_token and 'X-CSRFToken' not in headers:
        headers['X-CSRFToken'] = csrf_token

    kwargs['headers'] = headers
    kwargs['cookies'] = dict(request.COOKIES.items())

    endpoint = endpoint.lstrip('/')
    url = f"{BACKEND_BASE_URL}{endpoint}"

    return requests.request(method, url, **kwargs)


def apply_backend_auth_cookies(frontend_response, backend_response):
    for backend_cookie in backend_response.cookies:
        if backend_cookie.name not in ('access_token', 'refresh_token'):
            continue

        max_age = None
        if backend_cookie.expires is not None:
            max_age = max(int(backend_cookie.expires - time.time()), 0)

        frontend_response.set_cookie(
            backend_cookie.name,
            backend_cookie.value,
            httponly=True,
            secure=backend_cookie.secure,
            samesite=backend_cookie._rest.get('SameSite', 'Lax'),
            path=backend_cookie.path or '/',
            domain=backend_cookie.domain if backend_cookie.domain_specified else None,
            max_age=max_age,
        )


def clear_frontend_auth_cookies(frontend_response):
    for cookie_name in ('access_token', 'refresh_token', 'user_role', 'user_name', 'user_email'):
        frontend_response.delete_cookie(cookie_name, path='/')
