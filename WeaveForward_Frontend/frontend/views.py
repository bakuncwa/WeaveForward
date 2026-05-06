import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from .constants import ALLOWED_FIBERS, BACKEND_BASE_URL
from .services.form_utils import format_errors

def home(request):
    return render(request, 'frontend/home.html')

def role_select(request):
    return render(request, 'frontend/role_select.html')

def location_lookup_proxy(request):
    """SSR Proxy for location lookup."""
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    try:
        response = requests.get(f"{BACKEND_BASE_URL}location/lookup/", params={'lat': lat, 'lng': lng})
        return JsonResponse(response.json(), status=response.status_code)
    except Exception:
        return JsonResponse({'error': 'Backend location service unreachable'}, status=503)

def donor_registration(request):
    if request.method == 'POST':
        raw_data = request.POST
        lat = raw_data.get('latitude') or 0
        lng = raw_data.get('longitude') or 0
        payload = {
            'role': 'Donor',
            'first_name': raw_data.get('first_name'),
            'last_name': raw_data.get('last_name'),
            'email': raw_data.get('email'),
            'password': raw_data.get('password'),
            'confirm_password': raw_data.get('confirm_password') or raw_data.get('password'),
            'contact_no': raw_data.get('contact_no', ''),
            'display_address': raw_data.get('display_address'),
            'latitude': "{:.7f}".format(float(lat)),
            'longitude': "{:.7f}".format(float(lng))
        }
        if payload['contact_no'].startswith('0'):
            payload['contact_no'] = '+63' + payload['contact_no'][1:]
        elif not payload['contact_no'].startswith('+'):
            payload['contact_no'] = '+63' + payload['contact_no']
        try:
            response = requests.post(f"{BACKEND_BASE_URL}register/", json=payload)
            if response.status_code == 201:
                messages.success(request, "Registration successful!")
                return redirect('home')
            else:
                # Safely print a snippet of the error to avoid UnicodeEncodeError on Windows
                error_snippet = (response.text[:200] + '...') if len(response.text) > 200 else response.text
                print(f"DEBUG: Donor Error {response.status_code}: {error_snippet.encode('ascii', 'replace').decode('ascii')}")
                return render(request, 'frontend/donor_registration.html', {'errors': format_errors(response.json()), 'form_data': raw_data})
        except requests.exceptions.ConnectionError:
            messages.error(request, "Backend API is offline.")
    return render(request, 'frontend/donor_registration.html')

def tuab_registration(request):
    if request.method == 'POST':
        raw_data = request.POST

        # Fiber Cleaning
        target_fibers = raw_data.get('target_fibers', '').lower().replace(' ', '')

        # Phone Cleaning
        contact_no = raw_data.get('contact_no', '')
        if contact_no.startswith('0'): contact_no = '+63' + contact_no[1:]
        elif not contact_no.startswith('+'): contact_no = '+63' + contact_no

        # Coordinate Handling
        lat = raw_data.get('latitude') or 0
        lng = raw_data.get('longitude') or 0

        # Numeric Handling (Prevent empty strings)
        max_distance_km = raw_data.get('max_distance_km') or 0
        min_biodeg_score = raw_data.get('min_biodeg_score') or 0

        # URL Cleaning (Auto-prefix https:// if missing)
        social_link = raw_data.get('social_link', '').strip()
        if social_link and not social_link.startswith(('http://', 'https://')):
            social_link = 'https://' + social_link

        payload = {
            'role': 'TUAB',
            'business_name': raw_data.get('business_name'),
            'description': raw_data.get('description'),
            'email': raw_data.get('email'),
            'contact_no': contact_no,
            'password': raw_data.get('password'),
            'confirm_password': raw_data.get('confirm_password') or raw_data.get('password'),
            'display_address': raw_data.get('display_address'),
            'latitude': "{:.7f}".format(float(lat)),
            'longitude': "{:.7f}".format(float(lng)),
            'target_fibers': target_fibers,
            'max_distance_km': max_distance_km,
            'min_biodeg_score': min_biodeg_score,
            'social_link': social_link if social_link else None
        }

        files = {'documentation': request.FILES.get('documentation')} if request.FILES.get('documentation') else None

        try:
            response = requests.post(f"{BACKEND_BASE_URL}register/", data=payload, files=files)
            if response.status_code == 201:
                messages.success(request, "TUAB Application Submitted!")
                return redirect('home')
            else:
                # Safely print a snippet of the error to avoid UnicodeEncodeError on Windows
                error_snippet = (response.text[:200] + '...') if len(response.text) > 200 else response.text
                print(f"DEBUG: TUAB Error {response.status_code}: {error_snippet.encode('ascii', 'replace').decode('ascii')}")
                return render(request, 'frontend/tuab_registration.html', {
                    'errors': format_errors(response.json()),
                    'form_data': raw_data,
                    'fibers': ALLOWED_FIBERS
                })
        except requests.exceptions.ConnectionError:
            messages.error(request, "Backend API is offline.")

    return render(request, 'frontend/tuab_registration.html', {'fibers': ALLOWED_FIBERS})
