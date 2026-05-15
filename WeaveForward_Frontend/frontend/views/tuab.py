import json
from datetime import datetime
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.dateparse import parse_datetime, parse_time

from ..services import api_call, BackendUnavailable

def tuab_dashboard(request):
    """TUAB Dashboard showing available and claimed donations (SSR with Pagination)."""
    profile = request.user_profile
    
    # Get page and search parameters from query string
    avail_page = request.GET.get('avail_page', 1)
    claimed_page = request.GET.get('claimed_page', 1)
    search_query = request.GET.get('q', '')
    
    available_donations = []
    my_claimed_donations = []
    avail_meta = {'current': int(avail_page), 'has_next': False, 'has_prev': int(avail_page) > 1}
    claimed_meta = {'current': int(claimed_page), 'has_next': False, 'has_prev': int(claimed_page) > 1}

    # Helper for date formatting
    def format_date(iso_str):
        try:
            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
            return dt.strftime('%b-%d-%Y')
        except:
            return iso_str[:10]

    # Common params for both calls
    common_params = {'search': search_query} if search_query else {}

    # 1. Fetch Available Donations
    try:
        params = {'page': avail_page}
        params.update(common_params)
        response = api_call(request, 'GET', 'donations', params=params)
        if response.status_code == 200:
            data = response.json()
            available_donations = data.get('results', [])
            avail_meta['has_next'] = data.get('next') is not None
            avail_meta['count'] = data.get('count', 0)
    except Exception:
        pass

    # 2. Fetch My Claimed Donations
    try:
        params = {'page': claimed_page}
        params.update(common_params)
        response = api_call(request, 'GET', 'donations/me', params=params)
        if response.status_code == 200:
            data = response.json()
            my_claimed_donations = data.get('results', [])
            claimed_meta['has_next'] = data.get('next') is not None
            claimed_meta['count'] = data.get('count', 0)
    except Exception:
        pass

    return render(request, 'frontend/tuabs/tuab_dashboard.html', {
        'page_title': 'Dashboard',
        'sidebar_variant': 'tuab',
        'user': profile,
        'available_donations': available_donations,
        'my_claimed_donations': my_claimed_donations,
        'avail_meta': avail_meta,
        'claimed_meta': claimed_meta,
        'active_tab': request.GET.get('tab', 'available'),
        'search_query': search_query,
        'donations_json': json.dumps({
            'available': [
                {
                    'id': d['donation_id'],
                    'donor': f"{d['donor']['first_name']} {d['donor']['last_name']}",
                    'address': d['pickup_display_address'],
                    'pickupDate': format_date(d['preferred_pickup_date']),
                    'items': len(d['items']),
                    'lat': float(d['pickup_latitude']),
                    'lng': float(d['pickup_longitude']),
                } for d in available_donations
            ],
            'claimed': [
                {
                    'id': d['donation_id'],
                    'donor': f"{d['donor']['first_name']} {d['donor']['last_name']}",
                    'address': d['pickup_display_address'],
                    'pickupDate': format_date(d['preferred_pickup_date']),
                    'items': len(d['items']),
                    'lat': float(d['pickup_latitude']),
                    'lng': float(d['pickup_longitude']),
                } for d in my_claimed_donations
            ]
        })
    })

def tuab_view_donation(request, donation_id):
    """TUAB detail page for viewing and claiming a single donation."""
    profile = request.user_profile

    if request.method == 'POST':
        is_json_request = 'application/json' in (request.content_type or '')
        try:
            payload = json.loads(request.body.decode('utf-8')) if is_json_request and request.body else request.POST.dict()
        except json.JSONDecodeError:
            payload = request.POST.dict()

        headers = {'If-Match': payload.get('current_etag')} if payload.get('current_etag') else {}
        try:
            response = api_call(
                request,
                'POST',
                f'donations/{donation_id}/claim',
                json={
                    'delivery_method': payload.get('delivery_method'),
                    'quotation_token': payload.get('quotation_token'),
                },
                headers=headers,
            )
        except BackendUnavailable:
            if is_json_request:
                return JsonResponse({'detail': 'Backend service unreachable.'}, status=503)
            raise

        try:
            data = response.json()
        except Exception:
            data = {'detail': 'Backend returned an invalid response.'}

        if is_json_request:
            return JsonResponse(data, status=response.status_code, safe=not isinstance(data, list))

        if 200 <= response.status_code < 300:
            messages.success(request, data.get('detail') or 'Donation claim submitted successfully.')
            return redirect('tuab_dashboard')

        messages.error(request, data.get('detail') or 'Unable to submit the donation claim.')
        return redirect('tuab_view_donation', donation_id=donation_id)

    response = api_call(request, 'GET', f'donations/{donation_id}')
    if response.status_code != 200:
        messages.error(request, "Donation not found or access denied.")
        return redirect('tuab_dashboard')

    donation = response.json()
    for field in ('preferred_pickup_date', 'submitted_at', 'updated_at'):
        donation[field] = parse_datetime(donation[field])
    for field in ('preferred_pickup_window_start', 'preferred_pickup_window_end'):
        donation[field] = parse_time(donation[field])

    # Preserve the existing template contract while using the current backend payload.
    donation['user_id'] = donation.get('donor') or {}
    donation['upload_id'] = {'file_path': donation.get('upload') or ''}
    donation['pickup_address'] = donation.get('pickup_display_address') or donation.get('pickup_address') or ''
    donation['dropoff_display_address'] = profile.get('display_address', '')
    donation['dropoff_latitude'] = profile.get('latitude', '')
    donation['dropoff_longitude'] = profile.get('longitude', '')

    items = donation.get('items', [])
    for item in items:
        item['lookup'] = item.get('lookup_details') or {}

    return render(request, 'frontend/tuabs/tuab_view_donation.html', {
        'page_title': f"Donation {donation.get('donation_id')}",
        'sidebar_variant': 'tuab',
        'user': profile,
        'users': profile,
        'donation': donation,
        'items': items,
        'current_etag': response.headers.get('ETag', ''),
        'default_dropoff_address': profile.get('display_address', ''),
        'default_dropoff_latitude': profile.get('latitude', ''),
        'default_dropoff_longitude': profile.get('longitude', ''),
    })


