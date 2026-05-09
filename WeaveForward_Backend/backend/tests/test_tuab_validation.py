from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from backend.models import User, BrandFiberLookup
from backend.services.etag_service import build_updated_at_etag

class TUABUpdateValidationTest(TestCase):
    def setUp(self):
        # Create allowed fibers in DB for validation
        BrandFiberLookup.objects.create(
            category="Test", brand="Test", clothing_type="Test",
            fiber_json='{"cotton": 100, "wool": 100, "denim": 100}',
            is_active=True
        )
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="Password123", role="Admin", contact_no="+639000000000", status="ACTIVE"
        )
        self.tuab = User.objects.create_user(
            email="tuab@example.com", 
            password="Password123", 
            role="TUAB", 
            contact_no="+639181234567", 
            status="ACTIVE",
            business_name="Initial Name",
            description="Initial Description",
            social_link="http://initial.com",
            max_active_claims=3,
            max_distance_km=Decimal('10.00'),
            min_biodeg_score=Decimal('60.00'),
            target_fibers="cotton"
        )
        self.client.force_authenticate(user=self.admin)
        self.url = reverse('user-detail', kwargs={'pk': self.tuab.user_id})
        self.etag = build_updated_at_etag(self.tuab)

    def test_tuab_patch_enforces_mandatory_fields_not_blank(self):
        # Attempt to blank out mandatory fields
        payload = {
            "business_name": "",
            "description": " ",
            "social_link": ""
        }
        response = self.client.patch(self.url, payload, format='json', HTTP_IF_MATCH=self.etag)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('business_name', data)
        self.assertIn('description', data)
        self.assertIn('social_link', data)

    def test_tuab_patch_rejects_unauthorized_fields(self):
        # Attempt to change role or email which are NOT in the whitelist
        payload = {
            "role": "Admin",
            "email": "new@example.com",
            "maya_customer_id": "hacker_id",
            "first_name": "NewFirst",
            "last_name": "NewLast"
        }
        response = self.client.patch(self.url, payload, format='json', HTTP_IF_MATCH=self.etag)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        
        # All these should be rejected by the whitelist or blocked fields
        self.assertIn('role', data)
        self.assertIn('maya_customer_id', data)
        self.assertIn('email', data)
        self.assertIn('first_name', data)
        self.assertIn('last_name', data)

    def test_tuab_patch_allows_whitelisted_fields(self):
        payload = {
            "business_name": "Updated Business",
            "max_active_claims": 5,
            "target_fibers": "wool,denim"
        }
        response = self.client.patch(self.url, payload, format='json', HTTP_IF_MATCH=self.etag)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tuab.refresh_from_db()
        self.assertEqual(self.tuab.business_name, "Updated Business")
        self.assertEqual(self.tuab.max_active_claims, 5)
        self.assertEqual(self.tuab.target_fibers, "wool,denim")
