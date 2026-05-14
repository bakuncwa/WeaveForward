from django.shortcuts import render, redirect
from django.contrib import messages
from ..services import api_call, format_errors
from ..constants import ALLOWED_FIBERS

def tuab_dashboard(request):
    """Placeholder for TUAB Dashboard."""
    profile = request.user_profile

    return render(request, 'frontend/base.html', {
        'page_title': 'TUAB Dashboard', 
        'user': profile
    })


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
            'page_title': 'Subscription Success',
            'sidebar_variant': 'tuab',
            'user': profile
        })

    # 2. Failure check: Explicitly check for the 'failed' status
    if request.GET.get('status') == 'failed':
        return render(request, 'frontend/tuabs/tuab_subscribe_to_premium_failed.html', {
            'page_title': 'Subscription Failed',
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
        'page_title': 'Premium Subscription',
        'sidebar_variant': 'tuab',
        'user': profile,
    })
