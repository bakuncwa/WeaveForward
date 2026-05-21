import json
import asyncio
from datetime import datetime
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.dateparse import parse_datetime, parse_time
import httpx

from ..services import api_call, format_errors


async def tuab_dashboard(request):
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

    avail_params = {'page': avail_page}
    avail_params.update(common_params)
    
    claimed_params = {'page': claimed_page}
    claimed_params.update(common_params)

    # 1 & 2. Fetch Available and Claimed Donations in parallel
    try:
        avail_res, claimed_res = await asyncio.gather(
            api_call(request, 'GET', 'donations', params=avail_params),
            api_call(request, 'GET', 'donations/me', params=claimed_params),
            return_exceptions=True
        )
    except Exception:
        avail_res, claimed_res = None, None

    # Process Available Donations response
    if avail_res and not isinstance(avail_res, Exception) and avail_res.status_code == 200:
        data = avail_res.json()
        available_donations = data.get('results', [])
        avail_meta['has_next'] = data.get('next') is not None
        avail_meta['count'] = data.get('count', 0)

    # Process Claimed Donations response
    if claimed_res and not isinstance(claimed_res, Exception) and claimed_res.status_code == 200:
        data = claimed_res.json()
        my_claimed_donations = data.get('results', [])
        claimed_meta['has_next'] = data.get('next') is not None
        claimed_meta['count'] = data.get('count', 0)

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
                    'status': d.get('status', ''),
                    'delivery_method': d.get('delivery_method', ''),
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
                    'status': d.get('status', ''),
                    'delivery_method': d.get('delivery_method', ''),
                    'items': len(d['items']),
                    'lat': float(d['pickup_latitude']),
                    'lng': float(d['pickup_longitude']),
                } for d in my_claimed_donations
            ]
        })
    })


