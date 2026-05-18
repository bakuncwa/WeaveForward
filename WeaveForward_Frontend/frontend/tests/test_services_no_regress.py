import json
from unittest.mock import Mock, patch
from django.test import TestCase, RequestFactory
from django.shortcuts import render
from django.http import HttpResponse
from django.urls import reverse

from ..services.user_service import get_user_profile
from ..services.brand_fiber_lookup_service import get_fiber_choices
from ..services.form_utils import get_paginated_data
from ..middleware import TokenRefreshMiddleware
from ..constants import ALLOWED_FIBERS
from .test_views import make_response


class ServicesNoRegressTest(TestCase):

    @patch('frontend.services.user_service.api_call')
    async def test_get_user_profile_success(self, mocked_api_call):
        """Verify get_user_profile returns the JSON payload on 200 OK."""
        mocked_profile = {'user_id': 1, 'email': 'donor@test.com', 'role': 'Donor'}
        mocked_api_call.return_value = make_response(200, mocked_profile)
        
        request = Mock()
        profile = await get_user_profile(request)
        self.assertEqual(profile, mocked_profile)

    @patch('frontend.services.user_service.api_call')
    async def test_get_user_profile_non_200_returns_none(self, mocked_api_call):
        """Verify get_user_profile returns None on backend error."""
        mocked_api_call.return_value = make_response(500, {'detail': 'Server Error'})
        
        request = Mock()
        profile = await get_user_profile(request)
        self.assertIsNone(profile)

    @patch('frontend.services.brand_fiber_lookup_service.api_call')
    async def test_get_fiber_choices_success(self, mocked_api_call):
        """Verify get_fiber_choices returns backend list on 200 OK."""
        custom_choices = ['organic_cotton', 'recycled_denim']
        mocked_api_call.return_value = make_response(200, custom_choices)
        
        request = Mock()
        choices = await get_fiber_choices(request)
        self.assertEqual(choices, custom_choices)

    @patch('frontend.services.brand_fiber_lookup_service.api_call')
    async def test_get_fiber_choices_fallback_on_error(self, mocked_api_call):
        """Verify get_fiber_choices returns ALLOWED_FIBERS on backend outage."""
        mocked_api_call.return_value = make_response(500, 'HTML Error Page Content')
        
        request = Mock()
        choices = await get_fiber_choices(request)
        self.assertEqual(choices, ALLOWED_FIBERS)

    @patch('frontend.services.form_utils.api_call')
    async def test_get_paginated_data_success_dict(self, mocked_api_call):
        """Verify get_paginated_data parses standard DRF pagination dictionary."""
        mocked_payload = {
            'results': [{'id': 1, 'name': 'Item'}],
            'count': 1,
            'next': 'http://test.com/?page=2',
            'previous': None
        }
        mocked_api_call.return_value = make_response(200, mocked_payload)
        
        request = Mock()
        request.GET = {'page': '1', 'q': ''}
        data = await get_paginated_data(request, 'some-endpoint')
        
        self.assertEqual(data['results'], mocked_payload['results'])
        self.assertEqual(data['count'], 1)
        self.assertTrue(data['has_next'])
        self.assertFalse(data['has_prev'])

    @patch('frontend.services.form_utils.api_call')
    async def test_get_paginated_data_success_list(self, mocked_api_call):
        """Verify get_paginated_data parses flat JSON lists gracefully."""
        mocked_payload = [{'id': 1, 'name': 'Item'}]
        mocked_api_call.return_value = make_response(200, mocked_payload)
        
        request = Mock()
        request.GET = {'page': '1', 'q': ''}
        data = await get_paginated_data(request, 'some-endpoint')
        
        self.assertEqual(data['results'], mocked_payload)
        self.assertEqual(data['count'], 1)
        self.assertFalse(data['has_next'])

    @patch('frontend.services.form_utils.api_call')
    async def test_get_paginated_data_failure_fallback(self, mocked_api_call):
        """Verify get_paginated_data yields safe default values on backend outage."""
        mocked_api_call.return_value = make_response(500, 'HTML Error Page Content')
        
        request = Mock()
        request.GET = {'page': '1', 'q': ''}
        data = await get_paginated_data(request, 'some-endpoint')
        
        self.assertEqual(data['results'], [])
        self.assertEqual(data['count'], 0)
        self.assertFalse(data['has_next'])
        self.assertFalse(data['has_prev'])


class MiddlewareNoRegressTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        
        async def dummy_get_response(request):
            return HttpResponse("OK")
            
        self.dummy_get_response = dummy_get_response

    @patch('frontend.middleware.api_call')
    async def test_token_refresh_middleware_success(self, mocked_api_call):
        """Verify middleware sets request.user_profile on 200 OK profile response."""
        mocked_profile = {'user_id': 1, 'email': 'donor@test.com', 'role': 'Donor'}
        mocked_api_call.return_value = make_response(200, mocked_profile)

        middleware = TokenRefreshMiddleware(self.dummy_get_response)
        
        request = self.factory.get('/donor/profile/')
        request.COOKIES = {'access_token': 'valid', 'refresh_token': 'valid'}
        
        # Mock session store cleanly
        from django.contrib.sessions.middleware import SessionMiddleware
        session_middleware = SessionMiddleware(self.dummy_get_response)
        session_middleware.process_request(request)
        
        await middleware(request)
        
        self.assertEqual(request.user_profile, mocked_profile)
        self.assertEqual(request.session['user_profile'], mocked_profile)

    @patch('frontend.middleware.api_call')
    async def test_token_refresh_middleware_401_redirects(self, mocked_api_call):
        """Verify middleware redirects unauthenticated requests on protected path."""
        mocked_api_call.return_value = make_response(401, {'detail': 'Unauthorized'})

        middleware = TokenRefreshMiddleware(self.dummy_get_response)
        
        request = self.factory.get('/donor/profile/')
        request.COOKIES = {'access_token': 'expired', 'refresh_token': 'expired'}
        
        # Mock session store cleanly
        from django.contrib.sessions.middleware import SessionMiddleware
        session_middleware = SessionMiddleware(self.dummy_get_response)
        session_middleware.process_request(request)
        
        response = await middleware(request)
        
        self.assertEqual(response.status_code, 302)
        expected_url = reverse('login')
        self.assertTrue(response.url == expected_url or response['Location'] == expected_url)



