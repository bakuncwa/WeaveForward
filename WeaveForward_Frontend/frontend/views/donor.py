import json
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.dateparse import parse_datetime, parse_time
from ..services import api_call, format_errors, get_paginated_data, get_fiber_choices


def donor_browse_businesses(request):
    """Donor Dashboard - Browsing active TUABs."""
    profile = request.user_profile
    
    # Categories for filter from Service (Matches Registration)
    categories = get_fiber_choices(request)
    
    # Capture filter params
    params = {'role': 'TUAB', 'status': 'ACTIVE'}
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    category = request.GET.get('category')
    
    if lat and lng:
        params['lat'] = lat
        params['lng'] = lng
    if category:
        params['category'] = category
        
    p_data = get_paginated_data(request, 'users', params=params)
    
    # Process target_fibers into lists for template
    for biz in p_data.get('results', []):
        fibers = biz.get('target_fibers', '')
        if fibers:
            biz['fiber_list'] = [f.strip() for f in fibers.split(',') if f.strip()][:3]
        else:
            biz['fiber_list'] = ['upcycling']
    
    return render(request, 'frontend/donor/donor_browse_businesses.html', {
        'page_title': 'Browse Businesses', 
        'user': profile,
        'sidebar_variant': 'donor',
        'businesses': p_data['results'],
        'categories': categories,
        'count': p_data['count'],
        'total_pages': p_data['total_pages'],
        'current_page': p_data['current_page'],
        'has_next': p_data['has_next'],
        'has_prev': p_data['has_prev'],
        'page_range': range(1, p_data['total_pages'] + 1),
        'q': p_data['search_query']
    })

def donor_my_donations(request):
    """View to list the logged-in donor's donations."""
    profile = request.user_profile

    # Fetch from /api/donations/me/
    response = api_call(request, 'GET', 'donations/me')
    donations_data = {}
    donations_list = []
    if response.status_code == 200:
        donations_data = response.json()
        donations_list = donations_data.get('results', [])
        
        # Parse strings to objects for template formatting
        for d in donations_list:
            if d.get('preferred_pickup_date'):
                d['preferred_pickup_date'] = parse_datetime(d['preferred_pickup_date'])
            if d.get('preferred_pickup_window_start'):
                d['preferred_pickup_window_start'] = parse_time(d['preferred_pickup_window_start'])
            if d.get('preferred_pickup_window_end'):
                d['preferred_pickup_window_end'] = parse_time(d['preferred_pickup_window_end'])

    return render(request, 'frontend/donor/donor_my_donations.html', {
        'page_title': 'My Donations',
        'user': profile,
        'sidebar_variant': 'donor',
        'donations': donations_list,
        'count': donations_data.get('count', 0),
    })

def donor_view_donation(request, donation_id):
    profile = request.user_profile
    if not profile:
        return redirect('login')

    response = api_call(request, 'GET', f'donations/{donation_id}')
    if response.status_code != 200:
        messages.error(request, "Donation not found or access denied.")
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
        'sidebar_variant': 'donor',
        'donation': donation,
        'items': donation.get('items', [])
    })

def donor_view_tuab(request, user_id):
    """View to see details of a specific TUAB business."""
    profile = request.user_profile

    response = api_call(request, 'GET', f'users/{user_id}')
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
        'sidebar_variant': 'donor',
        'business': business,
    })

def donor_create_donation(request):
    """View for donors to create a new donation."""
    profile = request.user_profile
    if not profile:
        return redirect('login')

    if request.method == 'POST':
        payload = request.POST.dict()
        files = {}
        if 'donation_image' in request.FILES:
            files['donation_image'] = request.FILES['donation_image']
            
        try:
            response = api_call(request, 'POST', 'donations', data=payload, files=files)
            if response.status_code == 201:
                messages.success(request, "Donation request created successfully!")
                return redirect('donor_my_donations')
            else:
                response_data = response.json() if hasattr(response, 'json') else {}
                if isinstance(response_data, dict) and 'detail' in response_data:
                    messages.error(request, response_data['detail'])
                else:
                    errs = format_errors(response_data)
                    for field, msg_list in errs.items():
                        for msg in msg_list:
                            messages.error(request, f"{field}: {msg}")
        except Exception as e:
            messages.error(request, f"System Error: {str(e)}")

        # Fallback if error occurs: re-fetch lookups
        lookups = []
        res = api_call(request, 'GET', 'brandfiberlookups')
        if res.status_code == 200:
            data = res.json()
            lookups = data if isinstance(data, list) else data.get('results', [])

        return render(request, 'frontend/donor/donor_create_donation.html', {
            'page_title': 'Create Donation',
            'user': profile,
            'sidebar_variant': 'donor',
            'catalog_json': json.dumps(lookups),
            'form_data': payload
        })

    # GET Request
    lookups = []
    res = api_call(request, 'GET', 'brandfiberlookups')
    if res.status_code == 200:
        data = res.json()
        lookups = data if isinstance(data, list) else data.get('results', [])

    return render(request, 'frontend/donor/donor_create_donation.html', {
        'page_title': 'Create Donation',
        'user': profile,
        'sidebar_variant': 'donor',
        'catalog_json': json.dumps(lookups)
    })

def donor_profile(request):
    """View for the donor's account profile."""
    profile = request.user_profile.copy() if request.user_profile else {}
    
    if profile.get('created_at'):
        profile['created_at'] = parse_datetime(profile['created_at'])
        
    return render(request, 'frontend/donor/donor_profile.html', {
        'page_title': 'Account Profile',
        'user': profile,
        'sidebar_variant': 'donor'
    })
