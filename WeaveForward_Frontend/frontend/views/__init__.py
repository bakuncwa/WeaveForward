import json
import logging
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponseNotAllowed
from django.contrib import messages
from django.urls import reverse
from ..services import (
    api_call,
    format_errors,
    get_fiber_choices,
)
from ..middleware import apply_backend_auth_cookies

from ..constants import ALLOWED_FIBERS

# Import role-based views for convenience
from .admin import admin_view_donations, admin_view_donors, admin_view_tuabs, admin_view_tuab, admin_add_donor, admin_add_tuab, admin_view_donor, admin_edit_donor, admin_archive_user_proxy, admin_edit_tuab, admin_add_donation, admin_view_donation, admin_edit_donation, admin_cancel_donation, admin_archive_donation, admin_impact_dashboard, admin_view_payments, admin_circular_economy
from .donor import donor_browse_businesses, donor_my_donations, donor_view_donation, donor_view_tuab, donor_create_donation, donor_profile, donor_edit_profile, donor_edit_donation, donor_cancel_donation, donor_impact_dashboard
from .tuab import (
    tuab_dashboard,
    tuab_edit_profile,
    tuab_profile,
    tuab_subscribe,
    tuab_subscription_status,
    tuab_view_donation,
    tuab_quotation_proxy,
    tuab_update_incoming_donation,
    tuab_view_payments,
    tuab_inventory_snapshot,
    tuab_view_audit_history,
    tuab_inventory_update_usage_proxy,
    tuab_inventory_archive_proxy,
    tuab_inventory_restore_proxy,
    tuab_inventory_export_proxy,
    tuab_view_fiber_match_recommendations,
    tuab_match_recommendation_accept_proxy,
    tuab_match_recommendation_reject_proxy,
    tuab_donation_flag_proxy,
    tuab_circular_economy,
)

async def two_factor_setup_proxy(request):
    """Proxy to generate 2FA secret for the logged-in user."""
    response = await api_call(request, 'POST', 'users/me/2fa/setup')
    return JsonResponse(response.json(), status=response.status_code)

async def two_factor_verify_proxy(request):
    """Proxy to verify and enable 2FA for the logged-in user."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    data = json.loads(request.body)
    response = await api_call(request, 'POST', 'users/me/2fa', json=data)
    return JsonResponse(response.json(), status=response.status_code)

async def tuab_unsubscribe_proxy(request):
    """Proxy to unsubscribe the logged-in TUAB from premium."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    response = await api_call(request, 'DELETE', 'users/me/subscription')
    return JsonResponse(response.json(), status=response.status_code)


