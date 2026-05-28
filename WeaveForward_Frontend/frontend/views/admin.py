import json
import asyncio
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponseNotAllowed
from django.contrib import messages
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from ..constants import BACKEND_BASE_URL
from ..services import api_call, get_paginated_data, format_errors, get_fiber_choices

async def admin_view_donations(request):
    profile = request.user_profile
    page_data = await get_paginated_data(request, 'donations')
    return render(request, 'frontend/admin/admin_view_donations.html', {
        'page_title': 'Donations', 
        'user': profile, 
        'donations': page_data['results'],
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query']
    })

async def admin_view_donors(request):
    profile = request.user_profile
    page_data = await get_paginated_data(request, 'users', params={'role': 'Donor'})
    return render(request, 'frontend/admin/admin_view_donors.html', {
        'page_title': 'Donors', 
        'user': profile, 
        'backend_base_url': BACKEND_BASE_URL,
        'donors': page_data['results'],
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query']
    })

async def admin_view_tuabs(request):
    profile = request.user_profile
    page_data = await get_paginated_data(request, 'users', params={'role': 'TUAB'})
    return render(request, 'frontend/admin/admin_view_tuabs.html', {
        'page_title': 'Textile Upcycling Artisan Businesses',
        'user': profile,
        'backend_base_url': BACKEND_BASE_URL,
        'tuabs': page_data['results'],
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query']
    })

async def admin_add_tuab(request):
    profile = request.user_profile

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        action = request.POST.get('action', 'approve')
        rejection_reason = request.POST.get('rejection_reason')

        if not user_id:
            messages.error(request, "Missing TUAB user ID.")
            return redirect('admin_add_tuab')

        payload = {}
        if action == 'reject':
            if not rejection_reason:
                messages.error(request, "Rejection reason is required.")
                return redirect('admin_add_tuab')
            payload['status'] = 'REJECTED'
            payload['rejection_reason'] = rejection_reason
        else:
            payload['status'] = 'ACTIVE'

        try:
            response = await api_call(request, 'POST', f'users/{user_id}/approve', json=payload)
        except Exception:
            messages.error(request, "Backend API is offline or unreachable.")
            return redirect('admin_add_tuab')

        if response.status_code == 200:
            if action == 'reject':
                messages.success(request, "TUAB application rejected.")
            else:
                messages.success(request, "TUAB approved successfully.")
        else:
            response_data = response.json() if hasattr(response, 'json') else {}
            messages.error(request, response_data.get('detail', f'Unable to {action} TUAB.'))

        return redirect('admin_add_tuab')

    page_data = await get_paginated_data(request, 'users', params={'role': 'TUAB', 'status': 'UNDER_REVIEW'})

    return render(request, 'frontend/admin/admin_add_tuab.html', {
        'page_title': 'Add Textile Upcycling Artisan Business',
        'user': profile,
        'tuabs': page_data['results'],
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query']
    })

async def admin_view_tuab(request, user_id):
    profile = request.user_profile

    response = await api_call(request, 'GET', f'users/{user_id}')
    if response.status_code != 200:
        messages.error(request, "TUAB not found.")
        return redirect('admin_view_tuabs')

    tuab = response.json()
    if tuab.get('created_at'):
        tuab['created_at'] = parse_datetime(tuab['created_at'])
    if tuab.get('updated_at'):
        tuab['updated_at'] = parse_datetime(tuab['updated_at'])

    target_fibers = tuab.get('target_fibers') or ''
    target_fibers_list = [fiber.strip() for fiber in target_fibers.split(',') if fiber.strip()]

    return render(request, 'frontend/admin/admin_view_tuab.html', {
        'page_title': 'View Textile Upcycing Artisan Business',
        'user': profile,
        'tuab': tuab,
        'target_fibers_list': target_fibers_list,
    })

