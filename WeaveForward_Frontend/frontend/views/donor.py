import json
import asyncio
from datetime import datetime
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.utils.dateparse import parse_datetime, parse_time
from ..services import api_call, format_errors, get_paginated_data, get_fiber_choices, get_user_profile


async def donor_browse_businesses(request):
    """Donor Dashboard - Browsing active TUABs."""
    profile = request.user_profile
    
    # Categories for filter from Service (Matches Registration)
    categories = await get_fiber_choices(request)
    
    # Capture filter params
    params = {'role': 'TUAB', 'status': 'ACTIVE'}
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    category = request.GET.get('category')
    
    # Validate filter inputs defensively to prevent ValueErrors
    invalid_filters = False
    if lat and lng:
        try:
            float(lat)
            float(lng)
            params['lat'] = lat
            params['lng'] = lng
        except ValueError:
            invalid_filters = True
    elif lat or lng:
        # Incomplete coordinates are invalid
        invalid_filters = True
        
    if category:
        params['category'] = category

    # Inline paginated api_call to capture raw response status and catch network outages locally
    page = request.GET.get('page', 1)
    try:
        current_page = int(page)
        if current_page < 1:
            current_page = 1
    except ValueError:
        current_page = 1
        page = '1'
        
    search_query = request.GET.get('q', '')
    
    api_params = params.copy()
    api_params.update({'page': page, 'search': search_query})
    
    has_error = False
    if invalid_filters:
        has_error = True
        data = {}
    else:
        response = await api_call(request, 'GET', 'users', params=api_params)
        has_error = response.status_code != 200
        data = response.json() if not has_error else {}
    
    businesses = data.get('results', [])
    count = data.get('count', 0)
    total_pages = (count + 9) // 10  # 10 items per page
    has_next = data.get('next') is not None
    has_prev = data.get('previous') is not None
        
    # Process target_fibers into lists for template
    for biz in businesses:
        fibers = biz.get('target_fibers', '')
        if fibers:
            biz['fiber_list'] = [f.strip() for f in fibers.split(',') if f.strip()][:3]
        else:
            biz['fiber_list'] = ['upcycling']
    
    return render(request, 'frontend/donor/donor_browse_businesses.html', {
        'page_title': 'Browse Businesses', 
        'user': profile,
        'businesses': businesses,
        'categories': categories,
        'count': count,
        'total_pages': total_pages,
        'current_page': current_page,
        'has_next': has_next,
        'has_prev': has_prev,
        'page_range': range(1, total_pages + 1),
        'q': search_query,
        'has_error': has_error,
        'invalid_filters': invalid_filters
    })

async def donor_my_donations(request):
    """View to list the logged-in donor's donations with search and pagination."""
    profile = request.user_profile
    page_data = await get_paginated_data(request, 'users/me/donations')
    
    donations_list = page_data['results']
    for d in donations_list:
        if d.get('preferred_pickup_date'):
            d['preferred_pickup_date'] = parse_datetime(d['preferred_pickup_date'])
        if d.get('preferred_pickup_window_start'):
            d['preferred_pickup_window_start'] = parse_time(d['preferred_pickup_window_start'])
        if d.get('preferred_pickup_window_end'):
            d['preferred_pickup_window_end'] = parse_time(d['preferred_pickup_window_end'])

    def fmt_date(dt):
        return dt.strftime('%m-%d-%Y') if dt else ''
    def fmt_time(t):
        return t.strftime('%I:%M %p').lstrip('0') if t else ''

    donations_json = [
        {
            'donation_id': d['donation_id'],
            'pickupDate': fmt_date(d.get('preferred_pickup_date')),
            'pickupStart': fmt_time(d.get('preferred_pickup_window_start')),
            'pickupEnd': fmt_time(d.get('preferred_pickup_window_end')),
            'address': d.get('pickup_display_address', ''),
            'status': d.get('status', ''),
            'business_name': (d.get('claimed_by_tuab') or {}).get('business_name', ''),
            'upload': d.get('upload', ''),
            'items': [
                {
                    'label': '{} - {} {}'.format(
                        i.get('lookup_details', {}).get('clothing_type', ''),
                        i.get('lookup_details', {}).get('brand', ''),
                        (i.get('lookup_details', {}).get('dominant_fiber', '') or ''),
                    )
                } for i in d.get('items', [])
            ],
        }
        for d in donations_list
    ]

    meta = {
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query'],
    }

    if 'application/json' in request.headers.get('Accept', ''):
        resp = JsonResponse({
            'donations': donations_json,
            'meta': meta,
        })
        resp['Cache-Control'] = 'no-store'
        return resp

    return render(request, 'frontend/donor/donor_my_donations.html', {
        'page_title': 'My Donations',
        'user': profile,
        'donations': donations_list,
        'donations_json': donations_json,
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query'],
    })

