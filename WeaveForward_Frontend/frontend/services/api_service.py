import time

import requests
from ..constants import BACKEND_BASE_URL


def api_call(request, method, endpoint, **kwargs):
    """
    Make a backend request using the browser's cookies as the auth source.
    Includes automatic 401 handling (token refresh and retry).
    """
    headers = kwargs.pop('headers', {})
    method = method.upper()
    csrf_token = request.COOKIES.get('csrftoken')

    if method not in {'GET', 'HEAD', 'OPTIONS', 'TRACE'} and csrf_token and 'X-CSRFToken' not in headers:
        headers['X-CSRFToken'] = csrf_token

    kwargs['headers'] = headers
    kwargs['cookies'] = dict(request.COOKIES.items())

    endpoint = endpoint.lstrip('/')
    url = f"{BACKEND_BASE_URL.rstrip('/')}/{endpoint}"

    # First Attempt
    response = requests.request(method, url, **kwargs)

    # If Unauthorized (Expired Access Token), attempt silent refresh
    # We skip this if the endpoint is already the refresh endpoint to avoid loops.
    if response.status_code == 401 and endpoint != 'token/refresh':
        refresh_res = _attempt_internal_refresh(request)
        if refresh_res and refresh_res.status_code == 200:
            # Update the cookies for the retry attempt
            kwargs['cookies'] = dict(request.COOKIES.items())
            # Second Attempt (Retry)
            response = requests.request(method, url, **kwargs)
            # NOTE: If multiple api_calls in the same request each trigger a refresh,
            # the last one's _pending_refresh_response wins. This is correct because
            # the last refresh always holds the most recent token.
        else:
            # Refresh failed (e.g. Refresh Token also expired or user archived)
            # Kill the profile cache immediately
            if hasattr(request, 'session') and 'user_profile' in request.session:
                del request.session['user_profile']

    return response


def _attempt_internal_refresh(request):
    """
    Helper to refresh the session and store the new cookies on the request.
    Returns the backend response from the /token/refresh call.
    """
    refresh_token = request.COOKIES.get('refresh_token')
    if not refresh_token:
        return None

    url = f"{BACKEND_BASE_URL.rstrip('/')}/token/refresh"
    try:
        # Use simple requests here to avoid recursion with api_call
        res = requests.request('POST', url, cookies={'refresh_token': refresh_token})
        if res.status_code == 200:
            # Update the request object's cookies so subsequent api_calls in the same request use the new token
            new_access = res.cookies.get('access_token')
            new_refresh = res.cookies.get('refresh_token')
            # WARNING: Intentional mutation of request.COOKIES for retry propagation.
            # Django's request.COOKIES is a plain dict — we mutate it so that subsequent
            # api_call invocations within the same request cycle use the refreshed tokens
            # without needing to pass state explicitly.
            if new_access:
                request.COOKIES['access_token'] = new_access
            if new_refresh:
                request.COOKIES['refresh_token'] = new_refresh
            
            # Store this response on the request so middleware can apply cookies to the FINAL response sent to browser
            request._pending_refresh_response = res
        return res
    except Exception:
        return None


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