async def admin_view_donor(request, user_id):
    profile = request.user_profile
    
    response = await api_call(request, 'GET', f'users/{user_id}')
    if response.status_code != 200:
        messages.error(request, "Donor not found.")
        return redirect('admin_view_donors')
    
    donor = response.json()
    if donor.get('created_at'):
        donor['created_at'] = parse_datetime(donor['created_at'])
    if donor.get('updated_at'):
        donor['updated_at'] = parse_datetime(donor['updated_at'])
        
    return render(request, 'frontend/admin/admin_view_donor.html', {
        'page_title': 'View Donor',
        'user': profile,
        'donor': donor
    })

async def admin_edit_donor(request, user_id):
    profile = request.user_profile

    if request.method == 'POST':
        raw_data = request.POST
        password = raw_data.get('password')
        confirm_password = raw_data.get('confirm_password')
        submitted_etag = raw_data.get('current_etag')

        response = await api_call(request, 'GET', f'users/{user_id}')
        if response.status_code != 200:
            messages.error(request, "Donor not found.")
            return redirect('admin_view_donors')
        donor = response.json()
        current_etag = response.headers.get('ETag')
        if donor.get('status') != 'ACTIVE':
            messages.error(request, "Only active donors can be edited.")
            return redirect('admin_view_donors')

        if password != confirm_password:
            return render(request, 'frontend/admin/admin_edit_donor.html', {
                'page_title': 'Edit Donor',
                'user': profile,
                'donor': donor,
                'form_data': raw_data,
                'current_etag': submitted_etag or current_etag,
                'errors': {'Password': ["Passwords do not match."]},
            })

        payload = {}
        for field in ['first_name', 'middle_name', 'last_name', 'contact_no', 'display_address', 'latitude', 'longitude']:
            if field in raw_data:
                payload[field] = raw_data.get(field)

        # Handle middle_name: send empty string if blank
        if 'middle_name' in payload and payload['middle_name'] is None:
            payload['middle_name'] = ''

        if 'contact_no' in payload and payload['contact_no']:
            c = payload['contact_no']
            if c.startswith('0'):
                payload['contact_no'] = '+63' + c[1:]
            elif not c.startswith('+63'):
                payload['contact_no'] = '+63' + c

        if password:
            payload['password'] = password

        files = {}
        if request.FILES.get('upload'):
            files['upload'] = request.FILES['upload']

        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        patch_kwargs = {'headers': headers, 'data': payload}
        if files:
            patch_kwargs['files'] = files

        response = await api_call(request, 'PATCH', f'users/{user_id}', **patch_kwargs)

        if response.status_code == 200:
            if raw_data.get('disable_2fa') == '1' and donor.get('is_2fa_enabled'):
                try: await api_call(request, 'DELETE', f'users/{user_id}/2fa')
                except: pass
            messages.success(request, "Donor profile updated successfully.")
            return redirect('admin_view_donors')

        if response.status_code == 412:
            return redirect(f"/admin/donors/{user_id}/edit/?stale=1")

        try:
            response_data = response.json()
        except Exception:
            response_data = {}
        detail_message = response_data.get('detail') if isinstance(response_data, dict) and isinstance(response_data.get('detail'), str) else None
        return render(request, 'frontend/admin/admin_edit_donor.html', {
            'page_title': 'Edit Donor',
            'user': profile,
            'donor': donor,
            'form_data': raw_data,
            'current_etag': submitted_etag or current_etag,
            'errors': format_errors(response_data) if response.status_code in {400, 409} and not detail_message else None,
            'error_message': detail_message or ("We couldn't verify the donor's latest version. Please try again." if response.status_code == 428 else None),
        })

    response = await api_call(request, 'GET', f'users/{user_id}')
    if response.status_code != 200:
        messages.error(request, "Donor not found.")
        return redirect('admin_view_donors')
    donor = response.json()
    current_etag = response.headers.get('ETag')
    if donor.get('status') != 'ACTIVE':
        messages.error(request, "Only active donors can be edited.")
        return redirect('admin_view_donors')

    return render(request, 'frontend/admin/admin_edit_donor.html', {
        'page_title': 'Edit Donor',
        'user': profile,
        'donor': donor,
        'current_etag': current_etag,
        'error_message': "This donor was updated somewhere else. Refresh the page and try again." if request.GET.get('stale') == '1' else None,
    })

