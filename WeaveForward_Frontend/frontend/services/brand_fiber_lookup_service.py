from .api_service import api_call
from ..constants import ALLOWED_FIBERS

async def get_fiber_choices(request):
    """Helper to fetch unique fibers from backend with a fallback."""
    try:
        response = await api_call(request, 'GET', 'brandfiberlookups/fibers')
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return ALLOWED_FIBERS

