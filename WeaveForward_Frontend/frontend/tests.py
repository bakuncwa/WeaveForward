import base64
import json
import time
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse
from django.contrib.messages import get_messages
from requests.cookies import RequestsCookieJar


def make_response(status_code, payload=None, headers=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.headers = headers or {}
    response.cookies = RequestsCookieJar()
    return response


def make_access_token(expires_in=3600):
    payload = base64.b64encode(json.dumps({'exp': time.time() + expires_in}).encode()).decode().strip('=')
    return f"header.{payload}.signature"


class MiddlewareAuthMixin:
    auth_profile = {'role': 'Admin', 'first_name': 'Admin'}

    def setUp(self):
        super().setUp()
        self.client.cookies['access_token'] = make_access_token()
        self.middleware_request_patcher = patch(
            'frontend.services.api_service.requests.request',
            side_effect=self.mock_middleware_request,
        )
        self.mocked_middleware_request = self.middleware_request_patcher.start()
        self.addCleanup(self.middleware_request_patcher.stop)

    def mock_middleware_request(self, method, url, **kwargs):
        if url.endswith('/users/me'):
            return make_response(200, self.auth_profile)
        if url.endswith('/token/refresh'):
            response = make_response(200)
            response.cookies.set('access_token', make_access_token())
            return response
        raise AssertionError(f"Unexpected middleware request: {method} {url}")


class AuthViewsTest(TestCase):
    @patch('frontend.views.api_call')
    def test_login_mirrors_backend_auth_cookies(self, mocked_api_call):
        backend_response = make_response(200, {
            'user_id': 1,
            'role': 'Donor',
            'email': 'user@example.com',
            'name': 'Test User',
        })
        backend_response.cookies.set('access_token', 'access-cookie')
        backend_response.cookies.set('refresh_token', 'refresh-cookie')
        mocked_api_call.return_value = backend_response

        response = self.client.post(reverse('login'), {
            'email': 'user@example.com',
            'password': 'password123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('donor_browse_businesses'))
        self.assertEqual(response.cookies['access_token'].value, 'access-cookie')
        self.assertEqual(response.cookies['refresh_token'].value, 'refresh-cookie')

    @patch('frontend.views.api_call')
    def test_ajax_login_returns_json_redirect_and_auth_cookies(self, mocked_api_call):
        backend_response = make_response(200, {
            'user_id': 1,
            'role': 'Donor',
            'email': 'user@example.com',
        })
        backend_response.cookies.set('access_token', 'access-cookie')
        backend_response.cookies.set('refresh_token', 'refresh-cookie')
        mocked_api_call.return_value = backend_response

        response = self.client.post(
            reverse('login'),
            {
                'email': 'user@example.com',
                'password': 'password123',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect_url'], reverse('donor_browse_businesses'))
        self.assertEqual(response.cookies['access_token'].value, 'access-cookie')
        self.assertEqual(response.cookies['refresh_token'].value, 'refresh-cookie')

    @patch('frontend.views.api_call')
    def test_ajax_login_returns_2fa_required_payload(self, mocked_api_call):
        mocked_api_call.return_value = make_response(401, {
            '2fa_required': True,
        })

        response = self.client.post(
            reverse('login'),
            {
                'email': 'user@example.com',
                'password': 'password123',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['2fa_required'], True)
        self.assertEqual(response.json()['email'], 'user@example.com')

    @patch('frontend.views.api_call')
    def test_logout_calls_backend_without_refresh_body(self, mocked_api_call):
        mocked_api_call.return_value = make_response(205, {'message': 'Successfully logged out'})

        self.client.cookies['access_token'] = make_access_token()
        self.client.cookies['refresh_token'] = 'refresh-cookie'

        response = self.client.get(reverse('logout'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))
        # Use more robust way to check call arguments
        args, kwargs = mocked_api_call.call_args
        self.assertEqual(args[1:], ('POST', 'logout'))
        self.assertNotIn('json', mocked_api_call.call_args.kwargs)
        self.assertEqual(response.cookies['access_token'].value, '')
        self.assertEqual(response.cookies['refresh_token'].value, '')
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Successfully logged out.", messages)

    @patch('frontend.views.api_call')
    def test_logout_keeps_cookies_and_shows_error_when_backend_rejects(self, mocked_api_call):
        mocked_api_call.return_value = make_response(403, {'detail': 'CSRF Failed: missing or incorrect token.'})

        self.client.cookies['access_token'] = make_access_token()
        self.client.cookies['refresh_token'] = 'refresh-cookie'

        response = self.client.get(
            reverse('logout'),
            HTTP_REFERER=reverse('donor_browse_businesses')
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('donor_browse_businesses'))
        self.assertNotIn('access_token', response.cookies)
        self.assertNotIn('refresh_token', response.cookies)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn('CSRF Failed: missing or incorrect token.', messages)

    @patch('frontend.services.api_service.requests.request')
    def test_login_get_redirects_valid_authenticated_user(self, mocked_requests):
        self.client.cookies['access_token'] = make_access_token()
        mocked_requests.return_value = make_response(200, {
            'user_id': 1,
            'role': 'Donor',
            'email': 'user@example.com',
            'name': 'Test User',
        })

        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('donor_browse_businesses'))

    @patch('frontend.services.api_service.requests.request')
    def test_registration_get_redirects_valid_authenticated_user(self, mocked_requests):
        self.client.cookies['access_token'] = make_access_token()
        mocked_requests.return_value = make_response(200, {
            'user_id': 2,
            'role': 'TUAB',
            'email': 'tuab@example.com',
            'name': 'Weave Lab',
        })

        response = self.client.get(reverse('tuab_registration'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('tuab_dashboard'))

    @patch('frontend.services.api_service.requests.request')
    def test_login_get_invalid_session_clears_cookies_and_renders_page(self, mocked_requests):
        self.client.cookies['access_token'] = make_access_token()
        self.client.cookies['refresh_token'] = 'refresh-cookie'
        mocked_requests.return_value = make_response(401, {'detail': 'Unauthorized'})

        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies['access_token'].value, '')
        self.assertEqual(response.cookies['refresh_token'].value, '')

    @patch('frontend.services.api_service.requests.request')
    def test_login_get_backend_outage_keeps_cookies_and_renders_page(self, mocked_requests):
        self.client.cookies['access_token'] = make_access_token()
        self.client.cookies['refresh_token'] = 'refresh-cookie'
        mocked_requests.return_value = make_response(500, {'detail': 'Server error'})

        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 503)
        self.assertNotIn('access_token', response.cookies)
        self.assertNotIn('refresh_token', response.cookies)

    @patch('frontend.services.api_service.requests.request')
    def test_protected_page_invalid_session_redirects_to_login(self, mocked_requests):
        self.client.cookies['access_token'] = make_access_token()
        self.client.cookies['refresh_token'] = 'refresh-cookie'
        mocked_requests.return_value = make_response(401, {'detail': 'Unauthorized'})

        response = self.client.get(reverse('donor_browse_businesses'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))
        self.assertEqual(response.cookies['access_token'].value, '')
        self.assertEqual(response.cookies['refresh_token'].value, '')

    @patch('frontend.services.api_service.requests.request')
    def test_protected_page_refreshes_missing_access_and_renders(self, mocked_requests):
        self.client.cookies['refresh_token'] = 'refresh-cookie'
        self.client.cookies['csrftoken'] = 'csrf-cookie'
        responses = [
            make_response(401, {'detail': 'Expired'}),
            make_response(200),
            make_response(200, {
                'user_id': 1, 'role': 'Donor', 'email': 'user@example.com', 'name': 'Test User'
            }),
            make_response(200, ['Cotton']),
            make_response(200, {
                'results': [], 'count': 0, 'total_pages': 1, 'current_page': 1, 'has_next': False, 'has_prev': False, 'search_query': ''
            }),
        ]
        responses[1].cookies.set('access_token', make_access_token())
        responses[1].cookies.set('refresh_token', 'rotated-refresh')
        mocked_requests.side_effect = responses
        response = self.client.get(reverse('donor_browse_businesses'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Browse Businesses')
        self.assertEqual(response.cookies['access_token'].value.count('.'), 2)
        self.assertEqual(response.cookies['refresh_token'].value, 'rotated-refresh')
        self.assertEqual(mocked_requests.call_count, 5)

    @patch('frontend.services.api_service.requests.request')
    def test_protected_page_backend_outage_returns_503_without_clearing_cookies(self, mocked_requests):
        self.client.cookies['access_token'] = make_access_token()
        self.client.cookies['refresh_token'] = 'refresh-cookie'
        mocked_requests.return_value = make_response(500, {'detail': 'Server error'})

        response = self.client.get(reverse('donor_browse_businesses'))

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, 'Our threads are a bit tangled at the moment.', status_code=503)
        self.assertNotIn('access_token', response.cookies)
        self.assertNotIn('refresh_token', response.cookies)

    @patch('frontend.services.api_service.requests.request')
    def test_login_page_refresh_redirects_with_cookies(self, mocked_requests):
        """
        Edge Case: User is on /login with an expired token. 
        Middleware refreshes token, sees user is logged in, and redirects to dashboard.
        New cookies MUST be present on the redirect response.
        """
        self.client.cookies['access_token'] = 'expired'
        self.client.cookies['refresh_token'] = 'refresh-cookie'
        
        responses = [
            make_response(401), # Middleware: /users/me
            make_response(200), # api_call: /token/refresh
            make_response(200, { # api_call: retry /users/me
                'user_id': 1, 'role': 'Donor', 'email': 'u@e.com', 'status': 'ACTIVE'
            })
        ]
        responses[1].cookies.set('access_token', 'new-access')
        responses[1].cookies.set('refresh_token', 'new-refresh')
        mocked_requests.side_effect = responses
        
        response = self.client.get(reverse('login'))
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('donor_browse_businesses'))
        
        self.assertEqual(response.cookies['access_token'].value, 'new-access')
        self.assertEqual(response.cookies['refresh_token'].value, 'new-refresh')


class AdminEditDonorViewTest(MiddlewareAuthMixin, TestCase):

    @patch('frontend.services.api_service.requests.request')
    def test_profile_caching_includes_all_fields(self, mocked_requests):
        """
        Verify that the entire backend payload is stored in the session cache.
        """
        self.client.cookies['access_token'] = 'valid'
        
        full_payload = {
            'user_id': 1,
            'role': 'Donor',
            'email': 'u@e.com',
            'first_name': 'Test',
            'last_name': 'User',
            'status': 'ACTIVE',
            'large_bio': 'A' * 100,
            'other_junk': 'B' * 50,
        }
        mocked_requests.return_value = make_response(200, full_payload)
        
        self.client.get(reverse('donor_browse_businesses'))
        
        session = self.client.session
        cached_profile = session.get('user_profile')
        
        self.assertIsNotNone(cached_profile)
        self.assertEqual(cached_profile['large_bio'], 'A' * 100)
        self.assertEqual(cached_profile['other_junk'], 'B' * 50)
    def setUp(self):
        super().setUp()
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}
        self.donor_payload = {
            'user_id': 7,
            'first_name': 'Juan',
            'middle_name': 'Santos',
            'last_name': 'Dela Cruz',
            'email': 'juan@example.com',
            'contact_no': '+639171234567',
            'display_address': 'Manila',
            'latitude': '14.5995120',
            'longitude': '120.9842220',
            'is_2fa_enabled': True,
            'status': 'ACTIVE',
            'upload': None,
        }

    @patch('frontend.views.admin.api_call')
    def test_edit_page_hides_status_input(self, mocked_api_call):
        mocked_api_call.return_value = make_response(
            200,
            self.donor_payload,
            {'ETag': '"etag-1"'}
        )

        response = self.client.get(reverse('admin_edit_donor', kwargs={'user_id': 7}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="contact_no"')
        self.assertNotContains(response, 'name="status"')
        self.assertContains(response, 'name="current_etag"')

    @patch('frontend.views.admin.api_call')
    def test_staged_2fa_disable_runs_after_successful_patch(self, mocked_api_call):
        mocked_api_call.side_effect = [
            make_response(200, self.donor_payload, {'ETag': '"etag-1"'}),
            make_response(200, {'message': 'updated'}, {'ETag': '"etag-2"'}),
            make_response(200, {'message': '2fa disabled'}),
        ]

        response = self.client.post(
            reverse('admin_edit_donor', kwargs={'user_id': 7}),
            {
                'current_etag': '"etag-1"',
                'first_name': 'Updated',
                'middle_name': 'Santos',
                'last_name': 'Dela Cruz',
                'contact_no': '09171234567',
                'display_address': 'Manila',
                'latitude': '14.5995120',
                'longitude': '120.9842220',
                'disable_2fa': '1',
                'password': '',
                'confirm_password': '',
            }
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_view_donors'))
        self.assertEqual(mocked_api_call.call_count, 3)

        get_call, patch_call, delete_call = mocked_api_call.call_args_list
        self.assertEqual(get_call.args[1:], ('GET', 'users/7'))
        self.assertEqual(patch_call.args[1:], ('PATCH', 'users/7'))
        self.assertEqual(delete_call.args[1:], ('DELETE', 'users/7/2fa'))
        self.assertEqual(patch_call.kwargs['headers']['If-Match'], '"etag-1"')
        self.assertEqual(patch_call.kwargs['data']['contact_no'], '+639171234567')

    @patch('frontend.views.admin.api_call')
    def test_failed_patch_does_not_call_2fa_disable(self, mocked_api_call):
        mocked_api_call.side_effect = [
            make_response(200, self.donor_payload, {'ETag': '"etag-1"'}),
            make_response(400, {'first_name': ['This field is required.']}),
        ]

        response = self.client.post(
            reverse('admin_edit_donor', kwargs={'user_id': 7}),
            {
                'current_etag': '"etag-1"',
                'first_name': '',
                'middle_name': 'Santos',
                'last_name': 'Dela Cruz',
                'contact_no': '09171234567',
                'display_address': 'Manila',
                'latitude': '14.5995120',
                'longitude': '120.9842220',
                'disable_2fa': '1',
                'password': '',
                'confirm_password': '',
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_api_call.call_count, 2)

    @patch('frontend.views.admin.api_call')
    def test_conflict_patch_shows_backend_detail_message(self, mocked_api_call):
        mocked_api_call.side_effect = [
            make_response(200, self.donor_payload, {'ETag': '"etag-1"'}),
            make_response(409, {'detail': 'Only active users can be edited.'}),
        ]

        response = self.client.post(
            reverse('admin_edit_donor', kwargs={'user_id': 7}),
            {
                'current_etag': '"etag-1"',
                'first_name': 'Updated',
                'middle_name': 'Santos',
                'last_name': 'Dela Cruz',
                'contact_no': '09171234567',
                'display_address': 'Manila',
                'latitude': '14.5995120',
                'longitude': '120.9842220',
                'password': '',
                'confirm_password': '',
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only active users can be edited.')

    @patch('frontend.views.admin.api_call')
    def test_archived_donor_edit_page_redirects_to_list(self, mocked_api_call):
        archived_payload = dict(self.donor_payload, status='ARCHIVED')
        mocked_api_call.return_value = make_response(
            200,
            archived_payload,
            {'ETag': '"etag-1"'}
        )

        response = self.client.get(reverse('admin_edit_donor', kwargs={'user_id': 7}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_view_donors'))


class AdminViewTuabsTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.get_paginated_data')
    def test_admin_view_tuabs_renders_expected_columns_and_rows(self, mocked_page_data):
        mocked_page_data.return_value = {
            'results': [{
                'user_id': 11,
                'business_name': 'Weave Lab',
                'contact_no': '+639171234567',
                'is_subscribed': True,
                'status': 'ACTIVE',
                'etag': 'W/"etag-11"',
            }],
            'count': 1,
            'total_pages': 1,
            'current_page': 1,
            'has_next': False,
            'has_prev': False,
            'search_query': 'weave@example.com',
        }

        response = self.client.get(reverse('admin_view_tuabs'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Business Name')
        self.assertContains(response, 'Contact No')
        self.assertContains(response, 'Subscription Tier')
        self.assertContains(response, 'Weave Lab')
        self.assertContains(response, 'Pro')
        self.assertContains(response, 'Search TUABs...')
        self.assertNotContains(response, 'function authFetch')
        self.assertContains(response, 'data-api-url="/admin/users/11/archive/"')
        self.assertContains(response, 'data-user-etag="W/&quot;etag-11&quot;"')
        self.assertContains(response, 'name="etag"')
        self.assertContains(response, 'href="/admin/tuabs/11/"')
        self.assertContains(response, 'href="/admin/tuabs/add/"')
        self.assertContains(response, 'Add TUAB')


class AdminViewDonorsTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.get_paginated_data')
    def test_admin_view_donors_renders_archive_etag_data(self, mocked_page_data):
        mocked_page_data.return_value = {
            'results': [{
                'user_id': 7,
                'first_name': 'Juan',
                'last_name': 'Dela Cruz',
                'contact_no': '+639171234567',
                'status': 'ACTIVE',
                'etag': 'W/"etag-7"',
            }],
            'count': 1,
            'total_pages': 1,
            'current_page': 1,
            'has_next': False,
            'has_prev': False,
            'search_query': '',
        }

        response = self.client.get(reverse('admin_view_donors'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-api-url="/admin/users/7/archive/"')
        self.assertContains(response, 'data-user-etag="W/&quot;etag-7&quot;"')
        self.assertContains(response, 'name="etag"')


class AdminAddTuabViewTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.get_paginated_data')
    def test_pending_tuab_queue_renders_documentation_and_approve_actions(self, mocked_page_data):
        mocked_page_data.return_value = {
            'results': [{
                'user_id': 11,
                'business_name': 'Weave Lab',
                'email': 'weave@example.com',
                'contact_no': '+639171234567',
                'display_address': 'V. Luna Road',
                'barangay': 'Pinyahan',
                'city': 'Quezon City',
                'description': 'Community textile upcycling studio.',
                'social_link': 'https://example.com/weavelab',
                'target_fibers': 'denim,cotton',
                'max_distance_km': '10.00',
                'min_biodeg_score': '65.00',
                'documentation': 'http://127.0.0.1:8000/media/documentation/proof.pdf',
                'status': 'UNDER_REVIEW',
            }],
            'count': 1,
            'total_pages': 1,
            'current_page': 1,
            'has_next': False,
            'has_prev': False,
            'search_query': '',
        }

        response = self.client.get(reverse('admin_add_tuab'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_page_data.call_args.args[1], 'users')
        self.assertEqual(mocked_page_data.call_args.kwargs['params'], {'role': 'TUAB', 'status': 'UNDER_REVIEW'})
        self.assertContains(response, 'Pending TUAB Applications')
        self.assertContains(response, 'Weave Lab')
        self.assertContains(response, 'View Documentation')
        self.assertContains(response, 'action="/admin/tuabs/add/"')
        self.assertContains(response, 'name="user_id" value="11"')
        self.assertNotContains(response, 'All TUABs')
        self.assertNotContains(response, 'Under Review')
        self.assertNotContains(response, 'Open Detail')

    @patch('frontend.views.admin.get_paginated_data')
    def test_pending_tuab_queue_shows_empty_state(self, mocked_page_data):
        mocked_page_data.return_value = {
            'results': [],
            'count': 0,
            'total_pages': 1,
            'current_page': 1,
            'has_next': False,
            'has_prev': False,
            'search_query': '',
        }

        response = self.client.get(reverse('admin_add_tuab'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No TUAB applications are waiting for approval.')



class AdminViewTuabDetailTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}
        self.tuab_payload = {
            'user_id': 11,
            'role': 'TUAB',
            'business_name': 'Weave Lab',
            'email': 'weave@example.com',
            'description': 'Community textile upcycling studio.',
            'social_link': 'https://example.com/weavelab',
            'contact_no': '+639171234567',
            'barangay': 'Pinyahan',
            'city': 'Quezon City',
            'display_address': 'V. Luna Road',
            'latitude': '14.6500000',
            'longitude': '121.0500000',
            'status': 'ACTIVE',
            'operational_status': 'HIBERNATING',
            'is_subscribed': True,
            'max_active_claims': 5,
            'target_fibers': 'denim, cotton',
            'min_biodeg_score': '65.00',
            'max_distance_km': '10.00',
            'is_2fa_enabled': True,
            'upload': 'http://127.0.0.1:8000/media/profile.jpg',
            'created_at': '2026-05-01T08:30:00Z',
            'updated_at': '2026-05-02T09:45:00Z',
        }

    @patch('frontend.views.admin.api_call')
    def test_admin_view_tuab_renders_enriched_detail_fields(self, mocked_api_call):
        mocked_api_call.return_value = make_response(200, self.tuab_payload)

        response = self.client.get(reverse('admin_view_tuab', kwargs={'user_id': 11}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Weave Lab')
        self.assertContains(response, 'Hibernating')
        self.assertContains(response, 'denim')
        self.assertContains(response, 'cotton')
        self.assertContains(response, '10.00')
        self.assertContains(response, 'Pro')
        self.assertContains(response, 'Community textile upcycling studio.')
        self.assertContains(response, 'https://example.com/weavelab')

    @patch('frontend.views.admin.api_call')
    def test_admin_view_tuab_renders_fallbacks_for_optional_fields(self, mocked_api_call):
        payload = dict(self.tuab_payload)
        payload.update({
            'description': None,
            'social_link': '',
            'target_fibers': '',
            'latitude': None,
            'longitude': None,
            'barangay': None,
            'city': None,
            'display_address': None,
            'is_subscribed': False,
        })
        mocked_api_call.return_value = make_response(200, payload)

        response = self.client.get(reverse('admin_view_tuab', kwargs={'user_id': 11}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No business description provided.')
        self.assertContains(response, 'No social link provided.')
        self.assertContains(response, 'No target fibers set.')
        self.assertContains(response, 'Free')

    @patch('frontend.views.admin.api_call')
    def test_admin_view_tuab_redirects_to_list_when_backend_record_missing(self, mocked_api_call):
        mocked_api_call.return_value = make_response(404, {'detail': 'Not found.'})

        response = self.client.get(reverse('admin_view_tuab', kwargs={'user_id': 11}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_view_tuabs'))

class AdminArchiveProxyTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.api_call')
    def test_admin_archive_proxy_calls_backend_delete(self, mocked_api_call):
        mocked_api_call.return_value = make_response(204)
        
        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': '"etag-1"'})
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(mocked_api_call.call_args.args[1:], ('DELETE', 'users/11'))
        self.assertEqual(mocked_api_call.call_args.kwargs['headers']['If-Match'], '"etag-1"')

    @patch('frontend.views.admin.api_call')
    def test_admin_archive_proxy_sets_success_message(self, mocked_api_call):
        mocked_api_call.return_value = make_response(204)

        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': '"etag-1"'})

        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("User archived successfully.", messages)

    @patch('frontend.views.admin.api_call')
    def test_admin_archive_proxy_handles_stale_etag(self, mocked_api_call):
        mocked_api_call.return_value = make_response(412, {'detail': 'ETag does not match the current resource version.'})

        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': '"etag-1"'})

        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("This user was updated somewhere else. Refresh the page and try archiving again.", messages)

    @patch('frontend.views.admin.api_call')
    def test_admin_archive_proxy_handles_missing_etag(self, mocked_api_call):
        mocked_api_call.return_value = make_response(428, {'detail': 'If-Match header is required.'})

        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': ''})

        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("We couldn't verify the latest user version. Refresh the page and try again.", messages)

    def test_admin_archive_proxy_denies_non_admin(self):
        self.auth_profile = {'role': 'Donor'}
        
        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}))
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('donor_browse_businesses'))


class AdminApproveTuabPostTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.api_call')
    def test_admin_add_tuab_post_calls_backend_approve(self, mocked_api_call):
        mocked_api_call.return_value = make_response(200, {'status': 'ACTIVE'})

        response = self.client.post(reverse('admin_add_tuab'), {'user_id': 11})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_add_tuab'))
        self.assertEqual(mocked_api_call.call_args.args[1:], ('POST', 'users/11/approve'))

    @patch('frontend.views.admin.api_call')
    def test_admin_add_tuab_post_handles_backend_error(self, mocked_api_call):
        mocked_api_call.return_value = make_response(409, {'detail': 'Only TUAB users under review can be approved.'})

        response = self.client.post(reverse('admin_add_tuab'), {'user_id': 11})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_add_tuab'))

    def test_admin_add_tuab_post_denies_non_admin(self):
        self.auth_profile = {'role': 'Donor'}

        response = self.client.post(reverse('admin_add_tuab'), {'user_id': 11})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('donor_browse_businesses'))


class TuabDashboardViewTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.auth_profile = {
            'user_id': 21,
            'role': 'TUAB',
            'first_name': 'Mina',
            'last_name': 'Lopez',
            'business_name': 'Weave Lab',
        }

    @patch('frontend.views.tuab.api_call')
    def test_dashboard_uses_preferred_pickup_date_in_table(self, mocked_api_call):
        mocked_api_call.side_effect = [
            make_response(200, {
                'results': [{
                    'donation_id': 88,
                    'donor': {'first_name': 'Juan', 'last_name': 'Dela Cruz'},
                    'pickup_display_address': '123 Main St, Makati',
                    'preferred_pickup_date': '2026-05-10T00:00:00Z',
                    'submitted_at': '2026-05-01T08:30:00Z',
                    'pickup_latitude': '14.5547000',
                    'pickup_longitude': '121.0244000',
                    'items': [{'item_id': 1}],
                }],
                'next': None,
                'count': 1,
            }),
            make_response(200, {
                'results': [],
                'next': None,
                'count': 0,
            }),
        ]

        response = self.client.get(reverse('tuab_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'May-10-2026')
        self.assertNotContains(response, 'May-01-2026')
        self.assertContains(response, 'const DONATIONS = {"available": [{"id": 88')


class AdminEditTuabViewTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tuab_payload = {
            'user_id': 11,
            'role': 'TUAB',
            'business_name': 'Weave Lab',
            'email': 'weave@example.com',
            'description': 'Community textile upcycling studio.',
            'social_link': 'https://example.com/weavelab',
            'contact_no': '+639171234567',
            'barangay': 'Pinyahan',
            'city': 'Quezon City',
            'display_address': 'V. Luna Road',
            'latitude': '14.6500000',
            'longitude': '121.0500000',
            'status': 'ACTIVE',
            'operational_status': 'ACTIVE',
            'is_subscribed': True,
            'max_active_claims': 5,
            'target_fibers': 'denim,cotton',
            'min_biodeg_score': '65.00',
            'max_distance_km': '10.00',
            'is_2fa_enabled': True,
            'upload': 'http://127.0.0.1:8000/media/profile.jpg',
        }

    @patch('frontend.views.admin.get_fiber_choices')
    @patch('frontend.views.admin.api_call')
    def test_conflict_patch_shows_backend_detail_message(self, mocked_api_call, mocked_fibers):
        mocked_fibers.return_value = ['cotton', 'denim']
        mocked_api_call.side_effect = [
            make_response(409, {'detail': 'Only active users can be edited.'}),
            make_response(200, self.tuab_payload, {'ETag': '"etag-2"'}),
        ]

        response = self.client.post(
            reverse('admin_edit_tuab', kwargs={'user_id': 11}),
            {
                'current_etag': '"etag-1"',
                'business_name': 'Weave Lab',
                'description': 'Updated description',
                'contact_no': '09171234567',
                'display_address': 'V. Luna Road',
                'latitude': '14.6500000',
                'longitude': '121.0500000',
                'target_fibers': 'denim,cotton',
                'max_distance_km': '10.00',
                'min_biodeg_score': '65.00',
                'social_link': 'https://example.com/weavelab',
                'password': '',
                'confirm_password': '',
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only active users can be edited.')


class DonorEditProfileViewTest(MiddlewareAuthMixin, TestCase):
    auth_profile = {
        'user_id': 7,
        'role': 'Donor',
        'first_name': 'Juan',
        'last_name': 'Dela Cruz',
    }

    @patch('frontend.views.donor.api_call')
    def test_conflict_patch_returns_detail_payload(self, mocked_api_call):
        mocked_api_call.return_value = make_response(409, {'detail': 'Only active users can be edited.'})

        response = self.client.post(
            reverse('edit_profile'),
            {
                'user_id': '7',
                'current_etag': '"etag-1"',
                'first_name': 'Juan',
                'middle_name': 'Santos',
                'last_name': 'Dela Cruz',
                'contact_no': '09171234567',
                'display_address': 'Manila',
                'latitude': '14.5995120',
                'longitude': '120.9842220',
                'new_password': '',
                'confirm_password': '',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail'], 'Only active users can be edited.')


class TuabDonationDetailViewTest(MiddlewareAuthMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.auth_profile = {
            'user_id': 21,
            'role': 'TUAB',
            'first_name': 'Mina',
            'last_name': 'Lopez',
            'business_name': 'Weave Lab',
            'display_address': '123 TUAB Street, Quezon City',
            'latitude': '14.6500000',
            'longitude': '121.0500000',
        }
        self.donation_payload = {
            'donation_id': 88,
            'status': 'PENDING',
            'donor': {
                'user_id': 9,
                'first_name': 'Juan',
                'last_name': 'Dela Cruz',
                'contact_no': '+639171234567',
                'upload': 'http://127.0.0.1:8000/media/donor.jpg',
            },
            'claimed_by_tuab': None,
            'pickup_display_address': '123 Main St, Makati',
            'pickup_latitude': '14.554700000000000',
            'pickup_longitude': '121.024400000000000',
            'preferred_pickup_date': '2026-05-10T00:00:00Z',
            'preferred_pickup_window_start': '09:00:00',
            'preferred_pickup_window_end': '12:00:00',
            'submitted_at': '2026-05-01T08:30:00Z',
            'updated_at': '2026-05-01T08:30:00Z',
            'upload': 'http://127.0.0.1:8000/media/donation.jpg',
            'items': [
                {
                    'item_id': 1,
                    'condition_rating': 'GOOD',
                    'weight_kg': '1.500',
                    'lookup_details': {
                        'clothing_type': 'Shirt',
                        'brand': 'Brand A',
                        'fiber_json': '{"cotton": 100}',
                        'category': 'tops',
                    },
                }
            ],
        }

    @patch('frontend.views.tuab.api_call')
    def test_tuab_view_donation_renders_real_donation_payload(self, mocked_api_call):
        mocked_api_call.return_value = make_response(200, self.donation_payload, {'ETag': '"etag-88"'})

        response = self.client.get(reverse('tuab_view_donation', kwargs={'donation_id': 88}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="88"')
        self.assertContains(response, 'Juan Dela Cruz')
        self.assertContains(response, '123 Main St, Makati')
        self.assertContains(response, 'Shirt')
        self.assertContains(response, 'submitPickupClaim()')
        self.assertContains(response, 'submitDeliveryClaim()')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'Delivery Location')
        self.assertContains(response, 'Scheduled Time')

    @patch('frontend.views.tuab.api_call')
    def test_tuab_view_donation_proxies_quotation_request(self, mocked_api_call):
        mocked_api_call.return_value = make_response(200, {
            'total_price': 375.5,
            'quotationId': 'Q-123',
            'stopId_1': 'S1',
            'stopId_2': 'S2',
            'schedule_at': '2026-05-10 09:00:00',
            'expires_at': 2000000000,
            'quotation_token': 'token.sig',
        })

        response = self.client.post(
            reverse('tuab_quotation_proxy', kwargs={'donation_id': 88}),
            data=json.dumps({
                'current_etag': '"etag-88"',
                'dropoff_address': '123 TUAB Street, Quezon City',
                'dropoff_lat': '14.6500000',
                'dropoff_lng': '121.0500000',
                'scheduled_time': '10:30',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['quotationId'], 'Q-123')
        self.assertEqual(mocked_api_call.call_args.args[1:], ('POST', 'donations/88/quotation'))
        self.assertEqual(mocked_api_call.call_args.kwargs['headers']['If-Match'], '"etag-88"')
        self.assertEqual(mocked_api_call.call_args.kwargs['json']['dropoff_lat'], '14.6500000')
        self.assertEqual(mocked_api_call.call_args.kwargs['json']['scheduled_time'], '10:30')
        self.assertNotIn('schedule_at', mocked_api_call.call_args.kwargs['json'])

    @patch('frontend.views.tuab.api_call')
    def test_tuab_view_donation_proxies_pickup_claim(self, mocked_api_call):
        mocked_api_call.return_value = make_response(200, {'detail': 'Donation successfully claimed for pickup.'})

        response = self.client.post(
            reverse('tuab_view_donation', kwargs={'donation_id': 88}),
            data={
                'current_etag': '"etag-88"',
                'delivery_method': 'PICKUP',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('tuab_dashboard'))
        self.assertEqual(mocked_api_call.call_args.args[1:], ('POST', 'donations/88/claim'))
        self.assertEqual(mocked_api_call.call_args.kwargs['json']['delivery_method'], 'PICKUP')

    @patch('frontend.views.tuab.api_call')
    def test_tuab_view_donation_proxies_delivery_claim_with_token(self, mocked_api_call):
        mocked_api_call.return_value = make_response(200, {'detail': 'Donation successfully claimed and delivery scheduled.'})

        response = self.client.post(
            reverse('tuab_view_donation', kwargs={'donation_id': 88}),
            data={
                'current_etag': '"etag-88"',
                'delivery_method': 'DELIVERY',
                'quotation_token': 'token.sig',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('tuab_dashboard'))
        self.assertEqual(mocked_api_call.call_args.args[1:], ('POST', 'donations/88/claim'))
        self.assertEqual(mocked_api_call.call_args.kwargs['json']['quotation_token'], 'token.sig')

    @patch('frontend.views.tuab.api_call')
    def test_tuab_view_donation_surfaces_stale_etag(self, mocked_api_call):
        mocked_api_call.return_value = make_response(412, {'detail': 'ETag does not match the current resource version.'})

        response = self.client.post(
            reverse('tuab_quotation_proxy', kwargs={'donation_id': 88}),
            data=json.dumps({
                'current_etag': '"etag-old"',
                'dropoff_address': '123 TUAB Street, Quezon City',
                'dropoff_lat': '14.6500000',
                'dropoff_lng': '121.0500000',
                'scheduled_time': '10:30',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()['detail'], 'ETag does not match the current resource version.')

    @patch('frontend.views.tuab.api_call')
    def test_tuab_quotation_proxy_rejects_non_tuab(self, mocked_api_call):
        self.auth_profile = {'role': 'Donor', 'first_name': 'Dana'}

        response = self.client.post(
            reverse('tuab_quotation_proxy', kwargs={'donation_id': 88}),
            data=json.dumps({
                'current_etag': '"etag-88"',
                'dropoff_address': '123 TUAB Street, Quezon City',
                'dropoff_lat': '14.6500000',
                'dropoff_lng': '121.0500000',
                'scheduled_time': '10:30',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], 'Only authenticated TUABs can use this endpoint.')
        mocked_api_call.assert_not_called()
