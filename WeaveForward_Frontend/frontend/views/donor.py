from django.shortcuts import render, redirect
from django.contrib import messages
from ..services import api_call, format_errors

def donor_dashboard(request):
    """Placeholder for Donor Dashboard."""
    profile = request.user_profile
    
    return render(request, 'frontend/base.html', {
        'page_title': 'Donor Dashboard', 
        'user': profile
    })
