import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from .constants import ALLOWED_FIBERS, BACKEND_BASE_URL
from .services.form_utils import format_errors

def role_select(request):
    return render(request, 'frontend/role_select.html')

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        otp_code = request.POST.get('otp_code')
        
        try:
            response = requests.post(f"{BACKEND_BASE_URL}login/", json={
                'email': email,
                'password': password,
                'otp_code': otp_code
            })
            
            if response.status_code == 200:
                data = response.json()
                res = render(request, 'frontend/home.html') # Render dashboard immediately
                
                # Set HttpOnly cookies for tokens
                res.set_cookie('access_token', data['access'], httponly=True, samesite='Lax')
                res.set_cookie('refresh_token', data['refresh'], httponly=True, samesite='Lax')
                
                # Set plain cookies for UI data
                res.set_cookie('user_role', data['role'], samesite='Lax')
                res.set_cookie('user_name', data['name'], samesite='Lax')
                res.set_cookie('user_email', data['email'], samesite='Lax')
                
                return res
            else:
                # Handle login failure
                error_data = response.json()
                
                # Check for 2FA requirement
                if error_data.get('2fa_required'):
                    return render(request, 'frontend/login.html', {
                        'show_2fa': True, 
                        'email': email, 
                        'password': password
                    })

                backend_error = error_data.get('detail', 'Invalid email or password.')
                error_msg = backend_error[0] if isinstance(backend_error, list) else backend_error
                return render(request, 'frontend/login.html', {'error': error_msg, 'email': email})
                
        except requests.exceptions.ConnectionError:
            return render(request, 'frontend/login.html', {'error': 'Backend API is offline.'})

    # GET request - If we have an access token (or the middleware just refreshed it),
    # we show the home (dashboard). Otherwise, show login.
    if request.COOKIES.get('access_token'):
        return render(request, 'frontend/home.html')
    
    return render(request, 'frontend/login.html')

def logout_view(request):
    access_token = request.COOKIES.get('access_token')
    refresh_token = request.COOKIES.get('refresh_token')
    
    if access_token and refresh_token:
        try:
            # Tell backend to blacklist the refresh token
            requests.post(
                f"{BACKEND_BASE_URL}logout/",
                json={'refresh': refresh_token},
                headers={'Authorization': f'Bearer {access_token}'}
            )
        except Exception:
            pass # Proceed with local logout regardless

    response = redirect('login')
    # Clean up all cookies on the browser
    for cookie in ['access_token', 'refresh_token', 'user_role', 'user_name', 'user_email']:
        response.delete_cookie(cookie)
    
    messages.success(request, "Successfully logged out.")
    return response

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
                return redirect('login')
            else:
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
                return redirect('login')
            else:
                return render(request, 'frontend/tuab_registration.html', {
                    'errors': format_errors(response.json()),
                    'form_data': raw_data,
                    'fibers': ALLOWED_FIBERS
                })
        except requests.exceptions.ConnectionError:
            messages.error(request, "Backend API is offline.")

    return render(request, 'frontend/tuab_registration.html', {'fibers': ALLOWED_FIBERS})