async def donor_view_donation(request, donation_id):
    profile = request.user_profile

    response = await api_call(request, 'GET', f'donations/{donation_id}')
    if response.status_code != 200:
        if response.status_code == 403:
            messages.error(request, "Access denied.")
        else:
            messages.error(request, "Donation not found.")
        return redirect('donor_my_donations')

    donation = response.json()
    
    # Parse for formatting
    if donation.get('preferred_pickup_date'):
        donation['preferred_pickup_date'] = parse_datetime(donation['preferred_pickup_date'])
    if donation.get('preferred_pickup_window_start'):
        donation['preferred_pickup_window_start'] = parse_time(donation['preferred_pickup_window_start'])
    if donation.get('preferred_pickup_window_end'):
        donation['preferred_pickup_window_end'] = parse_time(donation['preferred_pickup_window_end'])

    return render(request, 'frontend/donor/donor_view_donation.html', {
        'page_title': 'View Donation',
        'user': profile,
        'donation': donation,
        'items': donation.get('items', [])
    })

async def donor_view_tuab(request, user_id):
    """View to see details of a specific TUAB business."""
    profile = request.user_profile

    response = await api_call(request, 'GET', f'users/{user_id}')
    if response.status_code != 200:
        messages.error(request, "Business not found or access denied.")
        return redirect('donor_browse_businesses')

    business = response.json()
    
    # Process target_fibers into a list
    fibers = business.get('target_fibers', '')
    if fibers:
        business['fiber_list'] = [f.strip() for f in fibers.split(',') if f.strip()]
    else:
        business['fiber_list'] = []

    return render(request, 'frontend/donor/donor_view_tuab.html', {
        'page_title': f"View Business | {business.get('business_name', 'Business Details')}",
        'user': profile,
        'business': business,
    })

