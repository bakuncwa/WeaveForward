from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from datetime import timedelta
from django.contrib.auth import get_user_model
import time

User = get_user_model()

class TokenExpirationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Create a donor user (ACTIVE by default in serializer.create, but let's be explicit)
        self.user = User.objects.create_user(
            email='test@example.com',
            password='password123',
            contact_no='+639123456789',
            first_name='Test',
            last_name='User',
            role='Donor',
            status='ACTIVE'
        )
        self.login_url = reverse('token_obtain_pair')
        self.protected_url = reverse('user-me')

    def test_access_token_expires(self):
        """
        Test that an access token becomes invalid after its lifetime expires.
        """
        response = self.client.post(self.login_url, {
            'email': 'test@example.com',
            'password': 'password123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access_token_str = response.cookies['access_token'].value

        self.client.cookies['access_token'] = access_token_str
        response = self.client.get(self.protected_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        from rest_framework_simplejwt.tokens import AccessToken
        from django.utils import timezone
        
        token = AccessToken.for_user(self.user)
        past_time = timezone.now() - timedelta(hours=1)
        token.payload['exp'] = int(past_time.timestamp())
        expired_token_str = str(token)

        self.client.cookies['access_token'] = expired_token_str
        response = self.client.get(self.protected_url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['code'], 'token_not_valid')
        # SimpleJWT might return a generic message or a specific one depending on configuration
        self.assertIn('messages', response.data)
        self.assertEqual(response.data['messages'][0]['message'], 'Token is expired')

    def test_invalid_token(self):
        """
        Test that a completely invalid token is rejected.
        """
        self.client.cookies['access_token'] = 'invalid_token_here'
        response = self.client.get(self.protected_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['code'], 'token_not_valid')

    def test_bearer_header_is_not_supported(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid_token_here')
        response = self.client.get(self.protected_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_token(self):
        """
        Test that accessing a protected endpoint without a token is rejected.
        """
        self.client.credentials()  # Clear credentials
        response = self.client.get(self.protected_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
