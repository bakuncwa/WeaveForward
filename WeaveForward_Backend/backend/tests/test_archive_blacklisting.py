from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from ..services.user_archive_service import archive_user
from ..models import ApiToken

User = get_user_model()

class ArchiveBlacklistingTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test_archived@example.com',
            password='password123',
            contact_no='+639123456789',
            first_name='Test',
            last_name='User',
            role='Donor',
            status='ACTIVE'
        )
        self.login_url = reverse('token_obtain_pair')

    def test_archive_blacklists_tokens(self):
        """
        Test that archiving a user blacklists all their outstanding tokens and deletes custom API tokens.
        """
        # 1. Log in to create an outstanding token
        response = self.client.post(self.login_url, {
            'email': 'test_archived@example.com',
            'password': 'password123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify outstanding token exists
        self.assertTrue(OutstandingToken.objects.filter(user=self.user).exists())
        
        # 2. Create a custom API token
        ApiToken.objects.create(user=self.user, token='some-secret-token')
        self.assertTrue(ApiToken.objects.filter(user=self.user).exists())

        # 3. Archive the user
        result = archive_user(target_user_id=self.user.user_id)
        self.assertEqual(result['status_code'], 204)
        
        # 4. Verify SimpleJWT tokens are blacklisted
        outstanding_tokens = OutstandingToken.objects.filter(user=self.user)
        for token in outstanding_tokens:
            self.assertTrue(BlacklistedToken.objects.filter(token=token).exists())
            
        # 5. Verify custom API tokens are deleted
        self.assertFalse(ApiToken.objects.filter(user=self.user).exists())

        # 6. Verify refresh fails
        refresh_token = response.cookies['refresh_token'].value
        refresh_url = reverse('token_refresh')
        
        self.client.cookies['refresh_token'] = refresh_token
        self.client.cookies['csrftoken'] = 'test-csrf-token'
        response = self.client.post(refresh_url, HTTP_X_CSRFTOKEN='test-csrf-token')
        
        # It should be 401 because the user is inactive (and the token is blacklisted)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # SimpleJWT returns 'user_inactive' when the user associated with the token is no longer active
        self.assertEqual(response.data['code'], 'user_inactive')

    def test_archived_user_cannot_login(self):
        """
        Test that an archived user cannot log in.
        """
        # Archive the user
        archive_user(target_user_id=self.user.user_id)
        
        # Attempt to login
        response = self.client.post(self.login_url, {
            'email': 'test_archived@example.com',
            'password': 'password123'
        })
        
        # Should fail with the generic "Invalid email or password." message for security/obfuscation
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['detail'], 'Invalid email or password.')
