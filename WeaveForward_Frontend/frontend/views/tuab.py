from django.shortcuts import render, redirect
from django.contrib import messages
from ..services import api_call, get_user_profile, format_errors
from ..constants import ALLOWED_FIBERS

def tuab_dashboard(request):
    """Placeholder for TUAB Dashboard."""
    profile = get_user_profile(request)
    if not profile: return redirect('login')

    return render(request, 'frontend/base.html', {
        'page_title': 'TUAB Dashboard', 
        'user': profile
    })


