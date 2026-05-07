from .api_service import api_call

def get_user_profile(request):
    """
    Fetches the current user's profile from the backend.
    """
    response = api_call(request, 'GET', 'users/me/')
    if response.status_code == 200:
        return response.json()
    return None