async def admin_add_donor(request):
    profile = request.user_profile
    
    if request.method == 'POST':
        raw_data = request.POST
        if raw_data.get('password') != raw_data.get('confirm_password'):
            return render(request, 'frontend/admin/admin_add_donor.html', {
                'page_title': 'Add Donor', 'user': profile, 'errors': {'Password': ["Passwords do not match."]}, 'form_data': raw_data
            })
        
        lat, lng = raw_data.get('latitude') or 0, raw_data.get('longitude') or 0
        payload = {
            'role': 'Donor',
            'first_name': raw_data.get('first_name'),
            'middle_name': raw_data.get('middle_name') or '',
            'last_name': raw_data.get('last_name'),
            'email': raw_data.get('email'),
            'password': raw_data.get('password'),
            'contact_no': raw_data.get('contact_no'),
            'display_address': raw_data.get('display_address'),
            'latitude': "{:.7f}".format(float(lat)),
            'longitude': "{:.7f}".format(float(lng)),
        }
        
        if payload['contact_no']:
            c = payload['contact_no']
            if c.startswith('0'):
                payload['contact_no'] = '+63' + c[1:]
            elif not c.startswith('+63'):
                payload['contact_no'] = '+63' + c

        response = await api_call(request, 'POST', 'users', json=payload)
        if response.status_code == 201:
            messages.success(request, "Donor account created successfully.")
            return redirect('admin_view_donors')
        
        return render(request, 'frontend/admin/admin_add_donor.html', {
            'page_title': 'Add Donor', 'user': profile, 'errors': format_errors(response.json()), 'form_data': raw_data
        })

    return render(request, 'frontend/admin/admin_add_donor.html', {'page_title': 'Add Donor', 'user': profile})

async def admin_archive_user_proxy(request, user_id):
    """Admin-only SSR Proxy for archiving/deleting a user."""
    profile = request.user_profile
    
    if request.method == 'POST':
        try:
            response = await api_call(request, 'DELETE', f'users/{user_id}')
            if response.status_code == 204:
                messages.success(request, "User archived successfully.")
            else:
                response_data = response.json() if hasattr(response, 'json') else {}
                messages.error(request, response_data.get('detail', 'Unable to archive user.'))
        except Exception:
            messages.error(request, "Backend API is offline or unreachable.")
            
    # Redirect back to the referring page or a fallback
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('admin_view_donors')

