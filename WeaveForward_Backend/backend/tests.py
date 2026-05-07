from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from .models import User, Upload, Donation, DonationItem, BrandFiberLookup
from .serializers import DonorRegisterSerializer, TUABRegisterSerializer

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
            'confirm_password': 'Password123',
            'latitude': '14.5995120',
            'longitude': '120.9842220',
            'display_address': 'Manila'
        }

    def test_valid_donor_registration(self):
        response = self.client.post(reverse('register'), self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='juan@example.com').exists())

    def test_password_mismatch(self):
        payload = self.valid_payload.copy()
        payload['confirm_password'] = 'Mismatch123'
        response = self.client.post(reverse('register'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.json())

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
        self.valid_payload = {
            'role': 'TUAB',
            'business_name': 'Recycle Co',
            'email': 'tuab@example.com',
            'contact_no': '+639181234567',
            'password': 'Password123',
            'confirm_password': 'Password123',
            'latitude': '14.5995120',
            'longitude': '120.9842220',
            'display_address': 'Manila',
            'target_fibers': 'cotton,wool',
            'max_distance_km': '50.00',
            'min_biodeg_score': '70.00'
        }

    def test_valid_tuab_registration(self):
        response = self.client.post(reverse('register'), self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='tuab@example.com')
        self.assertEqual(user.role, 'TUAB')
        self.assertEqual(user.status, 'UNDER_REVIEW')

    def test_invalid_fibers(self):
        payload = self.valid_payload.copy()
        payload['target_fibers'] = 'cotton,adamantium'
        response = self.client.post(reverse('register'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('target_fibers', response.json())

    def test_fiber_formatting(self):
        payload = self.valid_payload.copy()
        payload['target_fibers'] = 'Cotton, wool'
        response = self.client.post(reverse('register'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('target_fibers', response.json())

    def test_duplicate_email(self):
        self.client.post(reverse('register'), self.valid_payload, format='json')
        response = self.client.post(reverse('register'), self.valid_payload, format='json')
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
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['role'], "Donor")
        self.assertEqual(response.data['name'], "John Doe")

    def test_login_blocked_if_not_active(self):
        self.user.status = "UNDER_REVIEW"
        self.user.save()
        response = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_success(self):
        # Login to get tokens
        login_res = self.client.post(self.login_url, {
            "email": "tester@example.com",
            "password": self.password
        }, format='json')
        access = login_res.data['access']
        refresh = login_res.data['refresh']

        # Call logout
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        response = self.client.post(self.logout_url, {"refresh": refresh}, format='json')
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)
        self.assertEqual(response.data['message'], "Successfully logged out")

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

    def test_password_reset_flow(self):
        # 1. Request reset (This will now send a REAL email to you)
        response = self.client.post(self.request_url, {'email': self.email}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], "Password reset email sent.")

        # 2. Generate token (simulating what would be in the email)
        from .services.auth_service import generate_reset_token
        uidb64, token = generate_reset_token(self.user)

        # 3. Confirm reset
        new_pw = "NewSecret123"
        confirm_payload = {
            'uidb64': uidb64,
            'token': token,
            'new_password': new_pw,
            'confirm_password': new_pw
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

class UserAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin_test@example.com", password="Pass", role="Admin", contact_no="+639001", status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="donor_test@example.com", password="Pass", role="Donor", contact_no="+639002", status="ACTIVE"
        )

    def test_user_list_admin_only(self):
        # Admin can list
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('user-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        # Donor blocked
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('user-list'))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_retrieve_logic(self):
        # Donor can see self
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.donor.user_id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Donor cannot see admin
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.admin.user_id}))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Admin can see donor
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('user-detail', kwargs={'pk': self.donor.user_id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_user_me_shortcut(self):
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('user-me'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['email'], self.donor.email)

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
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['donation_id'], self.donation.donation_id)

    def test_archived_donations_excluded_for_non_admin(self):
        self.donation.status = 'ARCHIVED'
        self.donation.save()
        
        # Donor should NOT see archived donations
        self.client.force_authenticate(user=self.donor)
        res = self.client.get(reverse('donation-list'))
        self.assertEqual(len(res.data), 0)