async def tuab_view_donation(request, donation_id):
    """TUAB detail page for viewing and claiming a single donation."""
    profile = request.user_profile

    # =========================
    # POST: Action Submit
    # =========================
    if request.method == 'POST':
        is_json_request = 'application/json' in (request.content_type or '')
        try:
            payload = json.loads(request.body.decode('utf-8')) if is_json_request and request.body else request.POST.dict()
        except json.JSONDecodeError:
            payload = request.POST.dict()

        headers = {'If-Match': payload.get('current_etag')} if payload.get('current_etag') else {}
        action = payload.get('action')

        try:
            if action == 'transit':
                response = await api_call(
                    request,
                    'POST',
                    f'donations/{donation_id}/transit',
                    headers=headers,
                )

            elif action == 'claim' or action is None:
                response = await api_call(
                    request,
                    'POST',
                    f'donations/{donation_id}/claim',
                    json={
                        'delivery_method': payload.get('delivery_method'),
                        'quotation_token': payload.get('quotation_token'),
                    },
                    headers=headers,
                )

            else:
                response = JsonResponse({'detail': 'Unsupported action.'}, status=400)
        except httpx.RequestError:
            if is_json_request:
                return JsonResponse({'detail': 'Backend service unreachable.'}, status=503)
            raise

        try:
            data = response.json() if hasattr(response, 'json') else json.loads(response.content)
        except Exception:
            data = {'detail': 'Backend returned an invalid response.'}

        if is_json_request:
            return JsonResponse(data, status=response.status_code if hasattr(response, 'status_code') else 400, safe=not isinstance(data, list))

        if hasattr(response, 'status_code') and 200 <= response.status_code < 300:
            messages.success(request, data.get('detail') or 'Donation claim submitted successfully.')
            return redirect('tuab_dashboard')

        messages.error(request, data.get('detail') or 'Unable to submit the donation claim.')
        return redirect('tuab_view_donation', donation_id=donation_id)

    # =========================
    # GET: Shared Donation Fetch
    # =========================
    response = await api_call(request, 'GET', f'donations/{donation_id}')
    if response.status_code != 200:
        if response.status_code == 403:
            messages.error(request, "Access denied.")
        else:
            messages.error(request, "Donation not found.")
        return redirect('tuab_dashboard')

    donation = response.json()
    items = donation.get('items', [])

    # Parse date and times for all templates
    if donation.get('submitted_at'):
        dt = parse_datetime(donation['submitted_at'])
        donation['submitted_at'] = dt
        donation['created_at'] = dt
    if donation.get('updated_at'):
        donation['updated_at'] = parse_datetime(donation['updated_at'])
    if donation.get('auto_archive_at'):
        donation['auto_archive_at'] = parse_datetime(donation['auto_archive_at'])
    if donation.get('preferred_pickup_date'):
        donation['preferred_pickup_date'] = parse_datetime(donation['preferred_pickup_date'])
    if donation.get('preferred_pickup_window_start'):
        donation['preferred_pickup_window_start'] = parse_time(donation['preferred_pickup_window_start'])
    if donation.get('preferred_pickup_window_end'):
        donation['preferred_pickup_window_end'] = parse_time(donation['preferred_pickup_window_end'])

    # =========================
    # Show: Special Page for Owned Claimed Donation
    # =========================
    if (
        donation.get('status') == 'CLAIMED'
        and donation.get('delivery_method') in {'PICKUP', 'DELIVERY'}
        and (donation.get('claimed_by_tuab') or {}).get('user_id') == profile.get('user_id')
    ):
        return render(request, 'frontend/tuabs/tuab_mark_claimed_donation_as_IN_TRANSIT.html', {
            'page_title': 'View Donation',
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

    # =========================
    # Redirect: Owned In-Transit Donation
    # =========================
    if (
        donation.get('status') == 'IN_TRANSIT'
        and (donation.get('claimed_by_tuab') or {}).get('user_id') == profile.get('user_id')
    ):
        return redirect('tuab_update_incoming_donation', donation_id=donation_id)

    # =========================
    # Show: Received/Rejected Donation Page
    # =========================
    if donation.get('status') in {'RECEIVED', 'REJECTED'}:
        return render(request, 'frontend/tuabs/tuab_view_received_donation.html', {
            'page_title': 'View Donation',
            'sidebar_variant': 'tuab',
            'user': profile,
            'users': profile,
            'donation': donation,
            'items': items,
        })

    # =========================
    # Show: Standard Donation Detail Page
    # =========================
    return render(request, 'frontend/tuabs/tuab_view_donation.html', {
        'page_title': 'View Donation',
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


async def tuab_update_incoming_donation(request, donation_id):
    """TUAB page for updating/resolving an incoming donation (resolving at /edit)."""
    profile = request.user_profile

    # =========================
    # POST: Submit Resolution
    # =========================
    if request.method == 'POST':
        is_json_request = 'application/json' in (request.content_type or '')
        try:
            payload = json.loads(request.body.decode('utf-8')) if is_json_request and request.body else request.POST.dict()
        except json.JSONDecodeError:
            payload = request.POST.dict()

        payload.pop('csrfmiddlewaretoken', None)
        payload.pop('current_etag', None)

        try:
            response = await api_call(request, 'POST', f'donations/{donation_id}/resolve', data=payload)
            if response.status_code == 200:
                messages.success(request, "Donation resolved successfully!")
                return JsonResponse({'redirect': '/tuab/dashboard/'})
            else:
                try:
                    err_data = response.json()
                except:
                    err_data = {'detail': 'Unknown backend error.'}
                
                error_msg = err_data.get('detail')
                errors = []
                if error_msg:
                    errors.append(error_msg)
                elif isinstance(err_data, dict):
                    formatted = format_errors(err_data)
                    for field, msgs in formatted.items():
                        if isinstance(msgs, list):
                            for msg in msgs:
                                errors.append(f"{field}: {msg}")
                        else:
                            errors.append(f"{field}: {msgs}")
                
                if not errors:
                    errors.append("Resolution failed.")

                return JsonResponse({'errors': errors}, status=400)
        except Exception as e:
            return JsonResponse({'errors': [f"System Error: {str(e)}"]}, status=503)

    # =========================
    # GET: Render Resolve Form
    # =========================
    donation_res, types_res, brands_res = await asyncio.gather(
        api_call(request, 'GET', f'donations/{donation_id}'),
        api_call(request, 'GET', 'brandfiberlookups/clothing_types'),
        api_call(request, 'GET', 'brandfiberlookups/brands')
    )

    if donation_res.status_code != 200:
        if donation_res.status_code == 403:
            messages.error(request, "Access denied.")
        else:
            messages.error(request, "Donation not found.")
        return redirect('tuab_dashboard')

    donation = donation_res.json()

    # Validate that status is IN_TRANSIT and owned by this TUAB
    if (
        donation.get('status') != 'IN_TRANSIT'
        or (donation.get('claimed_by_tuab') or {}).get('user_id') != profile.get('user_id')
    ):
        messages.error(request, "You are not authorized to resolve this donation.")
        return redirect('tuab_view_donation', donation_id=donation_id)

    # Parse date and times
    if donation.get('submitted_at'):
        dt = parse_datetime(donation['submitted_at'])
        donation['submitted_at'] = dt
        donation['created_at'] = dt
    if donation.get('updated_at'):
        donation['updated_at'] = parse_datetime(donation['updated_at'])
    if donation.get('auto_archive_at'):
        donation['auto_archive_at'] = parse_datetime(donation['auto_archive_at'])
    if donation.get('preferred_pickup_date'):
        donation['preferred_pickup_date'] = parse_datetime(donation['preferred_pickup_date'])
    if donation.get('preferred_pickup_window_start'):
        donation['preferred_pickup_window_start'] = parse_time(donation['preferred_pickup_window_start'])
    if donation.get('preferred_pickup_window_end'):
        donation['preferred_pickup_window_end'] = parse_time(donation['preferred_pickup_window_end'])

    clothing_types = types_res.json() if types_res.status_code == 200 else []
    all_brands = brands_res.json() if brands_res.status_code == 200 else []

    return render(request, 'frontend/tuabs/tuab_update_incoming_donation.html', {
        'page_title': 'Update Donation',
        'user': profile,
        'donation': donation,
        'sidebar_variant': 'tuab',
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


async def tuab_quotation_proxy(request, donation_id):
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
        response = await api_call(
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
    except httpx.RequestError:
        return JsonResponse({'detail': 'Backend service unreachable.'}, status=503)


async def tuab_subscribe(request):
    """Handle TUAB Premium Subscription."""
    profile = request.user_profile

    # Always force fetch the latest profile directly from the backend to guarantee fresh subscription status
    try:
        response = await api_call(request, 'GET', 'users/me')
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
            response = await api_call(request, 'POST', f'users/{profile["user_id"]}/subscription', json=payload)
            
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
