import json
import asyncio
from datetime import datetime
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.dateparse import parse_datetime, parse_time
import httpx

from ..services import api_call, format_errors, get_paginated_data, get_fiber_choices


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
            api_call(request, 'GET', 'users/me/donations', params=claimed_params),
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
        'donations_json': {
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
        }
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
        api_call(request, 'GET', 'clothing-types'),
        api_call(request, 'GET', 'brands')
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
            response = await api_call(request, 'POST', 'users/me/subscription', json=payload)
            
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


async def tuab_profile(request):
    """View for the TUAB's account profile. Always fetches fresh data."""
    response = await api_call(request, 'GET', 'users/me')
    if response.status_code == 200:
        business = response.json()
    else:
        business = request.user_profile.copy() if request.user_profile else {}

    fibers = business.get('target_fibers', '')
    business['fiber_list'] = [f.strip() for f in fibers.split(',') if f.strip()] if fibers else []

    return render(request, 'frontend/tuabs/tuab_profile.html', {
        'page_title': 'Account Profile',
        'sidebar_variant': 'tuab',
        'user': business,
        'business': business,
    })


async def tuab_edit_profile(request):
    """View for TUAB to edit their own profile. Handles AJAX updates."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST' and is_ajax:
        payload = request.POST.dict()
        user_id = payload.get('user_id')
        submitted_etag = payload.get('current_etag')

        password = payload.get('new_password')
        confirm_password = payload.get('confirm_password')
        if password:
            if password != confirm_password:
                return JsonResponse({'errors': {'password': ['Passwords do not match.']}}, status=400)
            payload['password'] = password

        if 'contact_no' in payload and payload['contact_no']:
            c = payload['contact_no']
            if c.startswith('0'):
                payload['contact_no'] = '+63' + c[1:]
            elif not c.startswith('+63'):
                payload['contact_no'] = '+63' + c

        for k in ['csrfmiddlewaretoken', 'current_etag', 'confirm_password', 'new_password', 'user_id', 'photo', 'upload']:
            payload.pop(k, None)

        files = {}
        if 'upload' in request.FILES:
            files['upload'] = request.FILES['upload']

        headers = {'If-Match': submitted_etag} if submitted_etag else {}
        try:
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
        except Exception as e:
            return JsonResponse({'error': f"System Error: {str(e)}"}, status=503)

    fibers, response = await asyncio.gather(
        get_fiber_choices(request),
        api_call(request, 'GET', 'users/me')
    )
    if response.status_code == 200:
        profile = response.json()
        etag = response.headers.get('ETag')
        contact = profile.get('contact_no', '')
        if contact and contact.startswith('+63'):
            profile['contact_no'] = contact[3:]
    else:
        messages.error(request, "Unable to fetch latest profile data.")
        return redirect('tuab_profile')

    return render(request, 'frontend/tuabs/tuab_edit_profile.html', {
        'page_title': 'Edit Profile',
        'user': profile,
        'current_etag': etag,
        'sidebar_variant': 'tuab',
        'fibers': fibers,
    })

async def tuab_view_payments(request):
    """View TUAB payment history."""
    profile = request.user_profile
    reference = request.GET.get('reference', '')
    
    page_data = await get_paginated_data(request, 'users/me/payments', params={'reference': reference} if reference else None)
    
    return render(request, 'frontend/tuabs/tuab_view_payments.html', {
        'page_title': 'Payments',
        'sidebar_variant': 'tuab',
        'user': profile,
        'payments_json': page_data['results'],
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': page_data['search_query']
    })


async def tuab_inventory_snapshot(request):
    """View for TUAB inventory snapshot dashboard showing real-time raw material stock levels."""
    profile = request.user_profile
    
    # Fetch inventory snapshot summary and list
    snapshot_res, inventory_list_res = await asyncio.gather(
        api_call(request, 'GET', 'inventory/snapshot'),
        api_call(request, 'GET', 'inventory'),
        return_exceptions=True
    )
    
    snapshot_data = {}
    inventory_items = []
    
    if snapshot_res and not isinstance(snapshot_res, Exception) and snapshot_res.status_code == 200:
        snapshot_data = snapshot_res.json()
    
    if inventory_list_res and not isinstance(inventory_list_res, Exception) and inventory_list_res.status_code == 200:
        data = inventory_list_res.json()
        if isinstance(data, dict) and 'results' in data:
            inventory_items = data.get('results', [])
        else:
            inventory_items = data if isinstance(data, list) else []
    
    # Parse and format inventory items for display
    formatted_items = []
    for item in inventory_items:
        source_donation = item.get('source_donation', {})
        updated_raw = item.get('updated_at', '')
        last_audit = ''
        if updated_raw:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(updated_raw.replace('Z', '+00:00'))
                last_audit = dt.strftime('%-m-%-d-%Y')
            except Exception:
                last_audit = updated_raw[:10]
        formatted_item = {
            'inventory_id': item.get('inventory_id'),
            'donation_id': source_donation.get('donation_id'),
            'donor_name': f"{source_donation.get('donor', {}).get('first_name', '')} {source_donation.get('donor', {}).get('last_name', '')}".strip(),
            'address': source_donation.get('pickup_display_address', ''),
            'items_count': len(source_donation.get('items', [])),
            'current_weight_kg': float(item.get('current_weight_kg', 0)),
            'weight_before_kg': float(item.get('weight_before_kg', 0)),
            'usage_amount_kg': float(item.get('usage_amount_kg', 0)),
            'low_stock_threshold': float(item.get('low_stock_threshold', 1.3)),
            'audit_required': item.get('audit_required', False),
            'days_since_audit': item.get('days_since_audit', 0),
            'material_category': item.get('material_category', 'Mixed'),
            'last_audit': last_audit,
        }
        formatted_items.append(formatted_item)
    
    # Prepare map data for Leaflet
    locations_data = []
    for item in inventory_items:
        source_donation = item.get('source_donation', {})
        if source_donation.get('pickup_latitude') and source_donation.get('pickup_longitude'):
            locations_data.append({
                'lat': float(source_donation.get('pickup_latitude')),
                'lng': float(source_donation.get('pickup_longitude')),
                'donor': f"{source_donation.get('donor', {}).get('first_name', '')} {source_donation.get('donor', {}).get('last_name', '')}".strip(),
                'address': source_donation.get('pickup_display_address', ''),
                'inventory_id': item.get('inventory_id'),
            })
    
    return render(request, 'frontend/tuabs/tuab_inventory_snapshot.html', {
        'page_title': 'Inventory Snapshot',
        'sidebar_variant': 'tuab',
        'user': profile,
        'snapshot_data': snapshot_data,
        'inventory_items': formatted_items,
        'locations_json': json.dumps(locations_data),
        'total_items': snapshot_data.get('total_items', 0),
        'total_weight_kg': float(snapshot_data.get('total_weight_kg', 0)),
        'audit_required_count': snapshot_data.get('audit_required_count', 0),
        'category_summary': snapshot_data.get('category_summary', [])
    })


async def tuab_view_inventory_item(request, inventory_id):
    """View for TUAB to see detailed inventory item information including audit history."""
    profile = request.user_profile
    
    # Fetch inventory detail and audit history
    detail_res, audit_res = await asyncio.gather(
        api_call(request, 'GET', f'inventory/{inventory_id}'),
        api_call(request, 'GET', f'inventory/{inventory_id}/audit-history'),
        return_exceptions=True
    )
    
    if not detail_res or isinstance(detail_res, Exception) or detail_res.status_code != 200:
        messages.error(request, "Inventory item not found.")
        return redirect('tuab_inventory_snapshot')
    
    inventory_item = detail_res.json()
    audit_history = {}
    
    if audit_res and not isinstance(audit_res, Exception) and audit_res.status_code == 200:
        audit_history = audit_res.json()
    
    # Extract source donation and items information
    source_donation = inventory_item.get('source_donation', {})
    donor = source_donation.get('donor', {})
    items = source_donation.get('items', [])
    
    # Parse dates if needed
    if source_donation.get('preferred_pickup_date'):
        source_donation['preferred_pickup_date'] = parse_datetime(source_donation['preferred_pickup_date'])
    
    return render(request, 'frontend/tuabs/tuab_view_inventory_item.html', {
        'page_title': 'View Inventory',
        'sidebar_variant': 'tuab',
        'user': profile,
        'inventory_item': inventory_item,
        'source_donation': source_donation,
        'donor': donor,
        'items': items,
        'audit_history': audit_history,
        'pickup_address': source_donation.get('pickup_display_address', ''),
        'pickup_latitude': source_donation.get('pickup_latitude', ''),
        'pickup_longitude': source_donation.get('pickup_longitude', ''),
    })



async def tuab_inventory_update_usage_proxy(request, inventory_id):
    """Proxy: PATCH usage amount for an inventory item."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        body = json.loads(request.body)
        res = await api_call(request, 'PATCH', f'inventory/{inventory_id}/update-usage', json=body)
        return JsonResponse(res.json(), status=res.status_code)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=503)


