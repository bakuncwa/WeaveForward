from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from .models import User, Upload
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
