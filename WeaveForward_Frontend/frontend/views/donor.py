from django.shortcuts import render, redirect
from django.contrib import messages
from ..services import api_call, get_user_profile, format_errors

def donor_dashboard(request):
    """Placeholder for Donor Dashboard."""
    profile = get_user_profile(request)
    if not profile: return redirect('login')
    
    return render(request, 'frontend/base.html', {
        'page_title': 'Donor Dashboard', 
        'user': profile
    })


