from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.dateparse import parse_datetime
from ..constants import BACKEND_BASE_URL
from ..services import api_call, get_user_profile, get_paginated_data, format_errors

def admin_view_donations(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    
    page_data = get_paginated_data(request, 'donations')
    
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

def admin_view_donors(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    
    page_data = get_paginated_data(request, 'users', params={'role': 'Donor'})
    
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

def admin_view_tuabs(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')

    page_data = get_paginated_data(request, 'users', params={'role': 'TUAB'})

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

def admin_add_tuab(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin':
        return redirect('login')

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        if not user_id:
            messages.error(request, "Missing TUAB user ID.")
            return redirect('admin_add_tuab')

        try:
            response = api_call(request, 'POST', f'users/{user_id}/approve')
        except Exception:
            messages.error(request, "Backend API is offline or unreachable.")
            return redirect('admin_add_tuab')

        if response.status_code == 200:
            messages.success(request, "TUAB approved successfully.")
        else:
            response_data = response.json() if hasattr(response, 'json') else {}
            messages.error(request, response_data.get('detail', 'Unable to approve TUAB.'))

        return redirect('admin_add_tuab')

    page_data = get_paginated_data(request, 'users', params={'role': 'TUAB', 'status': 'UNDER_REVIEW'})

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

def admin_view_tuab(request, user_id):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')

    response = api_call(request, 'GET', f'users/{user_id}')
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

def admin_view_donor(request, user_id):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    
    response = api_call(request, 'GET', f'users/{user_id}')
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

def admin_edit_donor(request, user_id):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin':
        return redirect('login')

    if request.method == 'POST':
        raw_data = request.POST
        password = raw_data.get('password')
        confirm_password = raw_data.get('confirm_password')
        submitted_etag = raw_data.get('current_etag')

        response = api_call(request, 'GET', f'users/{user_id}')
        if response.status_code != 200:
            messages.error(request, "Donor not found.")
            return redirect('admin_view_donors')
        donor = response.json()
        current_etag = response.headers.get('ETag')
        if donor.get('status') == 'ARCHIVED':
            messages.error(request, "Archived donors can no longer be edited.")
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
            # if it already starts with +63, leave it alone

        if password:
            payload['password'] = password

        files = {}
        if request.FILES.get('upload'):
            files['upload'] = request.FILES['upload']

        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        patch_kwargs = {'headers': headers, 'data': payload}
        if files:
            patch_kwargs['files'] = files

        response = api_call(request, 'PATCH', f'users/{user_id}', **patch_kwargs)

        if response.status_code == 200:
            if raw_data.get('disable_2fa') == '1' and donor.get('is_2fa_enabled'):
                try: api_call(request, 'DELETE', f'users/{user_id}/2fa')
                except: pass
            messages.success(request, "Donor profile updated successfully.")
            return redirect('admin_view_donors')

        if response.status_code == 412:
            return redirect(f"/admin/donors/{user_id}/edit/?stale=1")

        response_data = response.json() if response.status_code == 400 else {}
        detail_message = response_data.get('detail') if isinstance(response_data, dict) else None
        return render(request, 'frontend/admin/admin_edit_donor.html', {
            'page_title': 'Edit Donor',
            'user': profile,
            'donor': donor,
            'form_data': raw_data,
            'current_etag': submitted_etag or current_etag,
            'errors': format_errors(response_data) if response.status_code == 400 and not detail_message else None,
            'error_message': detail_message or ("We couldn't verify the donor's latest version. Please try again." if response.status_code == 428 else None),
        })

    response = api_call(request, 'GET', f'users/{user_id}')
    if response.status_code != 200:
        messages.error(request, "Donor not found.")
        return redirect('admin_view_donors')
    donor = response.json()
    current_etag = response.headers.get('ETag')
    if donor.get('status') == 'ARCHIVED':
        messages.error(request, "Archived donors can no longer be edited.")
        return redirect('admin_view_donors')

    return render(request, 'frontend/admin/admin_edit_donor.html', {
        'page_title': 'Edit Donor',
        'user': profile,
        'donor': donor,
        'current_etag': current_etag,
        'error_message': "This donor was updated somewhere else. Refresh the page and try again." if request.GET.get('stale') == '1' else None,
    })

def admin_add_donor(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    
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

        response = api_call(request, 'POST', 'users', json=payload)
        if response.status_code == 201:
            messages.success(request, "Donor account created successfully.")
            return redirect('admin_view_donors')
        
        return render(request, 'frontend/admin/admin_add_donor.html', {
            'page_title': 'Add Donor', 'user': profile, 'errors': format_errors(response.json()), 'form_data': raw_data
        })

    return render(request, 'frontend/admin/admin_add_donor.html', {'page_title': 'Add Donor', 'user': profile})
def admin_archive_user_proxy(request, user_id):
    """Admin-only SSR Proxy for archiving/deleting a user."""
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin':
        return redirect('login')
    
    if request.method == 'POST':
        try:
            api_call(request, 'DELETE', f'users/{user_id}')
        except Exception:
            pass
            
    # Redirect back to the referring page or a fallback
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('admin_view_donors')

from ..services import get_fiber_choices

def admin_edit_tuab(request, user_id):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin':
        return redirect('login')

    fibers = get_fiber_choices(request)

    if request.method == 'POST':
        raw_data = request.POST
        password = raw_data.get('password')
        confirm_password = raw_data.get('confirm_password')
        submitted_etag = raw_data.get('current_etag')

        if password and password != confirm_password:
            # Re-fetch or use old data? Usually re-fetch to ensure fresh state if they failed validation
            response = api_call(request, 'GET', f'users/{user_id}')
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
        # Remove internal frontend-only fields and blocked fields
        for key in ['csrfmiddlewaretoken', 'current_etag', 'confirm_password', 'upload', 'is_2fa_enabled', 'email', 'status', 'remove_payment_method']:
            payload.pop(key, None)
        
        if not payload.get('password'):
            payload.pop('password', None)

        files = {}
        if request.FILES.get('upload'):
            files['upload'] = request.FILES['upload']

        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        response = api_call(request, 'PATCH', f'users/{user_id}', data=payload, files=files, headers=headers)

        if response.status_code == 200:
            # If successful update, handle secondary actions
            if raw_data.get('is_2fa_enabled') == 'false':
                api_call(request, 'DELETE', f'users/{user_id}/2fa')
            
            if raw_data.get('remove_payment_method') == '1':
                try: api_call(request, 'DELETE', f'users/{user_id}/subscription')
                except: pass

            messages.success(request, "TUAB profile updated successfully.")
            return redirect('admin_view_tuabs')
        
        # Handle errors (400, 412, etc.)
        if response.status_code == 412: # Precondition Failed (Stale ETag)
            messages.error(request, "The profile was updated by someone else. Please refresh and try again.")
            return redirect(request.path)

        response_data = response.json() if response.status_code == 400 else {}
        # We need the TUAB data again to re-render the form
        get_res = api_call(request, 'GET', f'users/{user_id}')
        tuab = get_res.json()
        
        return render(request, 'frontend/admin/admin_edit_tuab.html', {
            'page_title': 'Edit TUAB', 
            'user': profile,
            'tuab': tuab, 
            'errors': format_errors(response_data), 
            'form_data': raw_data,
            'current_etag': submitted_etag or get_res.headers.get('ETag'),
            'fibers': fibers
        })

    # GET Request
    response = api_call(request, 'GET', f'users/{user_id}')
    if response.status_code != 200:
        messages.error(request, "TUAB not found.")
        return redirect('admin_view_tuabs')
    
    tuab = response.json()
    current_etag = response.headers.get('ETag')
    return render(request, 'frontend/admin/admin_edit_tuab.html', {
        'page_title': 'Edit TUAB', 
        'user': profile,
        'tuab': tuab,
        'current_etag': current_etag,
        'fibers': fibers
    })