async def tuab_inventory_archive_proxy(request, inventory_id):
    """Proxy: Archive an inventory item with an exit state."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        body = json.loads(request.body)
        res = await api_call(request, 'PATCH', f'inventory/{inventory_id}/archive', json=body)
        return JsonResponse(res.json(), status=res.status_code)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=503)


async def tuab_inventory_restore_proxy(request, inventory_id):
    """Proxy: Restore (undo) a recently archived inventory item."""
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        res = await api_call(request, 'PATCH', f'inventory/{inventory_id}/restore', json={})
        return JsonResponse(res.json(), status=res.status_code)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=503)


async def tuab_circular_economy(request):
    """TUAB Circular Economy Impact Dashboard — Chart.js 4-panel view."""
    profile = request.user_profile

    date_from = request.GET.get('date_from', '')
    date_to   = request.GET.get('date_to', '')

    params = {}
    if date_from:
        params['date_from'] = date_from
    if date_to:
        params['date_to'] = date_to

    dashboard_data = {
        'biodeg_distribution': [],
        'volume_by_city_fiber': [],
        'top_brands': [],
        'decisions_by_city': [],
    }
    error_message = None

    try:
        res = await api_call(request, 'GET', 'tuab-circular-economy', params=params)
        if res and not isinstance(res, Exception) and res.status_code == 200:
            dashboard_data = res.json()
        elif res and not isinstance(res, Exception) and res.status_code == 403:
            error_message = "Access denied. Only TUABs can view this dashboard."
        else:
            error_message = "Unable to load dashboard data. Please try again later."
    except Exception:
        error_message = "An error occurred while loading the dashboard."

    return render(request, 'frontend/tuabs/tuab_circular_economy.html', {
        'page_title': 'Circular Economy',
        'sidebar_variant': 'tuab',
        'user': profile,
        'date_from': date_from,
        'date_to': date_to,
        'error_message': error_message,
        'dashboard_json': json.dumps(dashboard_data),
    })


async def tuab_view_fiber_match_recommendations(request):
    """TUAB Fiber-Match Recommendations - View and act on donation recommendations."""
    profile = request.user_profile
    page = request.GET.get('page', 1)

    filters_param = {
        'fiber_type': request.GET.get('fiber_type', ''),
        'biodeg_tier': request.GET.get('biodeg_tier', ''),
        'city': request.GET.get('city', ''),
        'confidence_min': request.GET.get('confidence_min', ''),
        'confidence_max': request.GET.get('confidence_max', ''),
        'date_after': request.GET.get('date_after', ''),
        'date_before': request.GET.get('date_before', ''),
    }

    recommendations = []
    pagination_meta = {'current': int(page), 'has_next': False, 'has_prev': int(page) > 1, 'count': 0}
    error_message = None

    try:
        params = {'page': page}
        for key, value in filters_param.items():
            if value:
                if key == 'confidence_min':
                    try:
                        params['confidence_min'] = float(value)
                    except (ValueError, TypeError):
                        pass
                elif key == 'confidence_max':
                    try:
                        params['confidence_max'] = float(value)
                    except (ValueError, TypeError):
                        pass
                elif key != 'biodeg_tier':
                    params[key] = value

        res = await api_call(request, 'GET', 'match-recommendations', params=params)


        if res and not isinstance(res, Exception) and res.status_code == 200:
            data = res.json()
            recommendations = data.get('results', [])
            pagination_meta['has_next'] = data.get('next') is not None
            pagination_meta['count'] = data.get('count', 0)
        elif res and not isinstance(res, Exception) and res.status_code == 403:
            error_message = "You don't have an active subscription to access Donation Recommendations. Please upgrade."
        else:
            error_message = "Unable to load recommendations. Please try again later."
    except Exception:
        error_message = "An error occurred while loading recommendations."

    available_fibers = []
    available_cities = set()


    try:
        fibers_res = await api_call(request, 'GET', 'fibers')
        if fibers_res and not isinstance(fibers_res, Exception) and fibers_res.status_code == 200:
            data = fibers_res.json()
            available_fibers = data.get('results', []) if isinstance(data, dict) else data
    except Exception:
        pass

    for rec in recommendations:
        city = rec.get('donation', {}).get('pickup_city', '')
        if city:
            available_cities.add(city)

    return render(request, 'frontend/tuabs/tuab_view_fiber_match_recommendations.html', {
        'page_title': 'Fiber-Match Recommendations',
        'sidebar_variant': 'tuab',
        'user': profile,
        'recommendations': recommendations,
        'pagination_meta': pagination_meta,
        'error_message': error_message,
        'active_filters': filters_param,
        'available_fibers': available_fibers,
        'available_cities': sorted(list(available_cities)),
        'recommendations_json': json.dumps(recommendations),
    })