async def admin_edit_tuab(request, user_id):
    profile = request.user_profile

    if request.method == 'POST':
        fibers = await get_fiber_choices(request)
        raw_data = request.POST
        password = raw_data.get('password')
        confirm_password = raw_data.get('confirm_password')
        submitted_etag = raw_data.get('current_etag')

        if password and password != confirm_password:
            response = await api_call(request, 'GET', f'users/{user_id}')
            tuab = response.json()
            return render(request, 'frontend/admin/admin_edit_tuab.html', {
                'page_title': 'Edit TUAB', 
                'user': profile,
                'tuab': tuab, 
                'errors': {'Password': ["Passwords do not match."]}, 
                'form_data': raw_data,
                'current_etag': submitted_etag or response.headers.get('ETag'),
                'fibers': fibers
            })

        payload = raw_data.dict()
        for key in ['csrfmiddlewaretoken', 'current_etag', 'confirm_password', 'upload', 'is_2fa_enabled', 'email', 'status', 'remove_payment_method']:
            payload.pop(key, None)
        
        if not payload.get('password'):
            payload.pop('password', None)

        files = {}
        if request.FILES.get('upload'):
            files['upload'] = request.FILES['upload']

        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        response = await api_call(request, 'PATCH', f'users/{user_id}', data=payload, files=files, headers=headers)

        if response.status_code == 200:
            if raw_data.get('is_2fa_enabled') == 'false':
                await api_call(request, 'DELETE', f'users/{user_id}/2fa')
            
            if raw_data.get('remove_payment_method') == '1':
                try: await api_call(request, 'DELETE', f'users/{user_id}/subscription')
                except: pass

            messages.success(request, "TUAB profile updated successfully.")
            return redirect('admin_view_tuabs')
        
        if response.status_code == 412: 
            messages.error(request, "The profile was updated by someone else. Please refresh and try again.")
            return redirect(request.path)

        try:
            response_data = response.json()
        except Exception:
            response_data = {}
        detail_message = response_data.get('detail') if isinstance(response_data, dict) and isinstance(response_data.get('detail'), str) else None
        get_res = await api_call(request, 'GET', f'users/{user_id}')
        tuab = get_res.json()
        
        return render(request, 'frontend/admin/admin_edit_tuab.html', {
            'page_title': 'Edit TUAB', 
            'user': profile,
            'tuab': tuab, 
            'errors': format_errors(response_data) if response.status_code in {400, 409} and not detail_message else None,
            'error_message': detail_message or ("We couldn't verify the TUAB's latest version. Please try again." if response.status_code == 428 else None),
            'form_data': raw_data,
            'current_etag': submitted_etag or get_res.headers.get('ETag'),
            'fibers': fibers
        })

    # GET Request: Fetch fiber choices and user details in parallel
    fibers, response = await asyncio.gather(
        get_fiber_choices(request),
        api_call(request, 'GET', f'users/{user_id}')
    )
    if response.status_code != 200:
        messages.error(request, "TUAB not found.")
        return redirect('admin_view_tuabs')

    tuab = response.json()
    if tuab.get('status') != 'ACTIVE':
        messages.error(request, "Only active TUABs can be edited.")
        return redirect('admin_view_tuabs')

    current_etag = response.headers.get('ETag')
    return render(request, 'frontend/admin/admin_edit_tuab.html', {
        'page_title': 'Edit TUAB', 
        'user': profile,
        'tuab': tuab,
        'current_etag': current_etag,
        'fibers': fibers
    })

async def admin_add_donation(request):
    """View for admins to add a donation. Lookups and donor search are handled via AJAX."""
    profile = request.user_profile

    if request.method == 'POST':
        payload = request.POST.dict()
        files = {'donation_image': request.FILES['donation_image']} if 'donation_image' in request.FILES else {}
        
        for k in ['csrfmiddlewaretoken']:
            payload.pop(k, None)

        try:
            response = await api_call(request, 'POST', 'donations', data=payload, files=files)
            if response.status_code == 201:
                messages.success(request, "Donation created successfully!")
                return JsonResponse({'redirect': '/admin/donations/'})
            else:
                try:
                    err_data = response.json()
                except:
                    err_data = {'detail': 'Unknown backend error.'}

                if isinstance(err_data, dict):
                    detail_msg = err_data.get('detail')
                    if detail_msg:
                        return JsonResponse({'error': detail_msg}, status=response.status_code)

                    formatted = format_errors(err_data)
                    error_list = []
                    for field, msgs in formatted.items():
                        if isinstance(msgs, list):
                            error_list.extend(f"{field}: {msg}" for msg in msgs)
                        else:
                            error_list.append(f"{field}: {msgs}")

                    if error_list:
                        return JsonResponse({'errors': error_list}, status=response.status_code)

                return JsonResponse({'error': "Failed to create donation."}, status=response.status_code)
        except Exception as e:
            return JsonResponse({'error': f"System Error: {str(e)}"}, status=500)

    types_res, brands_res = await asyncio.gather(
        api_call(request, 'GET', 'clothing-types'),
        api_call(request, 'GET', 'brands')
    )
    clothing_types = types_res.json() if types_res.status_code == 200 else []
    all_brands = brands_res.json() if brands_res.status_code == 200 else []

    return render(request, 'frontend/admin/admin_add_donation.html', {
        'page_title': 'Add Donation',
        'user': profile,
        'clothing_types': clothing_types,
        'all_brands': all_brands,
        'condition_choices': [
            ('NEW', 'New'),
            ('LIKE_NEW', 'Like New'),
            ('GOOD', 'Good'),
            ('FAIR', 'Fair'),
            ('POOR', 'Poor'),
        ]
    })

