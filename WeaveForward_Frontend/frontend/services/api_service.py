import requests
from ..constants import BACKEND_BASE_URL

def api_call(request, method, endpoint, **kwargs):
    """
    A short, intuitive helper for making authenticated requests to the backend.
    Automatically attaches the JWT access token from the user's cookies.
    
    Usage: 
        response = api_call(request, 'GET', 'donations/')
        response = api_call(request, 'POST', 'donations/', json={'data': 'value'})
    """
    access_token = request.COOKIES.get('access_token')
    
    # Ensure headers exist in kwargs
    headers = kwargs.pop('headers', {})
    
    # Automatically attach the Bearer token if it exists
    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'
    
    # Merge headers back into kwargs
    kwargs['headers'] = headers
    
    # Clean endpoint to prevent double slashes
    endpoint = endpoint.lstrip('/')
    url = f"{BACKEND_BASE_URL}{endpoint}"
    
    return requests.request(method, url, **kwargs)
