import json
import asyncio
from datetime import datetime
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.dateparse import parse_datetime, parse_time
from ..services import api_call, format_errors, get_paginated_data, get_fiber_choices, get_user_profile


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
    avail_res, claimed_res = await asyncio.gather(
        api_call(request, 'GET', 'donations', params=avail_params),
        api_call(request, 'GET', 'users/me/donations', params=claimed_params),
        return_exceptions=True
    )

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

    donations_json = {
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
                'item_details': [
                    {
                        'type': i.get('lookup_details', {}).get('clothing_type', ''),
                        'brand': i.get('lookup_details', {}).get('brand', ''),
                        'fiber': i.get('lookup_details', {}).get('dominant_fiber', ''),
                    } for i in d.get('items', [])
                ],
                'pickup_window_start': d.get('preferred_pickup_window_start', ''),
                'pickup_window_end': d.get('preferred_pickup_window_end', ''),
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
                'item_details': [
                    {
                        'type': i.get('lookup_details', {}).get('clothing_type', ''),
                        'brand': i.get('lookup_details', {}).get('brand', ''),
                        'fiber': i.get('lookup_details', {}).get('dominant_fiber', ''),
                    } for i in d.get('items', [])
                ],
                'pickup_window_start': d.get('preferred_pickup_window_start', ''),
                'pickup_window_end': d.get('preferred_pickup_window_end', ''),
            } for d in my_claimed_donations
        ]
    }

    if 'application/json' in request.headers.get('Accept', ''):
        resp = JsonResponse({
            'donations': donations_json,
            'meta': {
                'available': {**avail_meta, 'total': avail_meta.get('count', 0)},
                'claimed': {**claimed_meta, 'total': claimed_meta.get('count', 0)},
            }
        })
        resp['Cache-Control'] = 'no-store'
        return resp

    return render(request, 'frontend/tuabs/tuab_dashboard.html', {
        'page_title': 'Dashboard',
        'user': profile,
        'available_donations': available_donations,
        'my_claimed_donations': my_claimed_donations,
        'avail_meta': avail_meta,
        'claimed_meta': claimed_meta,
        'active_tab': request.GET.get('tab', 'available'),
        'search_query': search_query,
        'donations_json': donations_json,
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

        try:
            data = response.json() if hasattr(response, 'json') else json.loads(response.content)
        except Exception:
            data = {'detail': 'Backend returned an invalid response.'}

        if is_json_request:
            return JsonResponse(data, status=response.status_code if hasattr(response, 'status_code') else 400, safe=not isinstance(data, list))

        if hasattr(response, 'status_code') and 200 <= response.status_code < 300:
            messages.success(request, data.get('detail') or 'Donation claim submitted successfully.')
            return redirect(f'/tuab/dashboard/?tab=claimed&claimed={donation_id}')

        if hasattr(response, 'status_code') and response.status_code == 412:
            messages.error(request, 'This donation was modified. Refresh and try again.')
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

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse(donation)
    profile = await get_user_profile(request) or profile

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
    # Show: Mark-as-Transit Page for Claimed Donations
    # =========================
    if donation.get('status') == 'CLAIMED' and donation.get('delivery_method') in {'PICKUP', 'DELIVERY'}:
        return render(request, 'frontend/tuabs/tuab_mark_claimed_donation_as_IN_TRANSIT.html', {
            'page_title': 'View Donation',
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
    # Redirect: In-Transit Donation to Resolve Page
    # =========================
    if donation.get('status') == 'IN_TRANSIT':
        return redirect('tuab_update_incoming_donation', donation_id=donation_id)

    # =========================
    # Show: Standard Donation Detail Page
    # =========================
    return render(request, 'frontend/tuabs/tuab_view_donation.html', {
        'page_title': 'View Donation',
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
        current_etag = payload.pop('current_etag', None)
        headers = {'If-Match': current_etag} if current_etag else {}

        response = await api_call(request, 'POST', f'donations/{donation_id}/resolve', data=payload, headers=headers)
        if response.status_code == 200:
            messages.success(request, "Donation resolved successfully!")
            return JsonResponse({'redirect': '/tuab/dashboard/'})
        elif response.status_code == 412:
            return JsonResponse({'errors': ['Your session has expired. Please refresh the page and try again.']}, status=409)
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
    current_etag = donation_res.headers.get('ETag', '')

    if request.headers.get('Accept') == 'application/json':
        resp = JsonResponse({**donation, 'current_etag': current_etag})
        resp['ETag'] = current_etag
        return resp

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
        'clothing_types': clothing_types,
        'all_brands': all_brands,
        'condition_choices': [
            ('NEW', 'New'),
            ('LIKE_NEW', 'Like New'),
            ('GOOD', 'Good'),
            ('FAIR', 'Fair'),
            ('POOR', 'Poor'),
        ],
        'current_etag': current_etag,
    })


async def tuab_quotation_proxy(request, donation_id):
    """Proxy quotation requests for authenticated TUABs only."""
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed.'}, status=405)

    payload = json.loads(request.body or '{}')

    headers = {'If-Match': payload.get('current_etag')} if payload.get('current_etag') else {}
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


async def tuab_subscribe(request):
    """Handle TUAB Premium Subscription."""
    profile = await get_user_profile(request) or request.user_profile
            
    # 1. Check if already subscribed or redirected back from successful Maya 3DS
    if profile.get('is_subscribed') or request.GET.get('status') == 'success':
        return render(request, 'frontend/tuabs/tuab_subscribe_to_premium_success.html', {
            'page_title': 'Subscribe for Premium Features',
            'user': profile
        })

    # 2. Failure check: Explicitly check for the 'failed' status
    if request.GET.get('status') == 'failed':
        return render(request, 'frontend/tuabs/tuab_subscribe_to_premium_failed.html', {
            'page_title': 'Subscribe for Premium Features',
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

        response = await api_call(
            request,
            'POST',
            'users/me/subscription',
            json=payload,
            headers={
                'X-Frontend-Redirect-Url': request.build_absolute_uri('/').rstrip('/'),
            },
        )
        
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

    return render(request, 'frontend/tuabs/tuab_subscribe_to_premium.html', {
        'page_title': 'Subscribe for Premium Features',
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

        for k in ['csrfmiddlewaretoken', 'current_etag', 'confirm_password', 'new_password', 'user_id', 'photo', 'upload', 'otp_code', 'secret', 'disable_2fa', 'remove_payment_method']:
            payload.pop(k, None)

        files = {}
        if 'upload' in request.FILES:
            files['upload'] = request.FILES['upload']

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
                
            if request.POST.get('remove_payment_method') == '1':
                await api_call(request, 'DELETE', 'users/me/subscription'); etag_changed = True
                
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
        'fibers': fibers,
    })

async def tuab_view_payments(request):
    """View TUAB payment history."""
    profile = request.user_profile
    reference = request.GET.get('reference', '')
    
    page_data = await get_paginated_data(request, 'users/me/payments', params={'reference': reference} if reference else None)
    for payment in page_data['results']:
        payment['amount'] = -float(payment['amount'])
    
    return render(request, 'frontend/tuabs/tuab_view_payments.html', {
        'page_title': 'Payments',
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
    search_query = request.GET.get('q', '')
    
    # 1. Fetch paginated data for the grid table
    page_data = await get_paginated_data(request, 'inventory', params={'search': search_query} if search_query else None)
    inventory_items = page_data['results']
    
    # 2. Extract category summary from the paginated response
    category_summary = page_data.get('category_summary', [])
    
    # Parse and format inventory items for display (current page only)
    formatted_items = []
    for item in inventory_items:
        source_donation = item.get('source_donation', {})
        updated_raw = item.get('updated_at', '')
        last_audit = ''
        if updated_raw:
            try:
                dt = datetime.fromisoformat(updated_raw.replace('Z', '+00:00'))
                last_audit = dt.strftime('%-m-%-d-%Y')
            except Exception:
                last_audit = updated_raw[:10]
        item_details = []
        for si in source_donation.get('items', []):
            ld = si.get('lookup_details', {})
            if ld:
                item_details.append({'fiber': ld.get('dominant_fiber', ''), 'type': ld.get('clothing_type', '')})
        formatted_item = {
            'inventory_id': item.get('inventory_id'),
            'donation_id': source_donation.get('donation_id'),
            'donor_name': f"{source_donation.get('donor', {}).get('first_name', '')} {source_donation.get('donor', {}).get('last_name', '')}".strip(),
            'address': source_donation.get('pickup_display_address', ''),
            'item_details': item_details,
            'item_details_json': json.dumps(item_details),
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
    
    return render(request, 'frontend/tuabs/tuab_inventory_snapshot.html', {
        'page_title': 'Inventory Snapshot',
        'user': profile,
        'inventory_items': formatted_items,
        'category_summary': category_summary,
        'count': page_data['count'],
        'total_pages': page_data['total_pages'],
        'current_page': page_data['current_page'],
        'has_next': page_data['has_next'],
        'has_prev': page_data['has_prev'],
        'q': search_query
    })


async def tuab_view_audit_history(request):
    """View all TUAB inventory audit history in a table, similar to admin view donors."""
    profile = request.user_profile
    response = await api_call(request, 'GET', 'inventory', params={'status': 'all', 'nopaginate': 'true'})
    inventory_items = response.json() if response.status_code == 200 else []
    if isinstance(inventory_items, dict):
        inventory_items = inventory_items.get('results', [])

    def format_audit_date(value):
        if not value:
            return ''
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            time_part = dt.strftime('%I:%M %p').lstrip('0')
            return f'{dt.month}-{dt.day}-{dt.year} {time_part}'
        except Exception:
            return value[:10]

    formatted_items = []
    for item in inventory_items:
        updated_raw = item.get('updated_at', '')
        notes = item.get('notes')
        try:
            notes_payload = json.loads(notes) if notes else {}
        except (TypeError, json.JSONDecodeError):
            notes_payload = {}

        usage_events = notes_payload.get('production_context') if isinstance(notes_payload, dict) else None
        if isinstance(usage_events, list) and usage_events:
            for event in usage_events:
                if not isinstance(event, dict):
                    continue
                audited_at = event.get('at') or updated_raw
                formatted_items.append({
                    'inventory_id': item.get('inventory_id'),
                    'weight_before_kg': float(event.get('before', 0)),
                    'usage_amount_kg': float(event.get('used', 0)),
                    'current_weight_kg': float(event.get('after', 0)),
                    'last_audit': format_audit_date(audited_at),
                    'sort_key': audited_at,
                })

    formatted_items.sort(key=lambda item: item.get('sort_key') or '', reverse=True)
    page_size = 10
    count = len(formatted_items)
    total_pages = max((count + page_size - 1) // page_size, 1)
    try:
        current_page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        current_page = 1
    current_page = min(max(current_page, 1), total_pages)
    start = (current_page - 1) * page_size
    end = start + page_size
    page_items = formatted_items[start:end]

    return render(request, 'frontend/tuabs/tuab_inventory_audit_history.html', {
        'page_title': 'Inventory Snapshot',
        'user': profile,
        'inventory_items': page_items,
        'count': count,
        'total_pages': total_pages,
        'current_page': current_page,
        'has_next': current_page < total_pages,
        'has_prev': current_page > 1,
    })


async def tuab_inventory_update_usage_proxy(request, inventory_id):
    """Proxy: POST usage amount for an inventory item."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    body = json.loads(request.body)
    res = await api_call(request, 'POST', f'inventory/{inventory_id}/update-usage', json=body)
    return JsonResponse(res.json(), status=res.status_code)


async def tuab_inventory_archive_proxy(request, inventory_id):
    """Proxy: Archive an inventory item with an exit state."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    body = json.loads(request.body)
    res = await api_call(request, 'POST', f'inventory/{inventory_id}/archive', json=body)
    return JsonResponse(res.json(), status=res.status_code)


async def tuab_inventory_restore_proxy(request, inventory_id):
    """Proxy: Restore (undo) a recently archived inventory item."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    res = await api_call(request, 'POST', f'inventory/{inventory_id}/restore', json={})
    return JsonResponse(res.json(), status=res.status_code)


async def tuab_inventory_export_proxy(request):
    """Proxy: GET unpaginated inventory export for CSV/JSON."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    res = await api_call(request, 'GET', 'inventory/export')
    return JsonResponse(res.json(), status=res.status_code)


async def tuab_match_recommendation_accept_proxy(request, pair_id):
    """Proxy: Accept a fiber-match recommendation."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    res = await api_call(request, 'POST', f'match-predict/{pair_id}/accept', json={})
    return JsonResponse(res.json(), status=res.status_code)


async def tuab_match_recommendation_reject_proxy(request, pair_id):
    """Proxy: Reject a fiber-match recommendation with optional reason."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    body = json.loads(request.body)
    res = await api_call(request, 'POST', f'match-predict/{pair_id}/reject', json=body)
    return JsonResponse(res.json(), status=res.status_code)



async def tuab_donation_flag_proxy(request, donation_id):
    """Proxy: Flag a donation with a reason (TUAB or Admin)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    body = json.loads(request.body)
    res = await api_call(request, 'POST', f'donations/{donation_id}/flag', json={'flag_reason': body.get('flag_reason', '')})
    return JsonResponse(res.json(), status=res.status_code)


async def tuab_circular_economy(request):
    """TUAB Circular Economy Impact Dashboard � Chart.js 4-panel view."""
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

    res = await api_call(request, 'GET', 'tuab-circular-economy', params=params)
    if res and not isinstance(res, Exception) and res.status_code == 200:
        dashboard_data = res.json()
    elif res and not isinstance(res, Exception) and res.status_code in (400, 422):
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
    elif res and not isinstance(res, Exception) and res.status_code == 403:
        try:
            error_message = res.json().get('detail', 'Access denied.')
        except Exception:
            error_message = "Access denied."
    else:
        error_message = "Unable to load dashboard data. Please try again later."

    return render(request, 'frontend/tuabs/tuab_circular_economy.html', {
        'page_title': 'Circular Economy Impact Dashboard',
        'user': profile,
        'date_from': date_from,
        'date_to': date_to,
        'today_iso': datetime.now().strftime('%Y-%m-%d'),
        'error_message': error_message,
        'dashboard_json': json.dumps(dashboard_data),
    })


async def tuab_view_fiber_match_recommendations(request):
    """TUAB Fiber-Match Recommendations - View and act on donation recommendations."""
    profile = request.user_profile

    me_res = await api_call(request, 'GET', 'users/me')
    if me_res and not isinstance(me_res, Exception) and me_res.status_code == 200:
        me_data = me_res.json()
        if not me_data.get('is_subscribed'):
            messages.error(request, "You need an active subscription to access Donation Recommendations.")
            return redirect('tuab_subscribe')

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
    error_message = None

    params = {'unpaginated': 'true'}
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
            else:
                params[key] = value

    res = await api_call(request, 'GET', 'match-predict', params=params)


    if res and not isinstance(res, Exception) and res.status_code == 200:
        data = res.json()
        if isinstance(data, list):
            recommendations = data
        else:
            recommendations = data.get('results', [])
    elif res and not isinstance(res, Exception) and res.status_code == 403:
        error_message = "You don't have an active subscription to access Donation Recommendations. Please upgrade."
    else:
        error_message = "Unable to load recommendations. Please try again later."

    available_fibers = []
    available_cities = set()


    fibers_res = await api_call(request, 'GET', 'fibers')
    if fibers_res and not isinstance(fibers_res, Exception) and fibers_res.status_code == 200:
        data = fibers_res.json()
        available_fibers = data.get('results', []) if isinstance(data, dict) else data

    for rec in recommendations:
        city = rec.get('donation', {}).get('pickup_city', '')
        if city:
            available_cities.add(city)

    return render(request, 'frontend/tuabs/tuab_view_fiber_match_recommendations.html', {
        'page_title': 'Fiber-Match Recommendations',
        'user': profile,
        'recommendations': recommendations,
        'error_message': error_message,
        'active_filters': filters_param,
        'available_fibers': available_fibers,
        'available_cities': sorted(list(available_cities)),
        'recommendations_json': json.dumps(recommendations),
    })
