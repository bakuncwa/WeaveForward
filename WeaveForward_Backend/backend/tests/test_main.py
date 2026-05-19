import zoneinfo
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from decimal import Decimal
import json
from unittest.mock import Mock, patch
import pyotp
import requests
from django.test import TestCase, override_settings
from django.conf import settings
from django.contrib.auth.hashers import BCryptPasswordHasher

class FastBCryptPasswordHasher(BCryptPasswordHasher):
    rounds = 4

settings.PASSWORD_HASHERS = [
    'backend.tests.test_main.FastBCryptPasswordHasher',
] + list(settings.PASSWORD_HASHERS)
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import resolve, reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from backend.models import User, Upload, Donation, DonationItem, BrandFiberLookup, MatchPrediction, Subscription, SubscriptionPayment, InventoryLedger, UserOperationalStatus, AuditTrail, SubscriptionStatus, SubscriptionTier
from backend.serializers import DonorRegisterSerializer, TUABRegisterSerializer
from backend.services.audit_service import log_audit
from backend.services.claim_donation_service import sign_quotation_data
from backend.services.etag_service import build_updated_at_etag
from backend.services.prediction_service import run_predictions_for_donation
from backend.services.user_archive_service import archive_user
from backend.services.unclaim_donation_service import unclaim_tuab_donations
from backend.views.webhooks import webhooks as webhooks_view

class UserModelTest(TestCase):
    def setUp(self):
        self.user_data = {
            "email": "test@example.com",
            "password": "Password123",
            "role": "Donor",
            "contact_no": "+639150000001",
            "first_name": "Test",
            "last_name": "User"
        }

    def test_contact_no_uniqueness(self):
        User.objects.create_user(**self.user_data)
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                email="test2@example.com",
                password="Password123",
                role="Donor",
                contact_no="+639150000001"
            )

    def test_min_biodeg_score_range(self):
        # Above 100
        u = User(**self.user_data, min_biodeg_score=101.0)
        with self.assertRaises(ValidationError):
            u.full_clean()
        
        # Below 0
        u = User(**self.user_data, min_biodeg_score=-1.0)
        with self.assertRaises(ValidationError):
            u.full_clean()

    def test_max_distance_km_range(self):
        # Above 1000
        u = User(**self.user_data, max_distance_km=1001.0)
        with self.assertRaises(ValidationError):
            u.full_clean()
        
        # Below 0
        u = User(**self.user_data, max_distance_km=-1.0)
        with self.assertRaises(ValidationError):
            u.full_clean()

    def test_max_active_claims_range(self):
        # Above 255
        u = User(**self.user_data, max_active_claims=256)
        with self.assertRaises(ValidationError):
            u.full_clean()
        
        # Below 1
        u = User(**self.user_data, max_active_claims=0)
        with self.assertRaises(ValidationError):
            u.full_clean()

    def test_first_name_max_length(self):
        data = self.user_data.copy()
        data['first_name'] = "A" * 51
        u = User(**data)
        with self.assertRaises(ValidationError):
            u.full_clean()

    def test_maya_card_id_allows_realistic_maya_card_identifier_length(self):
        data = self.user_data.copy()
        data['maya_card_id'] = "B8dL3edy2qqULa5DSPWuzCSveroBICndc2Ols1cty5mU733RIRY2Pj0maXQSfYyvFNBlvfDZ6uadfDbNUqzFRs7TTYRaZnlfbIxJuNLe5GlTbpknC05ZNcLuAjf34UwKxvAmQENtx5HgmtitjmWM06eI0wm79XcZYVKD2dc"
        u = User(**data)
        u._meta.get_field('maya_card_id').clean(u.maya_card_id, u)

class DonorRegistrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.valid_payload = {
            'role': 'Donor',
            'first_name': 'Juan',
            'last_name': 'Dela Cruz',
            'email': 'juan@example.com',
            'contact_no': '+639171234567',
            'password': 'Password123',
            'latitude': '14.5995120',
            'longitude': '120.9842220',
            'display_address': 'Manila'
        }

    def test_valid_donor_registration(self):
        response = self.client.post(reverse('register'), self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='juan@example.com').exists())

    def test_invalid_phone_format(self):
        payload = self.valid_payload.copy()
        payload['contact_no'] = '09171234567'
        response = self.client.post(reverse('register'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_outside_ncr_geofence(self):
        payload = self.valid_payload.copy()
        payload['latitude'] = '14.0000000'
        payload['longitude'] = '121.0000000'
        response = self.client.post(reverse('register'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('location', response.json())

    def test_missing_required_fields(self):
        payload = {'role': 'Donor'}
        response = self.client.post(reverse('register'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('email', data)
        self.assertIn('contact_no', data)
        self.assertIn('password', data)

class TUABRegistrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Add fibers to database so validation passes
        BrandFiberLookup.objects.create(
            category="Test",
            brand="Test",
            clothing_type="Test",
            fiber_json=json.dumps({"cotton": 100, "wool": 0}),
            is_active=True
        )
        self.valid_payload = {
            'role': 'TUAB',
            'business_name': 'Recycle Co',
            'email': 'tuab@example.com',
            'contact_no': '+639181234567',
            'password': 'Password123',
            'latitude': '14.5995120',
            'longitude': '120.9842220',
            'display_address': 'Manila',
            'target_fibers': 'cotton,wool',
            'max_distance_km': '50.00',
            'min_biodeg_score': '70.00',
            'description': 'Valid description of Recycle Co'
        }

    def test_valid_tuab_registration(self):
        payload = self.valid_payload.copy()
        payload['documentation'] = SimpleUploadedFile("test.pdf", b"file_content", content_type="application/pdf")
        response = self.client.post(reverse('register'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='tuab@example.com')
        self.assertEqual(user.role, 'TUAB')
        self.assertEqual(user.status, 'UNDER_REVIEW')
        self.assertEqual(user.operational_status, UserOperationalStatus.ACTIVE)

    def test_missing_tuab_required_fields(self):
        payload = self.valid_payload.copy()
        payload.pop('target_fibers')
        # documentation is already missing from valid_payload in setUp
        response = self.client.post(reverse('register'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('target_fibers', data)
        self.assertIn('documentation', data)

    def test_invalid_fibers(self):
        payload = self.valid_payload.copy()
        payload['target_fibers'] = 'cotton,adamantium'
        payload['documentation'] = SimpleUploadedFile("test.pdf", b"file_content", content_type="application/pdf")
        response = self.client.post(reverse('register'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('target_fibers', response.json())

    def test_fiber_formatting(self):
        payload = self.valid_payload.copy()
        payload['target_fibers'] = 'Cotton, wool'
        payload['documentation'] = SimpleUploadedFile("test.pdf", b"file_content", content_type="application/pdf")
        response = self.client.post(reverse('register'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('target_fibers', response.json())

    def test_duplicate_email(self):
        payload = self.valid_payload.copy()
        payload['documentation'] = SimpleUploadedFile("test.pdf", b"file_content", content_type="application/pdf")
        self.client.post(reverse('register'), payload, format='multipart')
        
        payload2 = self.valid_payload.copy()
        payload2['contact_no'] = '+639189999999'
        payload2['documentation'] = SimpleUploadedFile("test.pdf", b"file_content", content_type="application/pdf")
        response = self.client.post(reverse('register'), payload2, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.json())

class LocationLookupTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_valid_location_lookup(self):
        response = self.client.get(reverse('location_lookup'), {'lat': 14.5895, 'lng': 120.9815})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('barangay', data)
        self.assertIn('city', data)

    def test_invalid_location_lookup(self):
        response = self.client.get(reverse('location_lookup'), {'lat': 0, 'lng': 0})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class RoutingStyleTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_named_routes_resolve_without_trailing_slashes(self):
        self.assertEqual(reverse('token_obtain_pair'), '/api/login')
        self.assertEqual(reverse('token_blacklist'), '/api/logout')
        self.assertEqual(reverse('token_refresh'), '/api/token/refresh')
        self.assertEqual(reverse('password_reset_request'), '/api/password-reset')
        self.assertEqual(reverse('password_reset_confirm'), '/api/password-reset/confirm')
        self.assertEqual(reverse('register'), '/api/register')
        self.assertEqual(reverse('user-list'), '/api/users')
        self.assertEqual(reverse('user-me'), '/api/users/me')
        self.assertEqual(reverse('user-2fa-setup'), '/api/users/me/2fa/setup')
        self.assertEqual(reverse('user-me-2fa'), '/api/users/me/2fa')
        self.assertEqual(reverse('user-me-subscription'), '/api/users/me/subscription')
        self.assertEqual(reverse('user-detail', kwargs={'pk': 7}), '/api/users/7')
        self.assertEqual(reverse('user-2fa-detail', kwargs={'pk': 7}), '/api/users/7/2fa')
        self.assertEqual(reverse('user-subscription', kwargs={'pk': 7}), '/api/users/7/subscription')
        self.assertEqual(reverse('webhooks'), '/api/webhooks')
        self.assertEqual(reverse('location_lookup'), '/api/location/lookup')
        self.assertEqual(reverse('donation-list'), '/api/donations')
        self.assertEqual(reverse('donation-me'), '/api/donations/me')
        self.assertEqual(reverse('donation-detail', kwargs={'pk': 9}), '/api/donations/9')
        self.assertEqual(reverse('material-list'), '/api/brandfiberlookups')
        self.assertEqual(reverse('material-fibers'), '/api/brandfiberlookups/fibers')

    def test_trailing_slash_variants_return_404(self):
        for path in (
            '/api/login/',
            '/api/logout/',
            '/api/token/refresh/',
            '/api/password-reset/',
            '/api/password-reset/confirm/',
            '/api/register/',
            '/api/users/',
            '/api/users/me/',
            '/api/users/me/2fa/setup/',
            '/api/users/me/2fa/',
            '/api/users/me/subscription/',
            '/api/users/7/',
            '/api/users/7/2fa/',
            '/api/users/7/subscription/',
            '/api/webhooks/',
            '/api/location/lookup/',
            '/api/donations/',
            '/api/donations/me/',
            '/api/donations/9/',
            '/api/brandfiberlookups/',
            '/api/brandfiberlookups/fibers/',
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, path)

    def test_webhooks_route_resolves_to_dedicated_webhook_view_module(self):
        match = resolve('/api/webhooks')
        self.assertEqual(match.func, webhooks_view)
        self.assertEqual(match.func.__module__, 'backend.views.webhooks')

class AuthenticationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.password = "Password123"
        self.user = User.objects.create_user(
            email="tester@example.com",
            password=self.password,
            role="Donor",
            first_name="John",
            last_name="Doe",
            contact_no="+639123456789",
            status="ACTIVE"
        )
        self.login_url = reverse('token_obtain_pair')
        self.logout_url = reverse('token_blacklist')

    def test_login_success(self):
        response = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('access', response.data)
        self.assertNotIn('refresh', response.data)
        self.assertEqual(response.data['role'], "Donor")
        self.assertNotIn('name', response.data)
        self.assertNotIn('email', response.data)
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)

    def test_login_blocked_if_not_active(self):
        self.user.status = "UNDER_REVIEW"
        self.user.save()
        response = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_success(self):
        login_res = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')

        cookie_client = APIClient(enforce_csrf_checks=True)
        cookie_client.cookies['refresh_token'] = login_res.cookies['refresh_token'].value
        cookie_client.cookies['csrftoken'] = 'a' * 32
        response = cookie_client.post(
            self.logout_url,
            {},
            format='json',
            HTTP_X_CSRFTOKEN='a' * 32
        )
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)
        self.assertEqual(response.data['message'], "Successfully logged out")
        self.assertEqual(response.cookies['access_token'].value, '')
        self.assertEqual(response.cookies['refresh_token'].value, '')

    def test_cookie_auth_can_access_protected_endpoint(self):
        login_res = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')

        cookie_client = APIClient(enforce_csrf_checks=True)
        cookie_client.cookies['access_token'] = login_res.cookies['access_token'].value
        response = cookie_client.get(reverse('user-me'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], "tester@example.com")

    def test_cookie_refresh_uses_refresh_cookie_and_rotates_access_cookie(self):
        login_res = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')

        cookie_client = APIClient(enforce_csrf_checks=True)
        cookie_client.cookies['refresh_token'] = login_res.cookies['refresh_token'].value
        cookie_client.cookies['csrftoken'] = 'a' * 32

        response = cookie_client.post(
            reverse('token_refresh'),
            {},
            format='json',
            HTTP_X_CSRFTOKEN='a' * 32
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('access', response.data)
        self.assertIn('access_token', response.cookies)

    def test_cookie_refresh_requires_csrf_when_refresh_cookie_is_used(self):
        login_res = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')

        cookie_client = APIClient(enforce_csrf_checks=True)
        cookie_client.cookies['refresh_token'] = login_res.cookies['refresh_token'].value

        response = cookie_client.post(reverse('token_refresh'), {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_preflight_request_returns_cors_headers_for_frontend_origin(self):
        response = self.client.options(
            reverse('user-me'),
            HTTP_ORIGIN='http://127.0.0.1:8001',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='DELETE'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Access-Control-Allow-Origin'], 'http://127.0.0.1:8001')
        self.assertEqual(response['Access-Control-Allow-Credentials'], 'true')

class PasswordResetTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.email = "joshua.vinson@benilde.edu.ph"
        # Ensure the user doesn't exist before we create them
        User.objects.filter(email=self.email).delete()
        
        self.password = "OldPassword123"
        self.user = User.objects.create_user(
            email=self.email,
            password=self.password,
            role="Donor",
            contact_no="+639150000005",
            is_2fa_enabled=True,
            totp_secret="JBSWY3DPEHPK3PXP",
            status="ACTIVE"
        )
        self.request_url = reverse('password_reset_request')
        self.confirm_url = reverse('password_reset_confirm')

    @patch('backend.views.auth.send_password_reset_email')
    def test_password_reset_flow(self, mock_send_email):
        # 1. Request reset (Mocked - will not send a REAL email)
        response = self.client.post(self.request_url, {'email': self.email}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send_email.assert_called_once()
        self.assertEqual(
            response.data['message'],
            "If that email exists, a password reset link has been sent."
        )

        # 2. Generate token (simulating what would be in the email)
        from backend.services.auth_service import generate_reset_token
        uidb64, token = generate_reset_token(self.user)

        # 3. Confirm reset
        new_pw = "NewSecret123"
        confirm_payload = {
            'uidb64': uidb64,
            'token': token,
            'new_password': new_pw
        }
        response = self.client.post(self.confirm_url, confirm_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Password has been reset successfully", response.data['message'])

        # 4. Verify user state (2FA should be disabled)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_2fa_enabled)
        self.assertIsNone(self.user.totp_secret)
        
        # 5. Verify login works with new password
        login_res = self.client.post(reverse('token_obtain_pair'), {
            "email": self.email,
            "password": new_pw
        }, format='json')
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)


class TwoFactorEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_password = "Password123"
        self.owner = User.objects.create_user(
            email="twofa_owner@example.com",
            password=self.owner_password,
            role="Donor",
            contact_no="+639150000101",
            status="ACTIVE"
        )
        self.admin = User.objects.create_user(
            email="twofa_admin@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639150000102",
            status="ACTIVE"
        )
        self.other_user = User.objects.create_user(
            email="twofa_other@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639150000103",
            status="ACTIVE"
        )
        self.setup_url = reverse('user-2fa-setup')
        self.me_2fa_url = reverse('user-me-2fa')
        self.owner_2fa_url = reverse('user-2fa-detail', kwargs={'pk': self.owner.user_id})
        self.other_2fa_url = reverse('user-2fa-detail', kwargs={'pk': self.other_user.user_id})
        self.login_url = reverse('token_obtain_pair')

    def test_owner_can_get_2fa_setup_data_without_audit_log(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(self.setup_url, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('secret', response.data)
        self.assertIn('provisioning_uri', response.data)
        self.assertIn('otpauth://totp/', response.data['provisioning_uri'])
        self.assertIn('issuer=WeaveForward', response.data['provisioning_uri'])
        self.assertFalse(AuditTrail.objects.filter(entity_type='users', actor=self.owner).exists())

    def test_owner_can_enable_2fa_with_valid_otp(self):
        self.client.force_authenticate(user=self.owner)
        setup_response = self.client.post(self.setup_url, format='json')
        secret = setup_response.data['secret']
        otp_code = pyotp.TOTP(secret).now()

        response = self.client.post(
            self.owner_2fa_url,
            {"secret": secret, "otp_code": otp_code},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_2fa_enabled)
        self.assertEqual(self.owner.totp_secret, secret)
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.owner,
                fields_modified='["is_2fa_enabled","totp_secret"]'
            ).exists()
        )

    def test_owner_cannot_enable_2fa_with_invalid_otp(self):
        self.client.force_authenticate(user=self.owner)
        setup_response = self.client.post(self.setup_url, format='json')
        secret = setup_response.data['secret']

        response = self.client.post(
            self.owner_2fa_url,
            {"secret": secret, "otp_code": "000000"},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'][0], 'Invalid 2FA code.')
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_2fa_enabled)
        self.assertIsNone(self.owner.totp_secret)

    def test_owner_cannot_enable_2fa_with_non_32_char_secret(self):
        self.client.force_authenticate(user=self.owner)
        secret = pyotp.random_base32(length=64)
        otp_code = pyotp.TOTP(secret).now()

        response = self.client.post(
            self.owner_2fa_url,
            {"secret": secret, "otp_code": otp_code},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['secret'][0], 'Ensure this field has no more than 32 characters.')
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_2fa_enabled)
        self.assertIsNone(self.owner.totp_secret)

    def test_admin_cannot_enable_2fa_for_another_user(self):
        self.client.force_authenticate(user=self.admin)
        secret = pyotp.random_base32()
        otp_code = pyotp.TOTP(secret).now()

        response = self.client.post(
            self.other_2fa_url,
            {"secret": secret, "otp_code": otp_code},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.other_user.refresh_from_db()
        self.assertFalse(self.other_user.is_2fa_enabled)
        self.assertIsNone(self.other_user.totp_secret)

    def test_non_owner_non_admin_cannot_enable_2fa_for_another_user(self):
        self.client.force_authenticate(user=self.owner)
        secret = pyotp.random_base32()
        otp_code = pyotp.TOTP(secret).now()

        response = self.client.post(
            self.other_2fa_url,
            {"secret": secret, "otp_code": otp_code},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.other_user.refresh_from_db()
        self.assertFalse(self.other_user.is_2fa_enabled)
        self.assertIsNone(self.other_user.totp_secret)

    def test_owner_can_disable_own_2fa_and_clear_secret(self):
        self.owner.is_2fa_enabled = True
        self.owner.totp_secret = pyotp.random_base32()
        self.owner.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self.owner_2fa_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_2fa_enabled)
        self.assertIsNone(self.owner.totp_secret)
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.owner,
                fields_modified='["is_2fa_enabled","totp_secret"]'
            ).exists()
        )

    def test_owner_can_enable_2fa_via_me_endpoint(self):
        self.client.force_authenticate(user=self.owner)
        setup_response = self.client.post(self.setup_url, format='json')
        secret = setup_response.data['secret']
        otp_code = pyotp.TOTP(secret).now()

        response = self.client.post(
            self.me_2fa_url,
            {"secret": secret, "otp_code": otp_code},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_2fa_enabled)
        self.assertEqual(self.owner.totp_secret, secret)
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.owner,
                fields_modified='["is_2fa_enabled","totp_secret"]'
            ).exists()
        )

    def test_owner_cannot_enable_2fa_via_me_endpoint_with_non_32_char_secret(self):
        self.client.force_authenticate(user=self.owner)
        secret = pyotp.random_base32()[:-1]
        otp_code = pyotp.TOTP(secret).now()

        response = self.client.post(
            self.me_2fa_url,
            {"secret": secret, "otp_code": otp_code},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['secret'][0], 'Ensure this field has at least 32 characters.')
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_2fa_enabled)
        self.assertIsNone(self.owner.totp_secret)

    def test_owner_can_disable_own_2fa_via_me_endpoint(self):
        self.owner.is_2fa_enabled = True
        self.owner.totp_secret = pyotp.random_base32()
        self.owner.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self.me_2fa_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_2fa_enabled)
        self.assertIsNone(self.owner.totp_secret)
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.owner,
                fields_modified='["is_2fa_enabled","totp_secret"]'
            ).exists()
        )

    def test_admin_can_disable_any_users_2fa(self):
        self.other_user.is_2fa_enabled = True
        self.other_user.totp_secret = pyotp.random_base32()
        self.other_user.save()

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.other_2fa_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.other_user.refresh_from_db()
        self.assertFalse(self.other_user.is_2fa_enabled)
        self.assertIsNone(self.other_user.totp_secret)
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.admin,
                fields_modified='["is_2fa_enabled","totp_secret"]'
            ).exists()
        )

    def test_non_owner_non_admin_cannot_disable_another_users_2fa(self):
        self.other_user.is_2fa_enabled = True
        self.other_user.totp_secret = pyotp.random_base32()
        self.other_user.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self.other_2fa_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.other_user.refresh_from_db()
        self.assertTrue(self.other_user.is_2fa_enabled)
        self.assertIsNotNone(self.other_user.totp_secret)

    def test_login_requires_otp_only_when_2fa_is_enabled(self):
        secret = pyotp.random_base32()
        self.owner.is_2fa_enabled = True
        self.owner.totp_secret = secret
        self.owner.save()

        response = self.client.post(
            self.login_url,
            {"email": self.owner.email, "password": self.owner_password},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(response.data['2fa_required'])

        response = self.client.post(
            self.login_url,
            {
                "email": self.owner.email,
                "password": self.owner_password,
                "otp_code": pyotp.TOTP(secret).now()
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class UserAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.upload = Upload.objects.create(file_path="profile/test.png", name="Test Upload")
        self.admin = User.objects.create_user(
            email="admin_test@example.com", password="Pass", role="Admin", contact_no="+639001", status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="donor_test@example.com", password="Pass", role="Donor", contact_no="+639002", status="ACTIVE",
            latitude=Decimal('14.771562800000000'), longitude=Decimal('121.066589400000000')
        )
        self.tuab_active = User.objects.create_user(
            email="tuab_active@example.com", password="Pass", role="TUAB", contact_no="+639003", status="ACTIVE", operational_status="ACTIVE",
            latitude=Decimal('14.771562800000000'), longitude=Decimal('121.066589400000000')
        )
        self.tuab_inactive = User.objects.create_user(
            email="tuab_inactive@example.com", password="Pass", role="TUAB", contact_no="+639004", status="ACTIVE", operational_status="HIBERNATING"
        )
        self.tuab_under_review = User.objects.create_user(
            email="tuab_review@example.com", password="Pass", role="TUAB", contact_no="+639005", status="UNDER_REVIEW", operational_status="ACTIVE"
        )
        Subscription.objects.create(
            user=self.tuab_active,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )
        Subscription.objects.create(
            user=self.donor,
            status='CANCELLED',
            subscription_tier='FREE',
            start_date='2026-04-01T00:00:00Z',
            end_date='2026-05-01T00:00:00Z'
        )

    def test_user_list_visibility(self):
        # Admin can list all
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('user-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 5) # Admin, Donor, TUAB Active, TUAB Inactive, TUAB Under Review
        admin_row = next(row for row in res.data['results'] if row['user_id'] == self.admin.user_id)
        donor_row = next(row for row in res.data['results'] if row['user_id'] == self.donor.user_id)
        tuab_active_row = next(row for row in res.data['results'] if row['user_id'] == self.tuab_active.user_id)
        self.assertEqual(admin_row['etag'], build_updated_at_etag(self.admin))
        self.assertEqual(donor_row['etag'], build_updated_at_etag(self.donor))
        self.assertEqual(tuab_active_row['etag'], build_updated_at_etag(self.tuab_active))
        self.assertFalse(admin_row['is_subscribed'])
        self.assertFalse(donor_row['is_subscribed'])
        self.assertTrue(tuab_active_row['is_subscribed'])
        self.assertEqual(
            set(admin_row.keys()),
            {'user_id', 'email', 'role', 'first_name', 'last_name', 'middle_name', 'business_name', 'contact_no', 'status', 'is_subscribed', 'etag'}
        )
        for removed_field in ['barangay', 'city', 'latitude', 'longitude', 'display_address', 'is_2fa_enabled', 'upload', 'created_at', 'updated_at']:
            self.assertNotIn(removed_field, donor_row)
        
        # Donor sees active TUABs
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('user-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['results']), 1)
        public_row = res.data['results'][0]
        self.assertEqual(public_row['email'], self.tuab_active.email)
        self.assertNotIn('is_subscribed', public_row)
        self.assertEqual(
            set(public_row.keys()),
            {'user_id', 'email', 'role', 'business_name', 'description', 'barangay', 'city', 'upload', 'target_fibers'}
        )

    def test_admin_user_list_can_filter_by_status(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('user-list'), {'role': 'TUAB', 'status': 'UNDER_REVIEW'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['user_id'], self.tuab_under_review.user_id)

    def test_user_retrieve_logic(self):
        # Non-admins can only retrieve publicly visible TUABs.
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.donor.user_id}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Donor cannot see admin
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.admin.user_id}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        
        # Donor can see active TUABs with active operational status.
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.tuab_active.user_id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['email'], self.tuab_active.email)
        self.assertNotIn('is_subscribed', res.data)
        self.assertNotIn('documentation', res.data)
        for detailed_field in ['contact_no', 'display_address', 'latitude', 'longitude', 'social_link', 'max_distance_km', 'min_biodeg_score', 'operational_status']:
            self.assertIn(detailed_field, res.data)
        self.assertIn('ETag', res)
        
        # Donor cannot see inactive TUAB
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.tuab_inactive.user_id}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Donor cannot see under-review TUAB
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.tuab_under_review.user_id}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Admin can see everyone
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.donor.user_id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('ETag', res)
        self.assertFalse(res.data['is_subscribed'])
        for detailed_field in ['barangay', 'city', 'latitude', 'longitude', 'display_address', 'is_2fa_enabled', 'upload', 'created_at', 'updated_at']:
            self.assertIn(detailed_field, res.data)

        res = self.client.get(reverse('user-detail', kwargs={'pk': self.tuab_active.user_id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['is_subscribed'])

    def test_user_me_shortcut(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('user-me'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['email'], self.donor.email)
        self.assertEqual(res['ETag'], build_updated_at_etag(self.donor))
        self.assertNotIn('is_subscribed', res.data)
        self.assertEqual(res.data['latitude'], '14.7715628')
        self.assertEqual(res.data['longitude'], '121.0665894')
        self.assertEqual(
            set(res.data.keys()),
            {
                'user_id', 'email', 'role', 'first_name', 'last_name', 'middle_name',
                'contact_no', 'barangay', 'city', 'latitude', 'longitude',
                'display_address', 'is_2fa_enabled', 'upload', 'created_at',
                'updated_at', 'etag'
            }
        )

        self.client.force_authenticate(user=self.tuab_active)
        res = self.client.get(reverse('user-me'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['email'], self.tuab_active.email)
        self.assertTrue(res.data['is_subscribed'])
        self.assertEqual(
            set(res.data.keys()),
            {
                'user_id', 'email', 'role', 'business_name', 'description',
                'social_link', 'max_active_claims', 'target_fibers',
                'min_biodeg_score', 'max_distance_km', 'operational_status',
                'contact_no', 'barangay', 'city', 'latitude', 'longitude',
                'display_address', 'is_2fa_enabled', 'is_subscribed', 'upload',
                'created_at', 'etag'
            }
        )

    def test_user_endpoints_serialize_coordinates_with_exactly_7_decimal_places(self):
        self.client.force_authenticate(user=self.admin)
        detail_res = self.client.get(reverse('user-detail', kwargs={'pk': self.donor.user_id}))
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.data['latitude'], '14.7715628')
        self.assertEqual(detail_res.data['longitude'], '121.0665894')

        self.client.force_authenticate(user=self.donor)
        list_res = self.client.get(reverse('user-list'))
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertNotIn('latitude', list_res.data['results'][0])
        self.assertNotIn('longitude', list_res.data['results'][0])

    def test_user_patch_self_password_only(self):
        self.client.force_authenticate(user=self.donor)
        etag = build_updated_at_etag(self.donor)
        payload = {
            "password": "NewPass123",
            "first_name": "Updated",
        }
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            payload,
            format='json',
            HTTP_IF_MATCH=etag
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.donor.refresh_from_db()
        self.assertTrue(self.donor.check_password("NewPass123"))
        self.assertEqual(self.donor.first_name, "Updated")
        self.assertEqual(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.donor
            ).count(),
            1
        )
        self.assertEqual(res['ETag'], build_updated_at_etag(self.donor))

    @patch('backend.serializers.users.default_storage.save', return_value='profile_photos/new-profile.png')
    def test_user_patch_accepts_upload_file(self, mocked_save):
        self.client.force_authenticate(user=self.donor)
        etag = build_updated_at_etag(self.donor)
        upload = SimpleUploadedFile(
            "avatar.png",
            b"fake-image-bytes",
            content_type="image/png"
        )

        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {
                "first_name": "WithPhoto",
                "upload": upload,
            },
            format='multipart',
            HTTP_IF_MATCH=etag
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        mocked_save.assert_called_once()

        self.donor.refresh_from_db()
        self.assertEqual(self.donor.first_name, "WithPhoto")
        self.assertIsNotNone(self.donor.upload)
        self.assertEqual(self.donor.upload.file_path, 'profile_photos/new-profile.png')
        self.assertEqual(self.donor.upload.name, 'avatar.png')
        self.assertTrue(res.data['upload'].endswith(self.donor.upload.file_path))
        self.assertNotIn('documentation', res.data)
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.donor,
                fields_modified='["first_name","upload"]'
            ).exists()
        )

    def test_user_patch_rejects_upload_id_in_json(self):
        self.client.force_authenticate(user=self.donor)
        etag = build_updated_at_etag(self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {
                "upload": self.upload.upload_id,
            },
            format='json',
            HTTP_IF_MATCH=etag
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('upload', res.data)

    def test_user_patch_forbidden_for_other_user(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.admin.user_id}),
            {"first_name": "Hacker"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.admin)
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_patch_other_user(self):
        self.client.force_authenticate(user=self.admin)
        etag = build_updated_at_etag(self.donor)
        payload = {
            "password": "AdminSet123",
            "last_name": "Changed",
        }
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            payload,
            format='json',
            HTTP_IF_MATCH=etag
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.donor.refresh_from_db()
        self.assertTrue(self.donor.check_password("AdminSet123"))
        self.assertEqual(self.donor.last_name, "Changed")
        self.assertEqual(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.admin
            ).count(),
            1
        )
        self.assertEqual(res['ETag'], build_updated_at_etag(self.donor))

    def test_user_patch_password_only_returns_new_etag(self):
        self.client.force_authenticate(user=self.donor)
        original_etag = build_updated_at_etag(self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"password": "Password456"},
            format='json',
            HTTP_IF_MATCH=original_etag
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.donor.refresh_from_db()
        self.assertTrue(self.donor.check_password("Password456"))
        self.assertNotEqual(res['ETag'], original_etag)
        self.assertEqual(res['ETag'], build_updated_at_etag(self.donor))

    def test_user_patch_rejects_short_password(self):
        self.client.force_authenticate(user=self.donor)
        original_password = "Pass"
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"password": "Short1"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data['password'][0],
            "Password must be at least 8 characters and contain both letters and numbers."
        )

        self.donor.refresh_from_db()
        self.assertTrue(self.donor.check_password(original_password))
        self.assertFalse(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.donor
            ).exists()
        )

    def test_user_patch_rejects_letters_only_password(self):
        self.client.force_authenticate(user=self.donor)
        original_password = "Pass"
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"password": "LettersOnly"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data['password'][0],
            "Password must be at least 8 characters and contain both letters and numbers."
        )

        self.donor.refresh_from_db()
        self.assertTrue(self.donor.check_password(original_password))
        self.assertFalse(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.donor
            ).exists()
        )

    def test_user_patch_rejects_numbers_only_password(self):
        self.client.force_authenticate(user=self.donor)
        original_password = "Pass"
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"password": "12345678"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data['password'][0],
            "Password must be at least 8 characters and contain both letters and numbers."
        )

        self.donor.refresh_from_db()
        self.assertTrue(self.donor.check_password(original_password))
        self.assertFalse(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.donor
            ).exists()
        )

    def test_user_patch_populates_city_and_barangay_from_coordinates(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {
                "latitude": "14.5995120",
                "longitude": "120.9842220",
                "display_address": "Manila"
            },
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.donor.refresh_from_db()
        self.assertIsNotNone(self.donor.city)
        self.assertIsNotNone(self.donor.barangay)
        self.assertEqual(res.data['city'], self.donor.city)
        self.assertEqual(res.data['barangay'], self.donor.barangay)

    def test_user_patch_rejects_email_updates(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"email": "new_email@example.com"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['email'][0], "This field cannot be updated through this endpoint.")

    def test_donor_patch_rejects_blank_required_profile_fields(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {
                "first_name": "   ",
                "last_name": "",
                "contact_no": "",
                "display_address": "",
                "latitude": None,
                "longitude": None,
            },
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['first_name'][0], "This field may not be blank.")
        self.assertEqual(res.data['last_name'][0], "This field may not be blank.")
        self.assertEqual(res.data['contact_no'][0], "This field may not be blank.")

    def test_user_patch_rejects_status_updates(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"status": "ARCHIVED"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['status'][0], "This field cannot be updated through this endpoint.")

    def test_user_patch_rejects_updates_for_archived_user(self):
        self.donor.status = 'ARCHIVED'
        self.donor.save(update_fields=['status'])
        self.client.force_authenticate(user=self.admin)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"first_name": "Updated"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['detail'], "Only active users can be edited.")
        self.donor.refresh_from_db()
        self.assertNotEqual(self.donor.first_name, "Updated")
        self.assertFalse(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.admin
            ).exists()
        )

    def test_user_patch_rejects_manual_city_and_barangay(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"city": "Manual City", "barangay": "Manual Barangay"},
            format='json',
            HTTP_IF_MATCH=build_updated_at_etag(self.donor)
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['city'][0], "This field cannot be updated through this endpoint.")
        self.assertEqual(res.data['barangay'][0], "This field cannot be updated through this endpoint.")

    def test_user_patch_requires_if_match_header(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"first_name": "Updated"},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_428_PRECONDITION_REQUIRED)
        self.assertEqual(res.data['detail'], "If-Match header is required.")

    @patch.object(User.objects, 'select_for_update', wraps=User.objects.select_for_update)
    def test_admin_can_approve_under_review_tuab(self, mocked_select_for_update):
        self.client.force_authenticate(user=self.admin)
        original_updated_at = self.tuab_under_review.updated_at

        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_under_review.user_id}),
            {"status": "ACTIVE"},
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        mocked_select_for_update.assert_called_once()

        self.tuab_under_review.refresh_from_db()
        self.assertEqual(self.tuab_under_review.status, 'ACTIVE')
        self.assertGreater(self.tuab_under_review.updated_at, original_updated_at)
        self.assertEqual(res.data['status'], 'ACTIVE')
        self.assertEqual(res['ETag'], build_updated_at_etag(self.tuab_under_review))
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type='users',
                action='STATUS_CHANGE',
                actor=self.admin,
                fields_modified='["status"]'
            ).exists()
        )

    def test_non_admin_cannot_approve_tuab(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_under_review.user_id}),
            {"status": "ACTIVE"},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_approve_non_tuab_user(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.donor.user_id}),
            {"status": "ACTIVE"},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['detail'], "Only TUAB users can be reviewed via this endpoint.")

    def test_admin_cannot_approve_tuab_not_under_review(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_active.user_id}),
            {"status": "ACTIVE"},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['detail'], "Only TUAB users under review can be reviewed.")
        self.assertFalse(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.donor
            ).exists()
        )

    def test_user_patch_rejects_stale_if_match_header(self):
        self.client.force_authenticate(user=self.donor)
        stale_etag = build_updated_at_etag(self.donor)
        self.donor.first_name = "Server Change"
        self.donor.save()

        res = self.client.patch(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            {"last_name": "Client Change"},
            format='json',
            HTTP_IF_MATCH=stale_etag
        )
        self.assertEqual(res.status_code, status.HTTP_412_PRECONDITION_FAILED)
        self.assertEqual(res.data['detail'], "ETag does not match the current resource version.")
        self.donor.refresh_from_db()
        self.assertNotEqual(self.donor.last_name, "Client Change")
        self.assertFalse(
            AuditTrail.objects.filter(
                entity_type='users',
                action='CREDENTIAL_UPDATE',
                actor=self.donor
            ).exists()
        )


class ETagServiceTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="etag_admin@example.com", password="Pass", role="Admin", contact_no="+639150000203", status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="etag_donor@example.com", password="Pass", role="Donor", contact_no="+639150000204", status="ACTIVE"
        )

    def test_build_updated_at_etag_is_stable_and_quoted(self):
        user = User.objects.create_user(
            email="etag_test@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639150000201",
            status="ACTIVE"
        )
        etag_one = build_updated_at_etag(user)
        etag_two = build_updated_at_etag(user)

        self.assertEqual(etag_one, etag_two)
        self.assertTrue(etag_one.startswith('W/"'))
        self.assertTrue(etag_one.endswith('"'))

    def test_build_updated_at_etag_changes_when_updated_at_changes(self):
        user = User.objects.create_user(
            email="etag_change@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639150000202",
            status="ACTIVE"
        )
        old_etag = build_updated_at_etag(user)
        User.objects.filter(pk=user.pk).update(updated_at=user.updated_at + timedelta(seconds=1))
        user.refresh_from_db()

        self.assertNotEqual(old_etag, build_updated_at_etag(user))

    def test_create_donor_via_users_endpoint(self):
        payload = {
            'role': 'Donor',
            'first_name': 'New',
            'last_name': 'Donor',
            'email': 'new_donor@example.com',
            'contact_no': '+639179999999',
            'password': 'Password123',
            'latitude': '14.5995120',
            'longitude': '120.9842220',
            'display_address': 'Manila'
        }
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(reverse('user-list'), payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='new_donor@example.com').exists())

    def test_create_tuab_via_users_endpoint(self):
        payload = {
            'role': 'TUAB',
            'business_name': 'New TUAB',
            'email': 'new_tuab@example.com',
            'contact_no': '+639189999999',
            'password': 'Password123',
            'latitude': '14.5995120',
            'longitude': '120.9842220',
            'display_address': 'Manila',
            'target_fibers': 'cotton,wool',
            'max_distance_km': '50.00',
            'min_biodeg_score': '70.00'
        }
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(reverse('user-list'), payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['error'], "Only Donor creation is supported via this endpoint.")

    def test_create_user_invalid_role(self):
        payload = {'role': 'Admin', 'email': 'admin2@ex.com'}
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(reverse('user-list'), payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['error'], "Only Donor creation is supported via this endpoint.")

    def test_create_user_forbidden_for_donor(self):
        self.client.force_authenticate(user=self.donor)
        payload = {'role': 'Donor', 'email': 'hacker@ex.com', 'password': 'Password123'}
        res = self.client.post(reverse('user-list'), payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class UserSubscriptionAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="sub_admin@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639150000281",
            status="ACTIVE"
        )
        self.user = User.objects.create_user(
            email="sub_user@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639150000282",
            status="ACTIVE",
            maya_customer_id="maya-customer-sub",
            maya_card_id="maya-card-sub"
        )
        self.tuab = User.objects.create_user(
            email="sub_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000283",
            status="ACTIVE",
            operational_status="ACTIVE"
        )
        self.other_tuab = User.objects.create_user(
            email="sub_other_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000284",
            status="ACTIVE",
            operational_status="ACTIVE"
        )
        self.archived_tuab = User.objects.create_user(
            email="archived_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000285",
            status="ARCHIVED",
            operational_status="ACTIVE"
        )
        self.review_tuab = User.objects.create_user(
            email="review_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000286",
            status="UNDER_REVIEW",
            operational_status="ACTIVE"
        )
        self.subscribe_payload = {
            "firstName": "Joshua",
            "lastName": "Vinson",
            "card": {
                "number": "5123456789012346",
                "expMonth": "12",
                "expYear": "2030",
                "cvc": "111",
            }
        }

    def maya_response(self, status_code, payload):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        response.text = json.dumps(payload)
        return response

    def test_user_cannot_unsubscribe_without_active_subscription(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.delete(reverse('user-me-subscription'))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], "User does not have an active subscription.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.maya_customer_id, "maya-customer-sub")
        self.assertEqual(self.user.maya_card_id, "maya-card-sub")
        self.assertEqual(AuditTrail.objects.count(), 0)

    def test_admin_cannot_unsubscribe_user_without_active_subscription(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.delete(reverse('user-subscription', kwargs={'pk': self.user.user_id}))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], "User does not have an active subscription.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.maya_customer_id, "maya-customer-sub")
        self.assertEqual(self.user.maya_card_id, "maya-card-sub")
        self.assertEqual(AuditTrail.objects.count(), 0)

    def test_user_can_unsubscribe_with_active_subscription(self):
        active_subscription = Subscription.objects.create(
            user=self.user,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        with patch('backend.services.subscription_service.requests.delete') as mocked_delete:
            mocked_delete.return_value = self.maya_response(200, {'status': 'deleted'})
            self.client.force_authenticate(user=self.user)
            response = self.client.delete(reverse('user-me-subscription'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], "Successfully unsubscribed.")
        self.user.refresh_from_db()
        active_subscription.refresh_from_db()
        self.assertEqual(self.user.maya_customer_id, "maya-customer-sub")
        self.assertIsNone(self.user.maya_card_id)
        self.assertEqual(active_subscription.status, 'CANCELLED')
        mocked_delete.assert_called_once()
        delete_call = mocked_delete.call_args
        self.assertEqual(
            delete_call.args[0],
            'https://pg-sandbox.paymaya.com/payments/v1/customers/maya-customer-sub/cards/maya-card-sub'
        )
        self.assertEqual(delete_call.kwargs['headers']['Authorization'], settings.MAYA_SANDBOX_SECRET_BASIC_AUTH)

    def test_admin_can_unsubscribe_user_with_active_subscription(self):
        active_subscription = Subscription.objects.create(
            user=self.user,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        with patch('backend.services.subscription_service.requests.delete') as mocked_delete:
            mocked_delete.return_value = self.maya_response(200, {'status': 'deleted'})
            self.client.force_authenticate(user=self.admin)
            response = self.client.delete(reverse('user-subscription', kwargs={'pk': self.user.user_id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], "Successfully unsubscribed.")
        self.user.refresh_from_db()
        active_subscription.refresh_from_db()
        self.assertEqual(self.user.maya_customer_id, "maya-customer-sub")
        self.assertIsNone(self.user.maya_card_id)
        self.assertEqual(active_subscription.status, 'CANCELLED')
        mocked_delete.assert_called_once()

    def test_user_unsubscribe_fails_when_maya_card_delete_fails(self):
        active_subscription = Subscription.objects.create(
            user=self.user,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        with patch('backend.services.subscription_service.requests.delete') as mocked_delete:
            mocked_delete.return_value = self.maya_response(400, {'error': 'Cannot delete card'})
            self.client.force_authenticate(user=self.user)
            response = self.client.delete(reverse('user-me-subscription'))

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Maya card deletion failed", response.data['detail'])
        self.user.refresh_from_db()
        active_subscription.refresh_from_db()
        self.assertEqual(self.user.maya_customer_id, "maya-customer-sub")
        self.assertEqual(self.user.maya_card_id, "maya-card-sub")
        self.assertEqual(active_subscription.status, 'ACTIVE')

    def test_user_unsubscribe_fails_when_maya_card_delete_raises(self):
        active_subscription = Subscription.objects.create(
            user=self.user,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        with patch('backend.services.subscription_service.requests.delete') as mocked_delete:
            mocked_delete.side_effect = requests.RequestException("network down")
            self.client.force_authenticate(user=self.user)
            response = self.client.delete(reverse('user-me-subscription'))

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Maya card deletion failed", response.data['detail'])
        self.user.refresh_from_db()
        active_subscription.refresh_from_db()
        self.assertEqual(self.user.maya_customer_id, "maya-customer-sub")
        self.assertEqual(self.user.maya_card_id, "maya-card-sub")
        self.assertEqual(active_subscription.status, 'ACTIVE')

    @override_settings(
        MAYA_SANDBOX_BASE_URL='https://pg-sandbox.paymaya.com/payments/v1',
        MAYA_SANDBOX_SECRET_BASIC_AUTH='Basic test-secret',
        MAYA_SANDBOX_PUBLIC_BASIC_AUTH='Basic test-public',
    )
    @patch('backend.services.subscription_service.requests.post')
    def test_active_tuab_can_subscribe_self_with_valid_etag(self, mocked_post):
        card_token_id = 'B8dL3edy2qqULa5DSPWuzCSveroBICndc2Ols1cty5mU733RIRY2Pj0maXQSfYyvFNBlvfDZ6uadfDbNUqzFRs7TTYRaZnlfbIxJuNLe5GlTbpknC05ZNcLuAjf34UwKxvAmQENtx5HgmtitjmWM06eI0wm79XcZYVKD2dc'
        mocked_post.side_effect = [
            self.maya_response(200, {'id': 'customer-123'}),
            self.maya_response(200, {'paymentTokenId': card_token_id}),
            self.maya_response(200, {
                'id': '14ff3be6-f677-4975-8d58-c02ddb6313b3',
                'cardTokenId': card_token_id,
                'state': 'PREVERIFICATION',
                'verificationUrl': 'https://payments-web-sandbox.maya.ph/authenticate?id=14ff3be6-f677-4975-8d58-c02ddb6313b3',
            }),
        ]

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tuab.refresh_from_db()
        self.assertEqual(self.tuab.maya_customer_id, 'customer-123')
        self.assertEqual(self.tuab.maya_card_id, card_token_id)
        self.assertEqual(response.data['maya_customer_id'], 'customer-123')
        self.assertEqual(response.data['maya_card_id'], card_token_id)
        self.assertEqual(response.data['cardTokenId'], card_token_id)
        self.assertEqual(response.data['state'], 'PREVERIFICATION')
        self.assertIn('verificationUrl', response.data)
        self.assertFalse(Subscription.objects.filter(user=self.tuab, status='ACTIVE').exists())
        self.assertEqual(mocked_post.call_count, 3)
        first_call, second_call, third_call = mocked_post.call_args_list
        self.assertEqual(first_call.args[0], 'https://pg-sandbox.paymaya.com/payments/v1/customers')
        self.assertEqual(first_call.kwargs['headers']['Authorization'], 'Basic test-secret')
        self.assertEqual(second_call.args[0], 'https://pg-sandbox.paymaya.com/payments/v1/payment-tokens')
        self.assertEqual(second_call.kwargs['headers']['Authorization'], 'Basic test-public')
        self.assertEqual(third_call.args[0], 'https://pg-sandbox.paymaya.com/payments/v1/customers/customer-123/cards')
        self.assertEqual(third_call.kwargs['headers']['Authorization'], 'Basic test-secret')
        self.assertEqual(
            third_call.kwargs['json']['redirectUrl']['success'],
            f"{settings.FRONTEND_URL.rstrip('/')}/tuab/subscribe/?status=success"
        )

    @override_settings(
        MAYA_SANDBOX_BASE_URL='https://pg-sandbox.paymaya.com/payments/v1',
        MAYA_SANDBOX_SECRET_BASIC_AUTH='Basic test-secret',
        MAYA_SANDBOX_PUBLIC_BASIC_AUTH='Basic test-public',
    )
    @patch('backend.services.subscription_service.requests.post')
    def test_subscribe_reuses_existing_maya_customer_id(self, mocked_post):
        card_token_id = 'B8dL3edy2qqULa5DSPWuzCSveroBICndc2Ols1cty5mU733RIRY2Pj0maXQSfYyvFNBlvfDZ6uadfDbNUqzFRs7TTYRaZnlfbIxJuNLe5GlTbpknC05ZNcLuAjf34UwKxvAmQENtx5HgmtitjmWM06eI0wm79XcZYVKD2dc'
        self.tuab.maya_customer_id = 'existing-customer-123'
        self.tuab.save(update_fields=['maya_customer_id', 'updated_at'])
        mocked_post.side_effect = [
            self.maya_response(200, {'paymentTokenId': card_token_id}),
            self.maya_response(200, {
                'id': '14ff3be6-f677-4975-8d58-c02ddb6313b3',
                'cardTokenId': card_token_id,
                'state': 'PREVERIFICATION',
                'verificationUrl': 'https://payments-web-sandbox.maya.ph/authenticate?id=14ff3be6-f677-4975-8d58-c02ddb6313b3',
            }),
        ]

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tuab.refresh_from_db()
        self.assertEqual(self.tuab.maya_customer_id, 'existing-customer-123')
        self.assertEqual(self.tuab.maya_card_id, card_token_id)
        self.assertEqual(mocked_post.call_count, 2)
        first_call, second_call = mocked_post.call_args_list
        self.assertEqual(first_call.args[0], 'https://pg-sandbox.paymaya.com/payments/v1/payment-tokens')
        self.assertEqual(second_call.args[0], 'https://pg-sandbox.paymaya.com/payments/v1/customers/existing-customer-123/cards')

    def test_subscribe_rejects_non_tuab_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.user.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], "Only TUAB users can subscribe themselves.")

    def test_subscribe_rejects_other_users_account(self):
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.other_tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], "You may only subscribe your own account.")

    def test_subscribe_rejects_archived_tuab(self):
        self.client.force_authenticate(user=self.archived_tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.archived_tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], "Only active TUAB users can subscribe.")

    def test_subscribe_rejects_under_review_tuab(self):
        self.client.force_authenticate(user=self.review_tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.review_tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], "Only active TUAB users can subscribe.")

    def test_subscribe_rejects_already_subscribed_tuab(self):
        Subscription.objects.create(
            user=self.tuab,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], "User is already subscribed.")

    @override_settings(
        MAYA_SANDBOX_BASE_URL='https://pg-sandbox.paymaya.com/payments/v1',
        MAYA_SANDBOX_SECRET_BASIC_AUTH='Basic test-secret',
        MAYA_SANDBOX_PUBLIC_BASIC_AUTH='Basic test-public',
    )
    @patch('backend.services.subscription_service.requests.post')
    def test_subscribe_rolls_back_when_maya_customer_creation_fails(self, mocked_post):
        mocked_post.return_value = self.maya_response(400, {'error': 'Bad request'})

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.tuab.refresh_from_db()
        self.assertIsNone(self.tuab.maya_customer_id)
        self.assertIsNone(self.tuab.maya_card_id)

    @override_settings(
        MAYA_SANDBOX_BASE_URL='https://pg-sandbox.paymaya.com/payments/v1',
        MAYA_SANDBOX_SECRET_BASIC_AUTH='Basic test-secret',
        MAYA_SANDBOX_PUBLIC_BASIC_AUTH='Basic test-public',
    )
    @patch('backend.services.subscription_service.requests.post')
    def test_subscribe_rolls_back_when_maya_payment_token_fails(self, mocked_post):
        mocked_post.side_effect = [
            self.maya_response(200, {'id': 'customer-123'}),
            self.maya_response(401, {'error': 'Invalid endpoint'}),
        ]

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.tuab.refresh_from_db()
        self.assertIsNone(self.tuab.maya_customer_id)
        self.assertIsNone(self.tuab.maya_card_id)

    @override_settings(
        MAYA_SANDBOX_BASE_URL='https://pg-sandbox.paymaya.com/payments/v1',
        MAYA_SANDBOX_SECRET_BASIC_AUTH='Basic test-secret',
        MAYA_SANDBOX_PUBLIC_BASIC_AUTH='Basic test-public',
    )
    @patch('backend.services.subscription_service.requests.post')
    def test_subscribe_rolls_back_when_maya_card_bind_fails(self, mocked_post):
        card_token_id = 'B8dL3edy2qqULa5DSPWuzCSveroBICndc2Ols1cty5mU733RIRY2Pj0maXQSfYyvFNBlvfDZ6uadfDbNUqzFRs7TTYRaZnlfbIxJuNLe5GlTbpknC05ZNcLuAjf34UwKxvAmQENtx5HgmtitjmWM06eI0wm79XcZYVKD2dc'
        mocked_post.side_effect = [
            self.maya_response(200, {'id': 'customer-123'}),
            self.maya_response(200, {'paymentTokenId': card_token_id}),
            self.maya_response(400, {'error': 'Card bind failed'}),
        ]

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('user-subscription', kwargs={'pk': self.tuab.user_id}),
            self.subscribe_payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.tuab.refresh_from_db()
        self.assertIsNone(self.tuab.maya_customer_id)
        self.assertIsNone(self.tuab.maya_card_id)


class WebhookAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.card_token_id = 'diRCydigrCU4mTisayRSrJ41IcMN2Y9tdneU7JGKZPIZBx5iUVCGDQM8pnZ7TsN2S2zREmorDqQRQSVShMZ9qBiGYcUdUGdjFPhdteSz2gKXSi4yZNnAQgWioCIPUkdEwBDmhFs81lRFfdT6I5NS2NZblNLO4TpzozkaXEFQ'
        self.tuab = User.objects.create_user(
            email="webhook_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000291",
            status="ACTIVE",
            operational_status="ACTIVE",
            maya_customer_id="maya-customer-verified",
            maya_card_id=self.card_token_id,
        )
        self.webhook_payload = {
            "id": "e1aea1e2-ec95-492a-a5df-26ca85c0df09",
            "isPaid": True,
            "status": "PAYMENT_SUCCESS",
            "amount": "10",
            "currency": "PHP",
            "paymentTokenId": self.card_token_id,
            "fundSource": {
                "type": "card",
                "id": self.card_token_id,
            },
        }

    def maya_response(self, status_code, payload):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        response.text = json.dumps(payload)
        return response

    def webhook_headers(self, ip_address='3.1.199.75', **extra_headers):
        headers = {'HTTP_X_FORWARDED_FOR': ip_address}
        headers.update(extra_headers)
        return headers

    def test_webhook_rejects_non_whitelisted_maya_ip(self):
        response = self.client.post(
            reverse('webhooks'),
            self.webhook_payload,
            format='json',
            **self.webhook_headers('203.0.113.25')
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], "Webhook source IP is not allowlisted.")
        self.assertFalse(Subscription.objects.exists())
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_unrelated_maya_webhook_is_ignored(self):
        unrelated_payload = self.webhook_payload.copy()
        unrelated_payload['status'] = 'PAYMENT_PENDING'

        response = self.client.post(
            reverse('webhooks'),
            unrelated_payload,
            format='json',
            **self.webhook_headers()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], "Maya webhook acknowledged with no subscription action taken.")
        self.assertFalse(Subscription.objects.exists())
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_auth_failed_verification_webhook_clears_maya_card_id(self):
        failed_payload = self.webhook_payload.copy()
        failed_payload['status'] = 'AUTH_FAILED'
        failed_payload['isPaid'] = False

        response = self.client.post(
            reverse('webhooks'),
            failed_payload,
            format='json',
            **self.webhook_headers()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['detail'],
            "Maya card verification failed (AUTH_FAILED) and the card token was cleared."
        )
        self.tuab.refresh_from_db()
        self.assertIsNone(self.tuab.maya_card_id)
        self.assertFalse(Subscription.objects.exists())
        self.assertFalse(SubscriptionPayment.objects.exists())

    @override_settings(
        MAYA_SANDBOX_BASE_URL='https://pg-sandbox.paymaya.com/payments/v1',
        MAYA_SANDBOX_SECRET_BASIC_AUTH='Basic test-secret',
    )
    @patch('backend.services.subscription_service.requests.get')
    @patch('backend.services.subscription_service.requests.post')
    def test_verification_success_webhook_charges_and_activates_subscription(self, mocked_post, mocked_get):
        mocked_get.return_value = self.maya_response(200, {
            'id': 'e1aea1e2-ec95-492a-a5df-26ca85c0df09',
            'status': 'PAYMENT_SUCCESS',
        })
        mocked_post.return_value = self.maya_response(200, {
            'id': 'maya-charge-1',
            'isPaid': True,
            'status': 'PAYMENT_SUCCESS',
            'amount': '499',
            'currency': 'PHP',
        })

        response = self.client.post(
            reverse('webhooks'),
            self.webhook_payload,
            format='json',
            **self.webhook_headers()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['detail'],
            "Maya card verification succeeded and the subscription was activated."
        )
        subscription = Subscription.objects.get(user=self.tuab)
        payment = SubscriptionPayment.objects.get(subscription=subscription)
        self.assertEqual(subscription.status, 'ACTIVE')
        self.assertEqual(subscription.subscription_tier, 'PRO')
        self.assertEqual(payment.status, 'SUCCESS')
        self.assertEqual(payment.amount, Decimal('499.00'))
        self.assertEqual(
            payment.payment_reference,
            'e1aea1e2-ec95-492a-a5df-26ca85c0df09'
        )
        self.assertEqual(mocked_post.call_count, 1)
        charge_call = mocked_post.call_args
        self.assertEqual(
            charge_call.args[0],
            f'https://pg-sandbox.paymaya.com/payments/v1/customers/{self.tuab.maya_customer_id}/cards/{self.tuab.maya_card_id}/payments'
        )
        self.assertEqual(charge_call.kwargs['headers']['Authorization'], 'Basic test-secret')
        self.assertEqual(charge_call.kwargs['json']['cardId'], self.card_token_id)
        self.assertEqual(
            charge_call.kwargs['json']['requestReferenceNumber'],
            'e1aea1e2-ec95-492a-a5df-26ca85c0df09'
        )

    @override_settings(
        MAYA_SANDBOX_BASE_URL='https://pg-sandbox.paymaya.com/payments/v1',
        MAYA_SANDBOX_SECRET_BASIC_AUTH='Basic test-secret',
    )
    @patch('backend.services.subscription_service.requests.get')
    @patch('backend.services.subscription_service.requests.post')
    def test_duplicate_verification_webhook_does_not_create_duplicate_records(self, mocked_post, mocked_get):
        mocked_get.return_value = self.maya_response(200, {
            'id': 'e1aea1e2-ec95-492a-a5df-26ca85c0df09',
            'status': 'PAYMENT_SUCCESS',
        })
        mocked_post.return_value = self.maya_response(200, {
            'id': 'maya-charge-1',
            'isPaid': True,
            'status': 'PAYMENT_SUCCESS',
            'amount': '499',
            'currency': 'PHP',
        })

        first_response = self.client.post(
            reverse('webhooks'),
            self.webhook_payload,
            format='json',
            **self.webhook_headers()
        )
        second_response = self.client.post(
            reverse('webhooks'),
            self.webhook_payload,
            format='json',
            **self.webhook_headers()
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(Subscription.objects.filter(user=self.tuab).count(), 1)
        self.assertEqual(SubscriptionPayment.objects.count(), 1)
        self.assertEqual(mocked_post.call_count, 1)
        self.assertEqual(
            second_response.data['detail'],
            "Maya webhook ignored because the matched TUAB is already subscribed."
        )

    def test_lalamove_scaffold_branch_returns_placeholder_response(self):
        response = self.client.post(
            reverse('webhooks'),
            {"event": "delivery.update"},
            format='json',
            **self.webhook_headers('52.76.164.226')
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], "Missing signature verification details.")

    @override_settings(LALAMOVE_API_SECRET='test-secret')
    def test_lalamove_webhook_invalid_signature(self):
        response = self.client.post(
            reverse('webhooks'),
            {
                "signature": "invalid-signature",
                "timestamp": "1620000000000",
                "data": {"test": "data"}
            },
            format='json',
            **self.webhook_headers('52.76.164.226')
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['detail'], "Invalid Lalamove webhook signature.")

    @override_settings(LALAMOVE_API_SECRET='test-secret')
    def test_lalamove_webhook_valid_signature_ignored_event(self):
        import hmac
        import hashlib
        secret = 'test-secret'
        timestamp = '1620000000000'
        data_obj = {"test": "data"}
        message = f"{timestamp}\r\nPOST\r\n/api/webhooks\r\n\r\n{json.dumps(data_obj, separators=(',', ':'))}"
        signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

        response = self.client.post(
            reverse('webhooks'),
            {
                "signature": signature,
                "timestamp": timestamp,
                "data": data_obj,
                "eventType": "SOME_OTHER_EVENT"
            },
            format='json',
            **self.webhook_headers('52.76.164.226')
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], "Webhook event type SOME_OTHER_EVENT ignored.")


class UserArchiveAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="archive_admin@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639150000301",
            status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="archive_donor@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639150000302",
            status="ACTIVE",
            maya_customer_id="maya-customer-1",
            maya_card_id="maya-card-1"
        )
        self.tuab = User.objects.create_user(
            email="archive_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000303",
            status="ACTIVE",
            operational_status=UserOperationalStatus.ACTIVE,
            maya_customer_id="maya-customer-2",
            maya_card_id="maya-card-2"
        )

    def archive_headers(self, user):
        return {'HTTP_IF_MATCH': build_updated_at_etag(user)}

    def maya_response(self, status_code, payload):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        response.text = json.dumps(payload)
        return response

    def create_donation(self, donor, status_value, delivery_method='PICKUP', claimed_by_tuab=None):
        return Donation.objects.create(
            donor=donor,
            claimed_by_tuab=claimed_by_tuab,
            delivery_method=delivery_method,
            status=status_value,
            pickup_barangay='San Lorenzo',
            pickup_city='Makati',
            pickup_display_address='123 Main St',
            pickup_latitude=Decimal('14.5547'),
            pickup_longitude=Decimal('121.0244'),
            preferred_pickup_date='2026-05-10',
            preferred_pickup_window_start='09:00:00',
            preferred_pickup_window_end='12:00:00'
        )

    @patch('backend.services.user_archive_service.requests.delete')
    def test_admin_can_archive_donor_and_archive_related_records(self, mocked_delete):
        mocked_delete.return_value = self.maya_response(200, {'status': 'deleted'})
        pending = self.create_donation(self.donor, 'PENDING')
        claimed_pickup = self.create_donation(self.donor, 'CLAIMED', delivery_method='PICKUP')
        in_transit_pickup = self.create_donation(self.donor, 'IN_TRANSIT', delivery_method='PICKUP')
        claimed_pickup_2 = self.create_donation(self.donor, 'CLAIMED', delivery_method='PICKUP')
        received = self.create_donation(self.donor, 'RECEIVED')
        active_subscription = Subscription.objects.create(
            user=self.donor,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )
        cancelled_subscription = Subscription.objects.create(
            user=self.donor,
            status='CANCELLED',
            subscription_tier='FREE',
            start_date='2026-04-01T00:00:00Z',
            end_date='2026-05-01T00:00:00Z'
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            **self.archive_headers(self.donor)
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.donor.refresh_from_db()
        pending.refresh_from_db()
        claimed_pickup.refresh_from_db()
        in_transit_pickup.refresh_from_db()
        claimed_pickup_2.refresh_from_db()
        received.refresh_from_db()
        active_subscription.refresh_from_db()
        cancelled_subscription.refresh_from_db()

        self.assertEqual(self.donor.status, 'ARCHIVED')
        self.assertEqual(self.donor.maya_customer_id, 'maya-customer-1')
        self.assertIsNone(self.donor.maya_card_id)
        self.assertEqual(pending.status, 'ARCHIVED')
        self.assertEqual(claimed_pickup.status, 'ARCHIVED')
        self.assertEqual(in_transit_pickup.status, 'ARCHIVED')
        self.assertEqual(claimed_pickup_2.status, 'ARCHIVED')
        self.assertEqual(received.status, 'RECEIVED')
        self.assertEqual(active_subscription.status, 'CANCELLED')
        self.assertEqual(cancelled_subscription.status, 'CANCELLED')
        self.assertEqual(
            AuditTrail.objects.filter(
                actor=self.admin,
                entity_type='users',
                action='STATUS_CHANGE',
                fields_modified='["status","maya_card_id"]'
            ).count(),
            1
        )
        self.assertEqual(
            AuditTrail.objects.filter(
                actor=self.admin,
                entity_type='donations',
                action='STATUS_CHANGE',
                fields_modified='["status"]'
            ).count(),
            4
        )
        self.assertEqual(
            AuditTrail.objects.filter(
                actor=self.admin,
                entity_type='inventory_ledger',
                action='STATUS_CHANGE'
            ).count(),
            0
        )

    @patch('backend.services.user_archive_service.requests.delete')
    def test_admin_can_archive_tuab_without_changing_operational_status(self, mocked_delete):
        mocked_delete.return_value = self.maya_response(200, {'status': 'deleted'})
        claimed_pickup = self.create_donation(self.donor, 'CLAIMED', claimed_by_tuab=self.tuab)
        in_transit_pickup = self.create_donation(
            self.donor, 'IN_TRANSIT', claimed_by_tuab=self.tuab
        )
        claimed_delivery = self.create_donation(
            self.donor, 'CLAIMED', delivery_method='PICKUP', claimed_by_tuab=self.tuab
        )
        pending = self.create_donation(self.donor, 'PENDING', claimed_by_tuab=self.tuab)
        inventory_one = InventoryLedger.objects.create(
            source_donation=claimed_pickup,
            usage_amount_kg=Decimal('1.000'),
            weight_before_kg=Decimal('3.000'),
            current_weight_kg=Decimal('2.000'),
        )
        inventory_two = InventoryLedger.objects.create(
            source_donation=in_transit_pickup,
            usage_amount_kg=Decimal('0.500'),
            weight_before_kg=Decimal('2.500'),
            current_weight_kg=Decimal('2.000'),
        )
        inventory_three = InventoryLedger.objects.create(
            source_donation=claimed_delivery,
            usage_amount_kg=Decimal('0.250'),
            weight_before_kg=Decimal('1.250'),
            current_weight_kg=Decimal('1.000'),
        )
        already_archived_ledger = InventoryLedger.objects.create(
            source_donation=pending,
            usage_amount_kg=Decimal('0.125'),
            weight_before_kg=Decimal('0.625'),
            current_weight_kg=Decimal('0.500'),
            lifecycle_status='ARCHIVED',
            archived_at='2026-05-01T00:00:00Z',
        )
        active_subscription = Subscription.objects.create(
            user=self.tuab,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            reverse('user-detail', kwargs={'pk': self.tuab.user_id}),
            **self.archive_headers(self.tuab)
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.tuab.refresh_from_db()
        claimed_pickup.refresh_from_db()
        in_transit_pickup.refresh_from_db()
        claimed_delivery.refresh_from_db()
        pending.refresh_from_db()
        inventory_one.refresh_from_db()
        inventory_two.refresh_from_db()
        inventory_three.refresh_from_db()
        already_archived_ledger.refresh_from_db()
        active_subscription.refresh_from_db()

        self.assertEqual(self.tuab.status, 'ARCHIVED')
        self.assertEqual(self.tuab.operational_status, UserOperationalStatus.ACTIVE)
        self.assertEqual(self.tuab.maya_customer_id, 'maya-customer-2')
        self.assertIsNone(self.tuab.maya_card_id)
        self.assertEqual(claimed_pickup.status, 'PENDING')
        self.assertIsNone(claimed_pickup.claimed_by_tuab)
        self.assertIsNone(claimed_pickup.delivery_method)
        self.assertEqual(in_transit_pickup.status, 'PENDING')
        self.assertIsNone(in_transit_pickup.claimed_by_tuab)
        self.assertIsNone(in_transit_pickup.delivery_method)
        self.assertEqual(claimed_delivery.status, 'PENDING')
        self.assertIsNone(claimed_delivery.claimed_by_tuab)
        self.assertIsNone(claimed_delivery.delivery_method)
        self.assertEqual(pending.status, 'PENDING')
        self.assertEqual(pending.claimed_by_tuab_id, self.tuab.user_id)
        self.assertEqual(active_subscription.status, 'CANCELLED')
        self.assertEqual(inventory_one.lifecycle_status, 'ARCHIVED')
        self.assertTrue(inventory_one.was_forced_archived)
        self.assertIsNotNone(inventory_one.archived_at)
        self.assertEqual(inventory_two.lifecycle_status, 'ARCHIVED')
        self.assertTrue(inventory_two.was_forced_archived)
        self.assertIsNotNone(inventory_two.archived_at)
        self.assertEqual(inventory_three.lifecycle_status, 'ARCHIVED')
        self.assertTrue(inventory_three.was_forced_archived)
        self.assertIsNotNone(inventory_three.archived_at)
        self.assertEqual(already_archived_ledger.lifecycle_status, 'ARCHIVED')
        self.assertFalse(already_archived_ledger.was_forced_archived)
        self.assertEqual(
            str(already_archived_ledger.archived_at),
            '2026-05-01 00:00:00+00:00'
        )
        self.assertEqual(
            AuditTrail.objects.filter(
                actor=self.admin,
                entity_type='users',
                action='STATUS_CHANGE',
                fields_modified='["status","maya_card_id"]'
            ).count(),
            1
        )
        self.assertEqual(
            AuditTrail.objects.filter(
                actor=self.admin,
                entity_type='donations',
                action='STATUS_CHANGE',
                fields_modified='["status"]'
            ).count(),
            3
        )
        self.assertEqual(
            AuditTrail.objects.filter(
                actor=self.admin,
                entity_type='inventory_ledger',
                action='STATUS_CHANGE',
                fields_modified='["lifecycle_status","was_forced_archived","archived_at"]'
            ).count(),
            3
        )

    def test_archive_rejected_when_donor_has_delivery_in_transit(self):
        blocked_donation = self.create_donation(self.donor, 'IN_TRANSIT', delivery_method='DELIVERY')
        pending = self.create_donation(self.donor, 'PENDING')
        active_subscription = Subscription.objects.create(
            user=self.donor,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            **self.archive_headers(self.donor)
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn(
            "Archiving is not allowed while an associated delivery is in progress.",
            response.data['detail']
        )
        self.assertIn(
            str(blocked_donation.donation_id),
            response.data['detail']
        )
        self.donor.refresh_from_db()
        blocked_donation.refresh_from_db()
        pending.refresh_from_db()
        active_subscription.refresh_from_db()

        self.assertEqual(self.donor.status, 'ACTIVE')
        self.assertEqual(self.donor.maya_customer_id, 'maya-customer-1')
        self.assertEqual(self.donor.maya_card_id, 'maya-card-1')
        self.assertEqual(blocked_donation.status, 'IN_TRANSIT')
        self.assertEqual(pending.status, 'PENDING')
        self.assertEqual(active_subscription.status, 'ACTIVE')
        self.assertEqual(AuditTrail.objects.filter(actor=self.admin).count(), 0)

    @patch('backend.services.user_archive_service.requests.delete')
    def test_archive_fails_when_maya_card_delete_fails(self, mocked_delete):
        mocked_delete.return_value = self.maya_response(400, {'error': 'Cannot delete card'})
        active_subscription = Subscription.objects.create(
            user=self.tuab,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date='2026-05-01T00:00:00Z',
            end_date='2026-06-01T00:00:00Z'
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            reverse('user-detail', kwargs={'pk': self.tuab.user_id}),
            **self.archive_headers(self.tuab)
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Maya card deletion failed", response.data['detail'])
        self.tuab.refresh_from_db()
        active_subscription.refresh_from_db()
        self.assertEqual(self.tuab.status, 'ACTIVE')
        self.assertEqual(self.tuab.maya_customer_id, 'maya-customer-2')
        self.assertEqual(self.tuab.maya_card_id, 'maya-card-2')
        self.assertEqual(active_subscription.status, 'ACTIVE')

    def test_archive_requires_if_match_header(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(reverse('user-detail', kwargs={'pk': self.donor.user_id}))

        self.assertEqual(response.status_code, status.HTTP_428_PRECONDITION_REQUIRED)
        self.assertEqual(response.data['detail'], "If-Match header is required.")

    def test_archive_rejects_stale_if_match_header(self):
        stale_etag = build_updated_at_etag(self.donor)
        self.donor.first_name = 'Updated elsewhere'
        self.donor.save(update_fields=['first_name', 'updated_at'])

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            HTTP_IF_MATCH=stale_etag
        )

        self.assertEqual(response.status_code, status.HTTP_412_PRECONDITION_FAILED)
        self.assertEqual(response.data['detail'], "ETag does not match the current resource version.")

    def test_archive_forbidden_for_non_admin(self):
        self.client.force_authenticate(user=self.donor)
        response = self.client.delete(reverse('user-detail', kwargs={'pk': self.tuab.user_id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_archive_rejects_admin_target(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            reverse('user-detail', kwargs={'pk': self.admin.user_id}),
            **self.archive_headers(self.admin)
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data['detail'],
            "Admin users cannot be archived through this endpoint."
        )

    def test_archive_is_idempotent_for_archived_user(self):
        self.donor.status = 'ARCHIVED'
        self.donor.save(update_fields=['status'])

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            reverse('user-detail', kwargs={'pk': self.donor.user_id}),
            **self.archive_headers(self.donor)
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], "This user is already archived.")
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.status, 'ARCHIVED')
        self.assertEqual(AuditTrail.objects.filter(actor=self.admin).count(), 0)


class UserArchiveServiceTest(TestCase):
    def setUp(self):
        self.donor = User.objects.create_user(
            email="service_donor@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639150000351",
            status="ACTIVE"
        )
        self.tuab = User.objects.create_user(
            email="service_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000352",
            status="ACTIVE",
            operational_status=UserOperationalStatus.ACTIVE
        )

    def create_donation(self, donor, status_value, delivery_method='PICKUP', claimed_by_tuab=None):
        return Donation.objects.create(
            donor=donor,
            claimed_by_tuab=claimed_by_tuab,
            delivery_method=delivery_method,
            status=status_value,
            pickup_barangay='San Lorenzo',
            pickup_city='Makati',
            pickup_display_address='123 Main St',
            pickup_latitude=Decimal('14.5547'),
            pickup_longitude=Decimal('121.0244'),
            preferred_pickup_date='2026-05-10',
            preferred_pickup_window_start='09:00:00',
            preferred_pickup_window_end='12:00:00'
        )

    def test_archive_user_handles_donor_mixed_statuses(self):
        pending = self.create_donation(self.donor, 'PENDING')
        claimed_pickup = self.create_donation(self.donor, 'CLAIMED', delivery_method='PICKUP')
        in_transit_pickup = self.create_donation(self.donor, 'IN_TRANSIT', delivery_method='PICKUP')
        claimed_delivery = self.create_donation(self.donor, 'CLAIMED', delivery_method='PICKUP')
        received = self.create_donation(self.donor, 'RECEIVED')

        result = archive_user(target_user_id=self.donor.user_id)

        self.assertEqual(result["status_code"], 204)
        self.assertIsNone(result["detail"])
        pending.refresh_from_db()
        claimed_pickup.refresh_from_db()
        in_transit_pickup.refresh_from_db()
        claimed_delivery.refresh_from_db()
        received.refresh_from_db()
        self.donor.refresh_from_db()
        self.assertEqual(pending.status, 'ARCHIVED')
        self.assertEqual(claimed_pickup.status, 'ARCHIVED')
        self.assertEqual(in_transit_pickup.status, 'ARCHIVED')
        self.assertEqual(claimed_delivery.status, 'ARCHIVED')
        self.assertEqual(received.status, 'RECEIVED')
        self.assertEqual(self.donor.status, 'ARCHIVED')
        self.assertEqual(len(result["changed_donations"]), 4)
        self.assertEqual(result["changed_inventory_ledgers"], [])
        self.assertTrue(result["user_updated"])

    def test_unclaim_tuab_donations_clears_expected_fields(self):
        claimed_pickup = self.create_donation(
            self.donor, 'CLAIMED', delivery_method='PICKUP', claimed_by_tuab=self.tuab
        )
        in_transit_pickup = self.create_donation(
            self.donor, 'IN_TRANSIT', delivery_method='PICKUP', claimed_by_tuab=self.tuab
        )
        claimed_delivery = self.create_donation(
            self.donor, 'CLAIMED', delivery_method='PICKUP', claimed_by_tuab=self.tuab
        )
        untouched = self.create_donation(
            self.donor, 'PENDING', delivery_method='PICKUP', claimed_by_tuab=self.tuab
        )

        result = unclaim_tuab_donations(tuab=self.tuab)

        self.assertEqual(result["status_code"], 204)
        self.assertIsNone(result["detail"])
        claimed_pickup.refresh_from_db()
        in_transit_pickup.refresh_from_db()
        claimed_delivery.refresh_from_db()
        untouched.refresh_from_db()
        for donation in (claimed_pickup, in_transit_pickup, claimed_delivery):
            self.assertEqual(donation.status, 'PENDING')
            self.assertIsNone(donation.claimed_by_tuab)
            self.assertIsNone(donation.delivery_method)
        self.assertEqual(untouched.status, 'PENDING')
        self.assertEqual(untouched.claimed_by_tuab_id, self.tuab.user_id)
        self.assertEqual(len(result["changed_donations"]), 3)

    def test_unclaim_tuab_donations_blocks_delivery_in_transit(self):
        blocked = self.create_donation(
            self.donor, 'IN_TRANSIT', delivery_method='DELIVERY', claimed_by_tuab=self.tuab
        )
        claimable = self.create_donation(
            self.donor, 'CLAIMED', delivery_method='PICKUP', claimed_by_tuab=self.tuab
        )

        result = unclaim_tuab_donations(tuab=self.tuab)

        self.assertEqual(result["status_code"], 409)
        self.assertEqual(
            result["detail"],
            "Archiving is not allowed while an associated delivery is in progress."
        )
        blocked.refresh_from_db()
        claimable.refresh_from_db()
        self.assertEqual(blocked.status, 'IN_TRANSIT')
        self.assertEqual(blocked.claimed_by_tuab_id, self.tuab.user_id)
        self.assertEqual(claimable.status, 'CLAIMED')
        self.assertEqual(claimable.claimed_by_tuab_id, self.tuab.user_id)
        self.assertEqual(result["changed_donations"], [])


class AuditServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="audit_service@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639150000401",
            status="ACTIVE"
        )

    def test_log_audit_serializes_fields_modified_as_json_array(self):
        audit = log_audit(
            actor=self.user,
            entity_type='users',
            action='CREDENTIAL_UPDATE',
            fields_modified=['first_name', 'last_name', 'contact_no']
        )

        self.assertEqual(
            audit.fields_modified,
            json.dumps(['first_name', 'last_name', 'contact_no'], separators=(',', ':'))
        )

    def test_log_audit_truncates_long_serialized_fields_modified(self):
        field_names = [f'field_name_number_{index}' for index in range(8)]
        serialized_fields = json.dumps(field_names, separators=(',', ':'))
        self.assertGreater(len(serialized_fields), 100)

        audit = log_audit(
            actor=self.user,
            entity_type='users',
            action='CREDENTIAL_UPDATE',
            fields_modified=field_names
        )

        self.assertEqual(audit.fields_modified, serialized_fields[:97] + '...')
        self.assertEqual(len(audit.fields_modified), 100)


class DonationAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin_don@example.com", password="Pass", role="Admin", contact_no="+639003", status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="donor_don@example.com", password="Pass", role="Donor", contact_no="+639004", status="ACTIVE"
        )
        self.tuab = User.objects.create_user(
            email="tuab_don@example.com", password="Pass", role="TUAB", contact_no="+639005", status="ACTIVE"
        )
        
        # Create a donation
        self.donation = Donation.objects.create(
            donor=self.donor,
            delivery_method='PICKUP',
            status='PENDING',
            pickup_barangay='San Lorenzo',
            pickup_city='Makati',
            pickup_display_address='123 Main St',
            pickup_latitude=Decimal('14.5547'),
            pickup_longitude=Decimal('121.0244'),
            preferred_pickup_date='2026-05-10',
            preferred_pickup_window_start='09:00:00',
            preferred_pickup_window_end='12:00:00'
        )

    def test_donation_list_visibility(self):
        # Admin sees all (including potentially archived if we added a check, but currently all non-archived)
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('donation-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        # Donor sees all (public feed)
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('donation-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_donation_me_filtering(self):
        # Create another donation for someone else
        other_donor = User.objects.create_user(email="other@ex.com", password="P", role="Donor", contact_no="+63999")
        Donation.objects.create(
            donor=other_donor, 
            delivery_method='DELIVERY', 
            status='PENDING',
            pickup_barangay='Legazpi',
            pickup_city='Makati',
            pickup_display_address='456 Oak St',
            pickup_latitude=Decimal('14.5500'),
            pickup_longitude=Decimal('121.0200'),
            preferred_pickup_date='2026-05-11',
            preferred_pickup_window_start='13:00:00',
            preferred_pickup_window_end='16:00:00'
        )

        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('donation-me'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Should only see 1 donation (theirs)
        self.assertEqual(len(res.data['results']), 1)
        self.assertEqual(res.data['results'][0]['donation_id'], self.donation.donation_id)

    def test_archived_donations_excluded_for_non_admin(self):
        self.donation.status = 'ARCHIVED'
        self.donation.save()
        
        # Donor should NOT see archived donations
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('donation-list'))
        self.assertEqual(res.data['count'], 0)

class PredictionServiceTest(TestCase):
    def setUp(self):
        self.donor = User.objects.create_user(
            email="prediction_donor@test.com", password="Password123", role="Donor", contact_no="+639019991", status="ACTIVE"
        )
        self.tuab_multi = User.objects.create_user(
            email="prediction_multi@test.com", password="Password123", role="TUAB", contact_no="+639019992", status="ACTIVE",
            operational_status=UserOperationalStatus.ACTIVE, target_fibers="cotton,polyester",
            latitude=Decimal('14.5'), longitude=Decimal('121.0'),
            min_biodeg_score=0, max_distance_km=100
        )
        # Add active PRO subscription for matching
        Subscription.objects.create(
            user=self.tuab_multi,
            status=SubscriptionStatus.ACTIVE,
            subscription_tier=SubscriptionTier.PRO,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30)
        )
        # Use real lookup data if available, fallback only if empty
        self.lookup_cotton = BrandFiberLookup.objects.filter(fiber_json__contains='cotton').first()
        if not self.lookup_cotton:
            self.lookup_cotton = BrandFiberLookup.objects.create(
                brand="BrandA", clothing_type="T-shirt", 
                fiber_json='{"cotton": 100.0}', biodeg_score=100.0, dominant_fiber="cotton"
            )
            
        self.lookup_poly = BrandFiberLookup.objects.filter(fiber_json__contains='polyester').first()
        if not self.lookup_poly:
            self.lookup_poly = BrandFiberLookup.objects.create(
                brand="BrandB", clothing_type="Shirt", 
                fiber_json='{"polyester": 100.0}', biodeg_score=0.0, dominant_fiber="polyester"
            )

    def test_multi_fiber_matching(self):
        # Create donation with two items (one cotton, one poly)
        donation = Donation.objects.create(
            donor=self.donor, pickup_barangay='B', pickup_city='C', pickup_display_address='D',
            pickup_latitude=Decimal('14.5'), pickup_longitude=Decimal('121.0'),
            preferred_pickup_date='2026-05-10', preferred_pickup_window_start='09:00:00',
            preferred_pickup_window_end='12:00:00'
        )
        DonationItem.objects.create(donation=donation, lookup=self.lookup_cotton, condition_rating='GOOD', weight_kg=1.0)
        DonationItem.objects.create(donation=donation, lookup=self.lookup_poly, condition_rating='GOOD', weight_kg=1.0)

        # Run prediction
        preds = run_predictions_for_donation(donation.donation_id)
        
        # Should have only the top prediction for our TUAB
        tuab_preds = [p for p in preds if p.tuab_id == self.tuab_multi.user_id]
        self.assertEqual(len(tuab_preds), 1)
        
        # It should be a match
        p = tuab_preds[0]
        self.assertTrue(p.is_match)
        self.assertGreater(p.match_prob, 0.8)

    def test_distance_constraint(self):
        # Create a TUAB with a very small radius (1km)
        tuab_close = User.objects.create_user(
            email="close@test.com", password="Password123", role="TUAB", contact_no="+639019993", status="ACTIVE",
            operational_status=UserOperationalStatus.ACTIVE, target_fibers="cotton",
            latitude=Decimal('14.5'), longitude=Decimal('121.0'),
            min_biodeg_score=0, max_distance_km=1           # 1km radius
        )
        Subscription.objects.create(
            user=tuab_close,
            status=SubscriptionStatus.ACTIVE,
            subscription_tier=SubscriptionTier.PRO,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30)
        )
        # Create a donation far away (~50km)
        donation_far = Donation.objects.create(
            donor=self.donor, pickup_barangay='Far', pickup_city='C', pickup_display_address='D',
            pickup_latitude=Decimal('15.0'), pickup_longitude=Decimal('121.0'), # ~55km away
            preferred_pickup_date='2026-05-10', preferred_pickup_window_start='09:00:00',
            preferred_pickup_window_end='12:00:00'
        )
        DonationItem.objects.create(donation=donation_far, lookup=self.lookup_cotton, condition_rating='GOOD', weight_kg=1.0)
        
        preds = run_predictions_for_donation(donation_far.donation_id)
        tuab_preds = [p for p in preds if p.tuab_id == tuab_close.user_id]
        
        # Should NOT be a match due to distance (returns empty because it's below threshold)
        self.assertEqual(len(tuab_preds), 0)

    def test_biodeg_constraint(self):
        # Create a TUAB with a high biodeg requirement (90)
        tuab_strict = User.objects.create_user(
            email="strict@test.com", password="Password123", role="TUAB", contact_no="+639019994", status="ACTIVE",
            operational_status=UserOperationalStatus.ACTIVE, target_fibers="polyester",
            latitude=Decimal('14.5'), longitude=Decimal('121.0'),
            min_biodeg_score=90, max_distance_km=100
        )
        Subscription.objects.create(
            user=tuab_strict,
            status=SubscriptionStatus.ACTIVE,
            subscription_tier=SubscriptionTier.PRO,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30)
        )
        # Polyester item has biodeg_score 0 (from setUp)
        donation = Donation.objects.create(
            donor=self.donor, pickup_barangay='B', pickup_city='C', pickup_display_address='D',
            pickup_latitude=Decimal('14.5'), pickup_longitude=Decimal('121.0'),
            preferred_pickup_date='2026-05-10', preferred_pickup_window_start='09:00:00',
            preferred_pickup_window_end='12:00:00'
        )
        DonationItem.objects.create(donation=donation, lookup=self.lookup_poly, condition_rating='GOOD', weight_kg=1.0)
        
        preds = run_predictions_for_donation(donation.donation_id)
        tuab_preds = [p for p in preds if p.tuab_id == tuab_strict.user_id]
        
        # Should NOT be a match because polyester (0) < requirement (90) (returns empty because it's below threshold)
        self.assertEqual(len(tuab_preds), 0)

    def test_model_unavailable(self):
        from unittest.mock import patch
        from backend.services.prediction_service import MatchPredictionService
        
        # Reset any loaded model first to force reload
        original_model = MatchPredictionService._model
        MatchPredictionService._model = None
        
        try:
            # Patch builtins.open to raise FileNotFoundError, simulating missing model/metadata files
            with patch('builtins.open', side_effect=FileNotFoundError):
                with self.assertRaises(ValueError) as ctx:
                    MatchPredictionService.load_model()
                self.assertEqual(str(ctx.exception), "Prediction model is unavailable.")
        finally:
            # Restore
            MatchPredictionService._model = original_model


class DonationQuotationClaimAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.donor = User.objects.create_user(
            email="quote_donor@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639150000401",
            status="ACTIVE",
            first_name="Juan",
            last_name="Dela Cruz",
        )
        self.tuab = User.objects.create_user(
            email="quote_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639150000402",
            status="ACTIVE",
            operational_status=UserOperationalStatus.ACTIVE,
            first_name="Mina",
            last_name="Lopez",
            display_address="123 TUAB Street, Quezon City",
            latitude=Decimal('14.6500000'),
            longitude=Decimal('121.0500000'),
            maya_customer_id="maya-customer-1",
            maya_card_id="maya-card-1",
            max_active_claims=3,
        )
        Subscription.objects.create(
            user=self.tuab,
            status='ACTIVE',
            subscription_tier='PRO',
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30),
        )
        self.donation = Donation.objects.create(
            donor=self.donor,
            pickup_barangay='San Lorenzo',
            pickup_city='Makati',
            pickup_display_address='123 Main St, Makati',
            pickup_latitude=Decimal('14.5547000'),
            pickup_longitude=Decimal('121.0244000'),
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start='09:00:00',
            preferred_pickup_window_end='12:00:00',
        )

    def quotation_headers(self):
        return {'HTTP_IF_MATCH': build_updated_at_etag(self.donation)}

    def make_http_response(self, status_code, payload):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        response.text = json.dumps(payload)
        return response

    def expected_schedule_at(self, pickup_time=None):
        pickup_start = pickup_time or self.donation.preferred_pickup_window_start
        if isinstance(pickup_start, str):
            pickup_start = datetime.strptime(pickup_start, '%H:%M:%S').time()
        
        # --- MANILA-FIRST LOCALIZATION (MATCHES VIEW LOGIC) ---
        schedule_at = timezone.localtime(self.donation.preferred_pickup_date).replace(
            hour=pickup_start.hour,
            minute=pickup_start.minute,
            second=pickup_start.second,
            microsecond=0,
        )
        return schedule_at.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    @patch('backend.views.donations.get_lalamove_quotation')
    def test_donation_quotation_returns_signed_token_and_quote_payload(self, mocked_quote):
        mocked_quote.return_value = {
            "data": {
                "quotationId": "Q-123",
                "stops": [
                    {"stopId": "S1"},
                    {"stopId": "S2"},
                ],
                "priceBreakdown": {"total": 375.5},
                "expiresAt": "2026-05-20T12:00:00Z",
            }
        }

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-quotation', kwargs={'pk': self.donation.donation_id}),
            {
                "dropoff_address": "123 TUAB Street, Quezon City",
                "dropoff_lat": "14.6500000",
                "dropoff_lng": "121.0500000",
                "scheduled_time": "10:30",
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['quotationId'], 'Q-123')
        self.assertEqual(response.data['total_price'], 375.5)
        self.assertEqual(response.data['schedule_at'], self.expected_schedule_at('10:30:00'))
        self.assertIn('quotation_token', response.data)
        self.assertIn('.', response.data['quotation_token'])
        mocked_quote.assert_called_once()
        self.assertEqual(mocked_quote.call_args.kwargs['schedule_at'], self.expected_schedule_at('10:30:00'))

    def test_donation_quotation_rejects_stale_if_match_header(self):
        stale_etag = '"etag-stale"'

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-quotation', kwargs={'pk': self.donation.donation_id}),
            {
                "dropoff_address": "123 TUAB Street, Quezon City",
                "dropoff_lat": "14.6500000",
                "dropoff_lng": "121.0500000",
                "scheduled_time": "10:30",
            },
            format='json',
            HTTP_IF_MATCH=stale_etag,
        )

        self.assertEqual(response.status_code, status.HTTP_412_PRECONDITION_FAILED)
        self.assertEqual(response.data['detail'], "ETag does not match the current resource version.")

    def test_donation_quotation_rejects_invalid_coordinates(self):
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-quotation', kwargs={'pk': self.donation.donation_id}),
            {
                "dropoff_address": "123 TUAB Street, Quezon City",
                "dropoff_lat": "14.65",
                "dropoff_lng": "121.0500000",
                "scheduled_time": "10:30",
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('dropoff_lat', response.data)

    def test_donation_quotation_rejects_scheduled_time_outside_window(self):
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-quotation', kwargs={'pk': self.donation.donation_id}),
            {
                "dropoff_address": "123 TUAB Street, Quezon City",
                "dropoff_lat": "14.6500000",
                "dropoff_lng": "121.0500000",
                "scheduled_time": "08:30",
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['scheduled_time'][0],
            "Scheduled time must be within the donation's preferred pickup window.",
        )

    def test_donation_quotation_rejects_when_pickup_window_has_already_passed(self):
        fixed_now = timezone.make_aware(datetime(2026, 5, 20, 13, 0, 0))
        self.donation.preferred_pickup_date = fixed_now.replace(hour=0, minute=0, second=0, microsecond=0)
        self.donation.preferred_pickup_window_start = '09:00:00'
        self.donation.preferred_pickup_window_end = '12:00:00'
        self.donation.save()

        self.client.force_authenticate(user=self.tuab)
        with patch('backend.views.donations.timezone.now', return_value=fixed_now):
            response = self.client.post(
                reverse('donation-quotation', kwargs={'pk': self.donation.donation_id}),
                {
                    "dropoff_address": "123 TUAB Street, Quezon City",
                    "dropoff_lat": "14.6500000",
                    "dropoff_lng": "121.0500000",
                    "scheduled_time": "10:30",
                },
                format='json',
                **self.quotation_headers(),
            )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data['detail'],
            "This donation's preferred pickup window has already passed. Delivery can no longer be scheduled.",
        )

    def test_donation_claim_succeeds_for_pickup(self):
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {
                "delivery_method": "PICKUP",
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, 'CLAIMED')
        self.assertEqual(self.donation.delivery_method, 'PICKUP')
        self.assertEqual(self.donation.claimed_by_tuab_id, self.tuab.user_id)

    @patch('backend.services.claim_donation_service.requests.post')
    @patch('backend.services.claim_donation_service.requests.delete')
    @patch('backend.views.donations.get_lalamove_quotation')
    def test_donation_claim_succeeds_for_delivery_with_signed_token(self, mocked_quote, mocked_delete, mocked_post):
        mocked_quote.return_value = {
            "data": {
                "quotationId": "Q-123",
                "stops": [
                    {"stopId": "S1"},
                    {"stopId": "S2"},
                ],
                "priceBreakdown": {"total": 375.5},
                "expiresAt": "2026-05-20T12:00:00Z",
            }
        }
        mocked_post.side_effect = [
            self.make_http_response(200, {"status": "PAYMENT_SUCCESS", "id": "maya-payment-1"}),
            self.make_http_response(201, {"data": {"orderId": "lalamove-order-1"}}),
        ]

        self.client.force_authenticate(user=self.tuab)
        quote_response = self.client.post(
            reverse('donation-quotation', kwargs={'pk': self.donation.donation_id}),
            {
                "dropoff_address": "123 TUAB Street, Quezon City",
                "dropoff_lat": "14.6500000",
                "dropoff_lng": "121.0500000",
                "scheduled_time": "10:30",
            },
            format='json',
            **self.quotation_headers(),
        )
        self.assertEqual(quote_response.status_code, status.HTTP_200_OK)
        self.assertEqual(quote_response.data['schedule_at'], self.expected_schedule_at('10:30:00'))

        claim_response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {
                "delivery_method": "DELIVERY",
                "quotation_token": quote_response.data['quotation_token'],
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(claim_response.status_code, status.HTTP_200_OK)
        self.assertEqual(claim_response.data['lalamove_order_id'], 'lalamove-order-1')
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, 'CLAIMED')
        self.assertEqual(self.donation.delivery_method, 'DELIVERY')
        self.assertEqual(self.donation.claimed_by_tuab_id, self.tuab.user_id)
        order = self.donation.orders.get()
        expected_scheduled_at = parse_datetime(self.expected_schedule_at('10:30:00'))
        self.assertEqual(order.scheduled_at.isoformat().replace('+00:00', 'Z'), self.expected_schedule_at('10:30:00'))
        self.assertEqual(
            order.expires_at.isoformat().replace('+00:00', 'Z'),
            (expected_scheduled_at + timedelta(hours=2)).isoformat().replace('+00:00', 'Z'),
        )
        mocked_delete.assert_not_called()

    def test_donation_claim_rejects_missing_quotation_token(self):
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {
                "delivery_method": "DELIVERY",
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], "Malformed or expired quotation token.")

    def test_donation_claim_rejects_expired_quotation_token(self):
        expired_token = sign_quotation_data({
            "amount": 375.5,
            "quotationId": "Q-123",
            "stopId_1": "S1",
            "stopId_2": "S2",
            "schedule_at": "2026-05-20T01:00:00Z",
            "expires_at": int(timezone.now().timestamp()) - 60,
        })

        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {
                "delivery_method": "DELIVERY",
                "quotation_token": expired_token,
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], "Quotation has expired.")

    def test_donation_claim_rejects_non_tuab(self):
        self.client.force_authenticate(user=self.donor)
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {"delivery_method": "PICKUP"},
            format='json',
            **self.quotation_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], "Only registered businesses can claim donations.")

    def test_donation_claim_rejects_missing_etag(self):
        self.client.force_authenticate(user=self.tuab)
        headers = self.quotation_headers()
        headers.pop('HTTP_IF_MATCH', None)  # Remove ETag header
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {"delivery_method": "PICKUP"},
            format='json',
            **headers,
        )
        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.data['detail'], "If-Match header is required.")

    def test_donation_claim_rejects_mismatched_etag(self):
        self.client.force_authenticate(user=self.tuab)
        headers = self.quotation_headers()
        headers['HTTP_IF_MATCH'] = '"invalid-etag"'
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {"delivery_method": "PICKUP"},
            format='json',
            **headers,
        )
        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.data['detail'], "ETag does not match the current resource version.")

    def test_donation_claim_rejects_inactive_pro_subscription(self):
        # Cancel or delete the PRO subscription for the TUAB user
        Subscription.objects.filter(user=self.tuab).delete()
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {"delivery_method": "DELIVERY"},
            format='json',
            **self.quotation_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error'], "SUBSCRIPTION_INACTIVE")
        self.assertEqual(response.data['detail'], "An active PRO subscription is required to claim donations.")

    def test_donation_claim_succeeds_for_pickup_without_pro_subscription(self):
        # Remove the PRO subscription to simulate a non-pro TUAB
        Subscription.objects.filter(user=self.tuab).delete()
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {
                "delivery_method": "PICKUP",
            },
            format='json',
            **self.quotation_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, 'CLAIMED')
        self.assertEqual(self.donation.delivery_method, 'PICKUP')
        self.assertEqual(self.donation.claimed_by_tuab_id, self.tuab.user_id)

    def test_donation_claim_rejects_invalid_delivery_method(self):
        self.client.force_authenticate(user=self.tuab)
        response = self.client.post(
            reverse('donation-claim', kwargs={'pk': self.donation.donation_id}),
            {"delivery_method": "INVALID"},
            format='json',
            **self.quotation_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], "Invalid delivery_method. Must be 'PICKUP' or 'DELIVERY'.")