async def admin_view_donation(request, donation_id):
    profile = request.user_profile

    response = await api_call(request, 'GET', f'donations/{donation_id}')
    if response.status_code != 200:
        messages.error(request, "Donation not found.")
        return redirect('admin_view_donations')

    donation = response.json()

    if donation.get('preferred_pickup_date'):
        donation['preferred_pickup_date'] = parse_datetime(donation['preferred_pickup_date'])
    if donation.get('submitted_at'):
        donation['submitted_at'] = parse_datetime(donation['submitted_at'])

    return render(request, 'frontend/admin/admin_view_donation.html', {
        'page_title': 'View Donation',
        'user': profile,
        'donation': donation,
        'items': donation.get('items', [])
    })

async def admin_edit_donation(request, donation_id):
    profile = request.user_profile

    if request.method == 'POST':
        payload = request.POST.dict()
        submitted_etag = payload.get('current_etag')
        
        for k in ['csrfmiddlewaretoken', 'current_etag']:
            payload.pop(k, None)

        files = {}
        if 'donation_image' in request.FILES:
            files['donation_image'] = request.FILES['donation_image']

        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        patch_kwargs = {'headers': headers, 'data': payload}
        if files:
            patch_kwargs['files'] = files

        try:
            response = await api_call(request, 'PATCH', f'donations/{donation_id}', **patch_kwargs)
            if 200 <= response.status_code < 300:
                messages.success(request, "Donation updated successfully!")
                return JsonResponse({'redirect': f'/admin/donations/{donation_id}/'})
            elif response.status_code == 412:
                return JsonResponse({'error': 'This donation was updated by someone else. Please refresh and try again.'}, status=412)
            elif response.status_code == 428:
                return JsonResponse({'error': "We couldn't verify the donation's latest version. Please refresh and try again."}, status=428)
            else:
                try:
                    err_data = response.json()
                except Exception:
                    err_data = {'detail': 'Unknown backend error.'}

                if isinstance(err_data, dict):
                    detail_msg = err_data.get('detail')
                    if detail_msg:
                        return JsonResponse({'error': detail_msg}, status=response.status_code)

                    formatted = format_errors(err_data)
                    error_list = []
                    for field, msgs in formatted.items():
                        if isinstance(msgs, list):
                            error_list.extend(f"{field}: {msg}" for msg in msgs)
                        else:
                            error_list.append(f"{field}: {msgs}")

                    if error_list:
                        return JsonResponse({'errors': error_list}, status=response.status_code)

                return JsonResponse({'error': "Failed to update donation."}, status=response.status_code)
        except Exception as e:
            return JsonResponse({'error': f"System Error: {str(e)}"}, status=400)

    response = await api_call(request, 'GET', f'donations/{donation_id}')
    if response.status_code != 200:
        messages.error(request, "Donation not found.")
        return redirect('admin_view_donations')

    donation = response.json()
    if donation.get('status') == 'ARCHIVED':
        messages.error(request, "Archived donations cannot be edited.")
        return redirect('admin_view_donations')
    current_etag = response.headers.get('ETag', '')

    types_res, brands_res = await asyncio.gather(
        api_call(request, 'GET', 'clothing-types'),
        api_call(request, 'GET', 'brands')
    )
    clothing_types = types_res.json() if types_res.status_code == 200 else []
    all_brands = brands_res.json() if brands_res.status_code == 200 else []

    return render(request, 'frontend/admin/admin_edit_donation.html', {
        'page_title': 'Edit Donation',
        'user': profile,
        'donation': donation,
        'current_etag': current_etag,
        'clothing_types': clothing_types,
        'all_brands': all_brands,
        'condition_choices': [
            ('NEW', 'New'),
            ('LIKE_NEW', 'Like New'),
            ('GOOD', 'Good'),
            ('FAIR', 'Fair'),
            ('POOR', 'Poor'),
        ]
    })