async def two_factor_disable_proxy(request):
    """Proxy to disable 2FA for the logged-in user."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    response = await api_call(request, 'DELETE', 'users/me/2fa')
    return JsonResponse(response.json(), status=response.status_code)

async def role_select(request):
    return render(request, 'frontend/role_select.html')

async def login_view(request):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        otp_code = request.POST.get('otp_code')
        
        payload = {'email': email, 'password': password}
        if otp_code:
            payload['otp_code'] = otp_code
        
        try:
            response = await api_call(request, 'POST', 'auth/token', json=payload)
            
            if response.status_code == 200:
                data = response.json()
                role = data.get('role')
                if role == 'Admin':
                    redirect_name = 'admin_view_donors'
                elif role == 'TUAB':
                    redirect_name = 'tuab_dashboard'
                else:
                    redirect_name = 'donor_browse_businesses'

                redirect_url = reverse(redirect_name)

                if is_ajax:
                    res = JsonResponse({'redirect_url': redirect_url}, status=200)
                else:
                    res = redirect(redirect_name)

                apply_backend_auth_cookies(res, response)
                return res
            else:
                error_data = response.json()
                if error_data.get('2fa_required'):
                    if is_ajax:
                        return JsonResponse({
                            '2fa_required': True,
                            'email': email,
                        }, status=401)

                    return render(request, 'frontend/login.html', {
                        'show_2fa': True,
                        'email': email,
                        'password': password
                    })

                backend_error = error_data.get('detail', 'Invalid email or password.')
                error_msg = backend_error[0] if isinstance(backend_error, list) else backend_error
                if 'under review' in error_msg.lower():
                    if is_ajax:
                        return JsonResponse({'under_review': True, 'error': error_msg}, status=401)
                    return render(request, 'frontend/login.html', {'under_review': True, 'error': error_msg})
                if is_ajax:
                    return JsonResponse({'error': error_msg}, status=response.status_code)
                return render(request, 'frontend/login.html', {'error': error_msg, 'email': email})
                
        except Exception:
            if is_ajax:
                return JsonResponse({'error': 'Service is temporarily unavailable. Please try again.'}, status=503)
            return render(request, 'frontend/login.html', {'error': 'Service is temporarily unavailable. Please try again.'})

    ctx = {}
    if request.GET.get('under_review'):
        ctx['under_review'] = True
        ctx['error'] = 'Your account is still under review.'
    return render(request, 'frontend/login.html', ctx)

async def logout_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        response = await api_call(request, 'DELETE', 'auth/token')
    except Exception:
        messages.error(request, "Logout could not be completed right now. Please try again.")
        return redirect(request.META.get('HTTP_REFERER') or reverse('login'))

    if response.status_code == 205:
        frontend_response = redirect('login')
        for c in ("access_token", "refresh_token", "user_role", "user_name", "user_email"):
            frontend_response.delete_cookie(c, path="/")
        request.session.flush()  # Wipe cached profile to prevent stale data on next login
        messages.success(request, "Successfully logged out.")
        return frontend_response

    try:
        error_data = response.json()
    except Exception:
        error_data = {}

    error_message = error_data.get('detail') or "Logout failed. Please try again."
    if isinstance(error_message, list):
        error_message = error_message[0]

    messages.error(request, error_message)
    return redirect(request.META.get('HTTP_REFERER') or reverse('login'))

async def location_lookup_proxy(request):
    """SSR Proxy for location lookup."""
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    response = await api_call(request, 'GET', 'location/lookup', params={'lat': lat, 'lng': lng})
    return JsonResponse(response.json(), status=response.status_code)

async def material_clothing_types_proxy(request):
    """SSR Proxy for fetching unique clothing types."""
    response = await api_call(request, 'GET', 'clothing-types')
    return JsonResponse(response.json(), status=response.status_code, safe=False)

async def material_brands_proxy(request):
    """SSR Proxy for fetching brands by clothing type."""
    clothing_type = request.GET.get('clothing_type')
    response = await api_call(request, 'GET', 'brands', params={'clothing_type': clothing_type})
    return JsonResponse(response.json(), status=response.status_code, safe=False)

async def material_search_proxy(request):
    """SSR Proxy for searching materials/items."""
    response = await api_call(request, 'GET', 'brandfiberlookups', params=request.GET.dict())
    return JsonResponse(response.json(), status=response.status_code, safe=False)

async def donor_search_proxy(request):
    """SSR Proxy for searching active donors only."""
    params = {'nopaginate': 'true', 'role': 'Donor', 'status': 'ACTIVE'}
    if request.GET.get('search'):
        params['search'] = request.GET['search']
    response = await api_call(request, 'GET', 'users', params=params)
    return JsonResponse(response.json(), status=response.status_code, safe=False)

async def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            response = await api_call(
                request,
                'POST',
                'auth/password-reset',
                json={'email': email},
                headers={
                    'X-Frontend-Redirect-Url': request.build_absolute_uri('/').rstrip('/'),
                },
            )
            if response.status_code == 200:
                return render(request, 'frontend/forgot_password.html', {'success': "If that email exists in our system, we've sent a password reset link to it."})
            else:
                data = response.json()
                error_msg = data.get('email', data.get('error', ['Error requesting reset.']))
                if isinstance(error_msg, list): error_msg = error_msg[0]
                return render(request, 'frontend/forgot_password.html', {'error': error_msg})
        except Exception:
            return render(request, 'frontend/forgot_password.html', {'error': "Backend service unreachable."})
    return render(request, 'frontend/forgot_password.html')

async def reset_password_confirm(request):
    if request.method == 'GET':
        uidb64 = request.GET.get('uidb64')
        token = request.GET.get('token')
        if not uidb64 or not token:
            return redirect('login')
        return render(request, 'frontend/reset_password_confirm.html', {'uidb64': uidb64, 'token': token})

    if request.method == 'POST':
        uidb64 = request.POST.get('uidb64')
        token = request.POST.get('token')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        payload = {
            'uidb64': uidb64,
            'token': token,
            'new_password': new_password
        }

        try:
            response = await api_call(request, 'POST', 'auth/password-reset/confirmation', json=payload)
            if response.status_code == 200:
                messages.success(request, "Password reset successful! 2FA has been disabled. You can now log in.")
                return redirect('login')
            else:
                errors = response.json()
                error_msg = "Invalid data."
                if 'password' in errors: error_msg = errors['password'][0]
                elif 'token' in errors: error_msg = errors['token'][0]
                elif 'non_field_errors' in errors: error_msg = errors['non_field_errors'][0]
                
                return render(request, 'frontend/reset_password_confirm.html', {
                    'error': error_msg,
                    'uidb64': uidb64,
                    'token': token
                })
        except Exception:
                return render(request, 'frontend/reset_password_confirm.html', {
                    'error': "Backend service unreachable.",
                    'uidb64': uidb64,
                    'token': token
                })

async def verify_email(request):
    if request.method == 'GET':
        return render(request, 'frontend/verify_email.html')

    if request.method == 'POST':
        data = json.loads(request.body)
        response = await api_call(request, 'POST', 'auth/verify-email', json=data)
        result = response.json()
        if response.status_code == 200:
            return JsonResponse(result, status=200)
        return JsonResponse(result, status=response.status_code)

async def resend_verification_email(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    data = json.loads(request.body)
    response = await api_call(
        request,
        'POST',
        'auth/resend-verification',
        json=data,
        headers={'X-Frontend-Redirect-Url': request.build_absolute_uri('/').rstrip('/')},
    )
    return JsonResponse(response.json(), status=response.status_code)

async def donor_registration(request):
    if request.method == 'POST':
        raw_data = request.POST
        password = raw_data.get('password')
        confirm_password = raw_data.get('confirm_password')

        if password != confirm_password:
            return JsonResponse({'errors': {'password': ['Passwords do not match.']}, 'form_data': dict(raw_data)})

        lat = raw_data.get('latitude') or 0
        lng = raw_data.get('longitude') or 0
        payload = {
            'role': 'Donor',
            'first_name': raw_data.get('first_name'),
            'middle_name': raw_data.get('middle_name'),
            'last_name': raw_data.get('last_name'),
            'email': raw_data.get('email'),
            'password': raw_data.get('password'),
            'contact_no': raw_data.get('contact_no', ''),
            'display_address': raw_data.get('display_address'),
            'latitude': "{:.7f}".format(float(lat)),
            'longitude': "{:.7f}".format(float(lng)),
            'city': raw_data.get('city'),
            'barangay': raw_data.get('barangay')
        }
        if payload['contact_no'].startswith('0'):
            payload['contact_no'] = '+63' + payload['contact_no'][1:]
        elif not payload['contact_no'].startswith('+'):
            payload['contact_no'] = '+63' + payload['contact_no']
        try:
            response = await api_call(
                request,
                'POST',
                'users',
                json=payload,
                headers={
                    'X-Frontend-Redirect-Url': request.build_absolute_uri('/').rstrip('/'),
                },
            )
            if response.status_code == 201:
                messages.success(request, "Registration successful! Please check your email for a verification link before logging in.")
                return JsonResponse({'redirect': reverse('login')})
            else:
                return JsonResponse({'errors': format_errors(response.json()), 'form_data': dict(raw_data)})
        except Exception:
            return JsonResponse({'errors': {'__all__': ['Service is temporarily unavailable. Please try again.']}})
    return render(request, 'frontend/donor_registration.html')

async def tuab_registration(request):
    fibers = await get_fiber_choices(request)
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        raw_data = request.POST
        password = raw_data.get('password')
        confirm_password = raw_data.get('confirm_password')

        if password != confirm_password:
            if is_ajax:
                return JsonResponse({'errors': {'password': ['Passwords do not match.']}, 'error_step': 1, 'form_data': dict(raw_data)})
            return render(request, 'frontend/tuab_registration.html', {
                'errors': {'password': ["Passwords do not match."]},
                'error_step': 1,
                'form_data': raw_data,
                'fibers': fibers
            })

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

        payload = {
            'role': 'TUAB',
            'business_name': raw_data.get('business_name'),
            'description': raw_data.get('description'),
            'email': raw_data.get('email'),
            'contact_no': contact_no,
            'password': raw_data.get('password'),
            'display_address': raw_data.get('display_address'),
            'latitude': "{:.7f}".format(float(lat)),
            'longitude': "{:.7f}".format(float(lng)),
            'city': raw_data.get('city'),
            'barangay': raw_data.get('barangay'),
            'target_fibers': target_fibers,
            'max_distance_km': max_distance_km,
            'min_biodeg_score': min_biodeg_score,
            'social_link': raw_data.get('social_link') or None
        }

        files = {'documentation': request.FILES.get('documentation')} if request.FILES.get('documentation') else None

        try:
            response = await api_call(
                request,
                'POST',
                'users',
                data=payload,
                files=files,
                headers={
                    'X-Frontend-Redirect-Url': request.build_absolute_uri('/').rstrip('/'),
                },
            )
            if response.status_code == 201:
                response_data = response.json()
                success_message = response_data.get('message', "TUAB Application Submitted! Please check your email for a verification link.")
                if is_ajax:
                    messages.success(request, success_message)
                    return JsonResponse({'redirect': reverse('login'), 'message': success_message})
                messages.success(request, success_message)
                return redirect('login')
            else:
                try:
                    resp_json = response.json()
                    logging.warning(f"TUAB_REG_DEBUG status={response.status_code} body={json.dumps(resp_json)}")
                except Exception as e:
                    logging.warning(f"TUAB_REG_DEBUG status={response.status_code} body_unparseable={e} text={response.text[:500]}")
                errors = format_errors(response.json())
                _step1 = {'email', 'password', 'contact_no', 'business_name'}
                _step2 = {'display_address', 'latitude', 'longitude', 'city', 'barangay',
                          'target_fibers', 'max_distance_km', 'min_biodeg_score', 'description', 'social_link'}
                err_keys = set(errors.keys())
                if err_keys & _step1:
                    error_step = 1
                elif err_keys & _step2:
                    error_step = 2
                else:
                    error_step = 3
                if is_ajax:
                    return JsonResponse({'errors': errors, 'error_step': error_step, 'form_data': dict(raw_data)})
                return render(request, 'frontend/tuab_registration.html', {
                    'errors': errors,
                    'error_step': error_step,
                    'form_data': raw_data,
                    'fibers': fibers
                })
        except Exception:
            if is_ajax:
                return JsonResponse({'errors': {'__all__': ['Service is temporarily unavailable. Please try again.']}})
            messages.error(request, "Service is temporarily unavailable. Please try again.")

    return render(request, 'frontend/tuab_registration.html', {'fibers': fibers})
