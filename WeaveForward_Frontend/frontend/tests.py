from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse


def make_response(status_code, payload=None, headers=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.headers = headers or {}
    return response


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
        self.assertEqual(response.url, '/admin/donors/7/edit/?saved=1')
        self.assertEqual(mocked_api_call.call_count, 3)

        get_call, patch_call, delete_call = mocked_api_call.call_args_list
        self.assertEqual(get_call.args[1:], ('GET', 'users/7/'))
        self.assertEqual(patch_call.args[1:], ('PATCH', 'users/7/'))
        self.assertEqual(delete_call.args[1:], ('DELETE', 'users/7/2fa/'))
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