async def admin_cancel_donation(request, donation_id):
    profile = request.user_profile
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        response = await api_call(request, 'POST', f'donations/{donation_id}/cancel')
        if response.status_code == 200:
            return JsonResponse({'redirect': reverse('admin_view_donations')})

        try:
            err_data = response.json()
        except Exception:
            err_data = {}
        error_msg = err_data.get('detail') if isinstance(err_data, dict) else None
        return JsonResponse(
            {'error': error_msg or "Failed to cancel donation."},
            status=response.status_code,
        )
    except Exception as e:
        return JsonResponse({'error': f"System Error: {str(e)}"}, status=500)


async def admin_archive_donation(request, donation_id):
    profile = request.user_profile
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        response = await api_call(request, 'POST', f'donations/{donation_id}/archive')
        if response.status_code == 200:
            messages.success(request, "Donation archived successfully.")
            return JsonResponse({'redirect': reverse('admin_view_donations')})

        try:
            err_data = response.json()
        except Exception:
            err_data = {}

        error_msg = err_data.get('detail') if isinstance(err_data, dict) else None
        return JsonResponse(
            {'error': error_msg or "Failed to archive donation."},
            status=response.status_code,
        )
    except Exception as e:
        return JsonResponse({'error': f"System Error: {str(e)}"}, status=500)


async def admin_impact_dashboard(request):
    """View to display aggregate donation metrics and a Leaflet map of NCR barangays for Admin."""
    profile = request.user_profile

    # Extract filter parameters
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    pickup_city = request.GET.get('pickup_city', '')
    clothing_type = request.GET.get('clothing_type', '')

    api_params = {}
    if date_from:
        api_params['date_from'] = date_from
    if date_to:
        api_params['date_to'] = date_to
    if pickup_city and pickup_city != 'All Cities':
        api_params['pickup_city'] = pickup_city
    if clothing_type and clothing_type != 'All Types':
        api_params['clothing_type'] = clothing_type

    # Fetch backend impact-dashboard metrics and clothing types concurrently
    dashboard_data = {}
    clothing_types = []
    try:
        response, types_res = await asyncio.gather(
            api_call(request, 'GET', 'impact-dashboard', params=api_params),
            api_call(request, 'GET', 'clothing-types')
        )
        if response.status_code == 200:
            dashboard_data = response.json()
        else:
            try:
                response_data = response.json()
            except Exception:
                response_data = {}

            detail_message = response_data.get('detail') if isinstance(response_data, dict) else None
            error_messages = None
            if isinstance(response_data, dict):
                formatted = format_errors(response_data)
                error_messages = [
                    f"{field}: {', '.join(map(str, value if isinstance(value, list) else [value]))}"
                    if isinstance(value, (list, tuple))
                    else f"{field}: {value}"
                    for field, value in formatted.items()
                ]

            if detail_message:
                messages.error(request, detail_message)
            elif error_messages:
                for message in error_messages:
                    messages.error(request, message)
            else:
                messages.error(request, "Failed to load donation metrics from the backend.")
        
        if types_res.status_code == 200:
            clothing_types = types_res.json()
    except Exception as e:
        messages.error(request, f"Backend service unreachable: {str(e)}")

    # Static list of cities matching the templates
    cities = [
        "Manila", "Quezon City", "Caloocan", "Makati", "Pasig", "Taguig",
        "Mandaluyong", "Pasay", "Parañaque", "Las Piñas", "Muntinlupa",
        "Marikina", "San Juan", "Valenzuela", "Navotas", "Malabon", "Pateros"
    ]

    total_donations = dashboard_data.get('donations', 0)
    claimed_count = dashboard_data.get('donors', 0)  # Map unique donors to the second stat slot
    leaderboard = dashboard_data.get('top_donors', [])
    donations_json = dashboard_data.get('barangay_breakdown', [])

    return render(request, 'frontend/admin/admin_impact_dashboard.html', {
        'page_title': 'Donation Impact Dashboard',
        'user': profile,
        'total_donations': total_donations,
        'claimed_count': claimed_count,
        'leaderboard': leaderboard,
        'cities': cities,
        'clothing_types': clothing_types,
        'donations_json': donations_json,
        'date_from': date_from,
        'date_to': date_to,
        'selected_city': pickup_city,
        'selected_clothing_type': clothing_type,
    })



