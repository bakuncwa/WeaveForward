from django.shortcuts import render, redirect
from ..services import api_call, get_user_profile

def admin_view_donations(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    response = api_call(request, 'GET', 'donations/')
    donations = response.json() if response.status_code == 200 else []
    return render(request, 'frontend/admin/admin_view_donations.html', {'page_title': 'Donations', 'user': profile, 'donations': donations})

def admin_view_donors(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    response = api_call(request, 'GET', 'users/', params={'role': 'Donor'})
    donors = response.json() if response.status_code == 200 else []
    return render(request, 'frontend/admin/admin_view_donors.html', {'page_title': 'Donors', 'user': profile, 'donors': donors})