async def donor_create_donation(request):
    """View for donors to create a new donation. Supports the new SSR-based version2 template."""
    profile = await get_user_profile(request) or request.user_profile

    if request.method == 'POST':
        payload = request.POST.dict()
        files = {'donation_image': request.FILES['donation_image']} if 'donation_image' in request.FILES else {}
        
        # Clean payload
        for k in ['csrfmiddlewaretoken']:
            payload.pop(k, None)

        response = await api_call(request, 'POST', 'donations', data=payload, files=files)
        if response.status_code == 201:
            messages.success(request, "Donation created successfully!")
            return JsonResponse({'redirect': '/donor/my-donations/'})
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

    # Fetch choices for the dropdowns (matching edit logic) in parallel
    types_res, brands_res = await asyncio.gather(
        api_call(request, 'GET', 'clothing-types'),
        api_call(request, 'GET', 'brands')
    )
    clothing_types = types_res.json() if types_res.status_code == 200 else []
    all_brands = brands_res.json() if brands_res.status_code == 200 else []

    return render(request, 'frontend/donor/donor_create_donation.html', {
        'page_title': 'Create Donation',
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

async def donor_profile(request):
    """View for the donor's account profile. Always fetches fresh data."""
    response = await api_call(request, 'GET', 'users/me')
    if response.status_code == 200:
        profile = response.json()
    else:
        # Fallback to cached profile if backend is unreachable
        profile = request.user_profile.copy() if request.user_profile else {}
    
    if profile.get('created_at'):
        profile['created_at'] = parse_datetime(profile['created_at'])
        
    return render(request, 'frontend/donor/donor_profile.html', {
        'page_title': 'Account Profile',
        'user': profile
    })

async def donor_edit_profile(request):
    """View to edit the donor's profile. Handles AJAX updates."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST' and is_ajax:
        # 1. Capture payload
        payload = request.POST.dict()
        user_id = payload.get('user_id')
        submitted_etag = payload.get('current_etag')

        # 2. Extract and format password if present
        password = payload.get('new_password')
        confirm_password = payload.get('confirm_password')
        if password:
            if password != confirm_password:
                return JsonResponse({'errors': {'password': ['Passwords do not match.']}}, status=400)
            payload['password'] = password

        # 3. Format Phone
        if 'contact_no' in payload and payload['contact_no']:
            c = payload['contact_no']
            if c.startswith('0'): payload['contact_no'] = '+63' + c[1:]
            elif not c.startswith('+63'): payload['contact_no'] = '+63' + c

        # 4. Clean internal/blocked fields
        for k in ['csrfmiddlewaretoken', 'current_etag', 'confirm_password', 'new_password', 'user_id', 'photo', 'upload', 'otp_code', 'secret', 'disable_2fa']:
            payload.pop(k, None)

        # 5. Handle File Upload
        files = {}
        if 'upload' in request.FILES:
            files['upload'] = request.FILES['upload']

        # 6. Proxy PATCH to backend
        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        response = await api_call(request, 'PATCH', 'users/me?validate_only=true', data=payload, files=files, headers=headers)
        
        if response.status_code == 200:
            etag_changed = False
            if request.POST.get('otp_code'):
                res = await api_call(request, 'POST', 'users/me/2fa', json={'otp_code': request.POST['otp_code'], 'secret': request.POST.get('secret')})
                if res.status_code != 200: return JsonResponse({'error': res.json().get('detail', 'Invalid 2FA code.')}, status=400)
                etag_changed = True
            
            if request.POST.get('disable_2fa') == '1':
                await api_call(request, 'DELETE', 'users/me/2fa'); etag_changed = True
                
            if etag_changed:
                get_res = await api_call(request, 'GET', 'users/me')
                if get_res.status_code == 200: headers['If-Match'] = get_res.headers.get('ETag')
                
            response = await api_call(request, 'PATCH', 'users/me', data=payload, files=files, headers=headers)

        if response.status_code == 200:
            messages.success(request, "Profile updated successfully.")
            return JsonResponse({'message': 'Success'}, status=200)
        else:
            try:
                err_data = response.json()
            except:
                err_data = {'detail': 'Unknown backend error.'}
            
            if response.status_code == 412:
                return JsonResponse({'error': 'The profile was updated by someone else. Please refresh and try again.'}, status=412)

            detail_message = err_data.get('detail') if isinstance(err_data, dict) and isinstance(err_data.get('detail'), str) else None
            if detail_message:
                return JsonResponse({'detail': detail_message}, status=response.status_code)

            return JsonResponse({'errors': format_errors(err_data)}, status=response.status_code)


    # GET Request: Fetch fresh data and ETag
    response = await api_call(request, 'GET', 'users/me')
    if response.status_code == 200:
        profile = response.json()
        etag = response.headers.get('ETag')
        
        # Clean contact number for display (strip +63)
        contact = profile.get('contact_no', '')
        if contact and contact.startswith('+63'):
            profile['contact_no'] = contact[3:]
    else:
        messages.error(request, "Unable to fetch latest profile data.")
        return redirect('donor_profile')

    return render(request, 'frontend/donor/donor_edit_profile.html', {
        'page_title': 'Edit Profile',
        'user': profile,
        'current_etag': etag
    })

async def donor_edit_donation(request, donation_id):
    """View to edit an existing donation. Handles fetching and proxying updates."""
    profile = request.user_profile

    if request.method == 'POST':
        # 1. Capture payload
        payload = request.POST.dict()
        submitted_etag = payload.get('current_etag')

        # 2. Extract files
        files = {}
        if 'donation_image' in request.FILES:
            files['donation_image'] = request.FILES['donation_image']

        # 3. Clean payload
        for k in ['csrfmiddlewaretoken', 'current_etag', '_method']:
            payload.pop(k, None)


        # 4. Proxy PATCH to backend
        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        response = await api_call(request, 'PATCH', f'donations/{donation_id}', data=payload, files=files, headers=headers)
        if response.status_code == 200:
            messages.success(request, "Donation updated successfully!")
            return JsonResponse({'redirect': f'/donor/my-donations/{donation_id}/'})
        elif response.status_code == 412:
            return JsonResponse({'error': "This donation was updated somewhere else. Please refresh."}, status=412)
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

            return JsonResponse({'error': "Update failed."}, status=response.status_code)

    # GET Request: Fetch donation, clothing types, and all brands in parallel
    donation_res, types_res, brands_res = await asyncio.gather(
        api_call(request, 'GET', f'donations/{donation_id}'),
        api_call(request, 'GET', 'clothing-types'),
        api_call(request, 'GET', 'brands')
    )
    
    if donation_res.status_code == 200:
        donation = donation_res.json()
        etag = donation_res.headers.get('ETag')
        
        # Check if the donation is in PENDING status
        if donation.get('status') != 'PENDING':
            messages.error(request, f"Cannot edit a donation in {donation.get('status')} status.")
            return redirect('donor_view_donation', donation_id=donation_id)
    else:
        messages.error(request, "Unable to fetch donation data.")
        return redirect('donor_my_donations')

    clothing_types = types_res.json() if types_res.status_code == 200 else []
    all_brands = brands_res.json() if brands_res.status_code == 200 else []

    return render(request, 'frontend/donor/donor_edit_donation.html', {
        'page_title': 'Edit Donation',
        'user': profile,
        'donation': donation,
        'current_etag': etag,
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


async def donor_cancel_donation(request, donation_id):
    await api_call(request, 'GET', 'users/me')

    if request.method == 'POST':
        response = await api_call(request, 'POST', f'donations/{donation_id}/cancel')
        if response.status_code == 200:
            return JsonResponse({'success': True, 'message': 'Donation cancelled successfully!'})
        else:
            err_data = response.json()
            error_msg = err_data.get('detail') if isinstance(err_data, dict) else None
            return JsonResponse({'success': False, 'error': error_msg or 'Failed to cancel donation.'}, status=400)
    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)


async def donor_impact_dashboard(request):
    """View to display aggregate donation metrics and a Leaflet map of NCR barangays."""
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

    if request.GET.get('format') == 'json':
        return JsonResponse({
            'total_donations': total_donations,
            'claimed_count': claimed_count,
            'leaderboard': leaderboard,
            'donations_json': donations_json,
        })

    return render(request, 'frontend/donor/donor_impact_dashboard.html', {
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
        'today_iso': datetime.now().strftime('%Y-%m-%d'),
    })