def tuab_quotation_proxy(request, donation_id):
    """Proxy quotation requests for authenticated TUABs only."""
    profile = request.user_profile
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed.'}, status=405)
    if not profile or profile.get('role') != 'TUAB':
        return JsonResponse(
            {'detail': 'Only authenticated TUABs can use this endpoint.'},
            status=403 if profile else 401,
        )

    payload = json.loads(request.body or '{}')

    headers = {'If-Match': payload.get('current_etag')} if payload.get('current_etag') else {}
    try:
        response = api_call(
            request,
            'POST',
            f'donations/{donation_id}/quotation',
            json={
                'dropoff_address': payload.get('dropoff_address'),
                'dropoff_lat': payload.get('dropoff_lat'),
                'dropoff_lng': payload.get('dropoff_lng'),
                'scheduled_time': payload.get('scheduled_time'),
            },
            headers=headers,
        )
        return JsonResponse(response.json(), status=response.status_code)
    except BackendUnavailable:
        return JsonResponse({'detail': 'Backend service unreachable.'}, status=503)


def tuab_subscribe(request):
    """Handle TUAB Premium Subscription."""
    profile = request.user_profile

    # Always force fetch the latest profile directly from the backend to guarantee fresh subscription status
    try:
        response = api_call(request, 'GET', 'users/me')
        if response.status_code == 200:
            profile = response.json()
            if hasattr(request, 'session'):
                request.session['user_profile'] = profile
                import time
                request.session['user_profile_verified_at'] = time.time()
    except Exception:
        pass
            
    # 1. Check if already subscribed (Success state)
    if profile.get('is_subscribed'):
        return render(request, 'frontend/tuabs/tuab_subscribe_to_premium_success.html', {
            'page_title': 'Subscribe for Premium Features',
            'sidebar_variant': 'tuab',
            'user': profile
        })

    # 2. Failure check: Explicitly check for the 'failed' status
    if request.GET.get('status') == 'failed':
        return render(request, 'frontend/tuabs/tuab_subscribe_to_premium_failed.html', {
            'page_title': 'Subscribe for Premium Features',
            'sidebar_variant': 'tuab',
            'user': profile
        })

    if request.method == 'POST':
        # Extract data from the form
        payload = {
            'firstName': request.POST.get('first_name'),
            'lastName': request.POST.get('last_name'),
            'card': {
                'number': request.POST.get('card_number'),
                'expMonth': request.POST.get('exp_month'),
                'expYear': request.POST.get('exp_year'),
                'cvc': request.POST.get('cvv'),
            }
        }

        try:
            response = api_call(request, 'POST', f'users/{profile["user_id"]}/subscription', json=payload)
            
            if response.status_code == 200:
                data = response.json()
                verification_url = data.get('verificationUrl')
                if verification_url:
                    return redirect(verification_url)
                
                messages.success(request, "Successfully subscribed to Premium!")
                return redirect('tuab_subscribe') # Redirect to itself to show success template
            else:
                # Redirect to failed state for any backend rejection
                return redirect('/tuab/subscribe/?status=failed')
        except Exception as e:
            messages.error(request, f"Error communicating with backend: {str(e)}")
            return redirect('/tuab/subscribe/?status=failed')

    return render(request, 'frontend/tuabs/tuab_subscribe_to_premium.html', {
        'page_title': 'Subscribe for Premium Features',
        'sidebar_variant': 'tuab',
        'user': profile,
    })
