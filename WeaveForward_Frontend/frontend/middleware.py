import requests
import base64
import json
import time
from django.shortcuts import redirect
from .constants import BACKEND_BASE_URL

def is_token_expired(token):
    """Checks if a JWT token is expired."""
    if not token:
        return True
    try:
        _, payload_b64, _ = token.split('.')
        missing_padding = len(payload_b64) % 4
        if missing_padding:
            payload_b64 += '=' * (4 - missing_padding)
        payload = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
        return payload.get('exp', 0) < (time.time() + 5)
    except Exception:
        return True

class JWTSessionMiddleware:
    """Handles automatic token refreshing and session cleanup."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        access_token = request.COOKIES.get('access_token')
        refresh_token = request.COOKIES.get('refresh_token')

        if is_token_expired(access_token):
            if is_token_expired(refresh_token):
                request._auth_failed = True
            else:
                try:
                    response = requests.post(
                        f"{BACKEND_BASE_URL}token/refresh/", 
                        json={'refresh': refresh_token},
                        timeout=5
                    )
                    if response.status_code == 200:
                        new_access = response.json().get('access')
                        request.COOKIES['access_token'] = new_access
                        request._new_access_token = new_access
                    else:
                        request._auth_failed = True
                except Exception:
                    pass

        response = self.get_response(request)

        if hasattr(request, '_new_access_token'):
            response.set_cookie('access_token', request._new_access_token, httponly=True, samesite='Lax')
            
        if hasattr(request, '_auth_failed') and (access_token or refresh_token):
            for cookie in ['access_token', 'refresh_token', 'user_role', 'user_name', 'user_email']:
                response.delete_cookie(cookie)
            if request.path != '/':
                return redirect('login')

        return response

class GuestOnlyMiddleware:
    """Redirects authenticated users away from registration/login pages."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # We check the updated access_token (in case the JWTSessionMiddleware just refreshed it)
        access_token = request.COOKIES.get('access_token')
        
        guest_only_paths = ['/select-role/', '/register/donor/', '/register/tuab/']
        
        # If the user is authenticated, bounce them away from guest-only pages
        if not is_token_expired(access_token) and request.path in guest_only_paths:
            return redirect('login')

        return self.get_response(request)
