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
        self.assertEqual(response.url, reverse('donor_dashboard'))
        self.assertEqual(response.cookies['access_token'].value, 'access-cookie')
        self.assertEqual(response.cookies['refresh_token'].value, 'refresh-cookie')

    @patch('frontend.views.api_call')
    def test_logout_calls_backend_without_refresh_body(self, mocked_api_call):
        mocked_api_call.return_value = make_response(205, {'message': 'Successfully logged out'})
        
        # Create a fake JWT that won't trigger the TokenRefreshMiddleware's expiration check
        import base64, json, time
        payload = base64.b64encode(json.dumps({'exp': time.time() + 3600}).encode()).decode().strip('=')
        fake_access_token = f"header.{payload}.signature"
        
        self.client.cookies['access_token'] = fake_access_token
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


class AdminEditDonorViewTest(TestCase):
    def setUp(self):
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
            'upload': None,
        }

    @patch('frontend.views.admin.api_call')
    @patch('frontend.views.admin.get_user_profile')
    def test_edit_page_hides_status_input(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
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
    @patch('frontend.views.admin.get_user_profile')
    def test_staged_2fa_disable_runs_after_successful_patch(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
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
    @patch('frontend.views.admin.get_user_profile')
    def test_failed_patch_does_not_call_2fa_disable(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
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
    @patch('frontend.views.admin.get_user_profile')
    def test_archived_donor_edit_page_redirects_to_list(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        archived_payload = dict(self.donor_payload, status='ARCHIVED')
        mocked_api_call.return_value = make_response(
            200,
            archived_payload,
            {'ETag': '"etag-1"'}
        )

        response = self.client.get(reverse('admin_edit_donor', kwargs={'user_id': 7}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_view_donors'))


class AdminViewTuabsTest(TestCase):
    def setUp(self):
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.get_paginated_data')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_view_tuabs_renders_expected_columns_and_rows(self, mocked_profile, mocked_page_data):
        mocked_profile.return_value = self.profile
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


class AdminViewDonorsTest(TestCase):
    def setUp(self):
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.get_paginated_data')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_view_donors_renders_archive_etag_data(self, mocked_profile, mocked_page_data):
        mocked_profile.return_value = self.profile
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


class AdminAddTuabViewTest(TestCase):
    def setUp(self):
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.get_paginated_data')
    @patch('frontend.views.admin.get_user_profile')
    def test_pending_tuab_queue_renders_documentation_and_approve_actions(self, mocked_profile, mocked_page_data):
        mocked_profile.return_value = self.profile
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
    @patch('frontend.views.admin.get_user_profile')
    def test_pending_tuab_queue_shows_empty_state(self, mocked_profile, mocked_page_data):
        mocked_profile.return_value = self.profile
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



class AdminViewTuabDetailTest(TestCase):
    def setUp(self):
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
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_view_tuab_renders_enriched_detail_fields(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
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
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_view_tuab_renders_fallbacks_for_optional_fields(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
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
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_view_tuab_redirects_to_list_when_backend_record_missing(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        mocked_api_call.return_value = make_response(404, {'detail': 'Not found.'})

        response = self.client.get(reverse('admin_view_tuab', kwargs={'user_id': 11}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_view_tuabs'))

class AdminArchiveProxyTest(TestCase):
    def setUp(self):
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.api_call')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_archive_proxy_calls_backend_delete(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        mocked_api_call.return_value = make_response(204)
        
        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': '"etag-1"'})
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(mocked_api_call.call_args.args[1:], ('DELETE', 'users/11'))
        self.assertEqual(mocked_api_call.call_args.kwargs['headers']['If-Match'], '"etag-1"')

    @patch('frontend.views.admin.api_call')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_archive_proxy_sets_success_message(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        mocked_api_call.return_value = make_response(204)

        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': '"etag-1"'})

        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("User archived successfully.", messages)

    @patch('frontend.views.admin.api_call')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_archive_proxy_handles_stale_etag(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        mocked_api_call.return_value = make_response(412, {'detail': 'ETag does not match the current resource version.'})

        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': '"etag-1"'})

        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("This user was updated somewhere else. Refresh the page and try archiving again.", messages)

    @patch('frontend.views.admin.api_call')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_archive_proxy_handles_missing_etag(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        mocked_api_call.return_value = make_response(428, {'detail': 'If-Match header is required.'})

        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}), {'etag': ''})

        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("We couldn't verify the latest user version. Refresh the page and try again.", messages)

    @patch('frontend.views.admin.get_user_profile')
    def test_admin_archive_proxy_denies_non_admin(self, mocked_profile):
        mocked_profile.return_value = {'role': 'Donor'}
        
        response = self.client.post(reverse('admin_archive_user_proxy', kwargs={'user_id': 11}))
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))


class AdminApproveTuabPostTest(TestCase):
    def setUp(self):
        self.profile = {'role': 'Admin', 'first_name': 'Admin'}

    @patch('frontend.views.admin.api_call')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_add_tuab_post_calls_backend_approve(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        mocked_api_call.return_value = make_response(200, {'status': 'ACTIVE'})

        response = self.client.post(reverse('admin_add_tuab'), {'user_id': 11})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_add_tuab'))
        self.assertEqual(mocked_api_call.call_args.args[1:], ('POST', 'users/11/approve'))

    @patch('frontend.views.admin.api_call')
    @patch('frontend.views.admin.get_user_profile')
    def test_admin_add_tuab_post_handles_backend_error(self, mocked_profile, mocked_api_call):
        mocked_profile.return_value = self.profile
        mocked_api_call.return_value = make_response(400, {'detail': 'Only TUAB users under review can be approved.'})

        response = self.client.post(reverse('admin_add_tuab'), {'user_id': 11})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_add_tuab'))

    @patch('frontend.views.admin.get_user_profile')
    def test_admin_add_tuab_post_denies_non_admin(self, mocked_profile):
        mocked_profile.return_value = {'role': 'Donor'}

        response = self.client.post(reverse('admin_add_tuab'), {'user_id': 11})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))