async def admin_view_payments(request):
    """View Admin payment history."""
    profile = request.user_profile
    reference = request.GET.get('reference', '')
    
    page_data = await get_paginated_data(request, 'payments', params={'reference': reference} if reference else None)
    
    return render(request, 'frontend/admin/admin_view_payments.html', {
        'page_title': 'Payments',
        'sidebar_variant': 'admin',
        'user': profile,
        'payments_json': page_data['results'],
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query']
    })


async def admin_circular_economy(request):
    """Admin view of the platform-wide Circular Economy dashboard."""
    from datetime import datetime
    profile = request.user_profile

    date_from = request.GET.get('date_from', '')
    date_to   = request.GET.get('date_to', '')
    tuab_id   = request.GET.get('tuab_id', '')

    params = {}
    if date_from: params['date_from'] = date_from
    if date_to:   params['date_to']   = date_to
    if tuab_id:   params['tuab_id']   = tuab_id

    dashboard_data = {
        'biodeg_distribution': [],
        'volume_by_city_fiber': [],
        'top_brands': [],
        'decisions_by_city': [],
    }
    tuabs = []
    error_message = None

    try:
        res, tuab_res = await asyncio.gather(
            api_call(request, 'GET', 'tuab-circular-economy', params=params),
            api_call(request, 'GET', 'users', params={'role': 'TUAB', 'status': 'ACTIVE', 'page_size': 200}),
        )
        if res and res.status_code == 200:
            dashboard_data = res.json()
        elif res and res.status_code in (400, 422):
            try:
                err_data = res.json()
                if isinstance(err_data, dict):
                    parts = []
                    for v in err_data.values():
                        parts.append(', '.join(v) if isinstance(v, list) else str(v))
                    error_message = ' '.join(parts) or "Invalid date range filter."
                else:
                    error_message = "Invalid date range filter."
            except Exception:
                error_message = "Invalid date range filter."
        else:
            error_message = "Unable to load dashboard data."
        if tuab_res and tuab_res.status_code == 200:
            tuabs = tuab_res.json().get('results', tuab_res.json()) if isinstance(tuab_res.json(), dict) else tuab_res.json()
    except Exception:
        error_message = "An error occurred while loading the dashboard."

    return render(request, 'frontend/admin/admin_circular_economy.html', {
        'page_title': 'Circular Economy Impact Dashboard',
        'sidebar_variant': 'admin',
        'user': profile,
        'date_from': date_from,
        'date_to': date_to,
        'today_iso': datetime.now().strftime('%Y-%m-%d'),
        'tuab_id': tuab_id,
        'tuabs': tuabs,
        'error_message': error_message,
        'dashboard_json': json.dumps(dashboard_data),
    })
