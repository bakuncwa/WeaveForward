from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.dateparse import parse_datetime
from ..services import api_call, get_user_profile, get_paginated_data, format_errors

def admin_view_donations(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    
    page_data = get_paginated_data(request, 'donations/')
    
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
    
    page_data = get_paginated_data(request, 'users/', params={'role': 'Donor'})
    
    return render(request, 'frontend/admin/admin_view_donors.html', {
        'page_title': 'Donors', 
        'user': profile, 
        'donors': page_data['results'],
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query']
    })

def admin_view_donor(request, user_id):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    
    response = api_call(request, 'GET', f'users/{user_id}/')
    if response.status_code != 200:
        messages.error(request, "Donor not found.")
        return redirect('admin_view_donors')
        
    donor = response.json()
    
    # Parse dates so Django template filters can work
    if donor.get('created_at'):
        donor['created_at'] = parse_datetime(donor['created_at'])
    if donor.get('updated_at'):
        donor['updated_at'] = parse_datetime(donor['updated_at'])
        
    return render(request, 'frontend/admin/admin_view_donor.html', {
        'page_title': 'Donor Detail',
        'user': profile,
        'donor': donor
    })

def admin_add_donor(request):
    profile = get_user_profile(request)
    if not profile or profile.get('role') != 'Admin': return redirect('login')
    
    if request.method == 'POST':
        raw_data = request.POST
        password = raw_data.get('password')
        confirm_password = raw_data.get('confirm_password')

        if password != confirm_password:
            return render(request, 'frontend/admin/admin_add_donor.html', {
                'page_title': 'Add Donor',
                'user': profile,
                'errors': {'Password': ["Passwords do not match."]},
                'form_data': raw_data
            })
        lat = raw_data.get('latitude') or 0
        lng = raw_data.get('longitude') or 0
        payload = {
            'role': 'Donor',
            'first_name': raw_data.get('first_name'),
            'middle_name': raw_data.get('middle_name'),
            'last_name': raw_data.get('last_name'),
            'email': raw_data.get('email'),
            'password': raw_data.get('password'),
            'contact_no': raw_data.get('contact_no'),
            'display_address': raw_data.get('display_address'),
            'latitude': "{:.7f}".format(float(lat)),
            'longitude': "{:.7f}".format(float(lng)),
        }
        
        # Phone cleaning
        contact_no = payload['contact_no']
        if contact_no:
            if contact_no.startswith('0'): contact_no = '+63' + contact_no[1:]
            elif not contact_no.startswith('+'): contact_no = '+63' + contact_no
            payload['contact_no'] = contact_no

        response = api_call(request, 'POST', 'users/', json=payload)
        if response.status_code == 201:
            messages.success(request, "Donor account created successfully.")
            return redirect('admin_view_donors')
        else:
            errors = format_errors(response.json())
            return render(request, 'frontend/admin/admin_add_donor.html', {
                'page_title': 'Add Donor', 
                'user': profile, 
                'errors': errors, 
                'form_data': raw_data
            })

    return render(request, 'frontend/admin/admin_add_donor.html', {'page_title': 'Add Donor', 'user': profile})
