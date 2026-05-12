from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
import json
from ..models import User, Donation, DonationItem, BrandFiberLookup, Upload, AuditTrail

class DonationCreationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Create users
        self.admin = User.objects.create_user(
            email="admin_don@example.com", 
            password="Password123", 
            role="Admin", 
            contact_no="+639000000001", 
            status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="donor_don@example.com", 
            password="Password123", 
            role="Donor", 
            contact_no="+639000000002", 
            status="ACTIVE"
        )
        # Create lookup data
        self.lookup = BrandFiberLookup.objects.create(
            category="Jeans", 
            brand="Levi's", 
            clothing_type="Pants", 
            fiber_json='{"cotton": 100}'
        )
        self.client.force_authenticate(user=self.admin)

    def test_create_donation_success(self):
        items = [
            {"lookup_id": self.lookup.lookup_id, "weight_kg": 1.5, "condition_rating": "Good"},
            {"lookup_id": self.lookup.lookup_id, "weight_kg": 0.8, "condition_rating": "Like New"}
        ]
        payload = {
            "donor_user_id": self.donor.user_id,
            "items": json.dumps(items),
            "preferred_pickup_date": "2026-06-01T10:00:00Z",
            "preferred_pickup_window_start": "10:00:00",
            "preferred_pickup_window_end": "12:00:00",
            "pickup_display_address": "De La Salle-College of Saint Benilde, Manila",
            "pickup_latitude": "14.5645000",
            "pickup_longitude": "120.9930000",
        }
        
        response = self.client.post(reverse('donation-list'), payload, format='multipart')
        
        if response.status_code != status.HTTP_201_CREATED:
            print(response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Donation.objects.count(), 1)
        self.assertEqual(DonationItem.objects.count(), 2)
        
        donation = Donation.objects.first()
        self.assertEqual(donation.donor, self.donor)
        self.assertEqual(donation.pickup_city, "Manila") # Should be resolved from coordinates
        
        # Check audit trail
        self.assertTrue(AuditTrail.objects.filter(entity_type="donations", action="STATUS_CHANGE", actor=self.admin).exists())
        
        # Check items
        item1 = donation.items.get(weight_kg=1.5)
        self.assertEqual(item1.condition_rating, "GOOD")
        self.assertEqual(item1.lookup, self.lookup)

    def test_create_donation_past_date(self):
        items = [{"lookup_id": self.lookup.lookup_id, "weight_kg": 1.5, "condition_rating": "Good"}]
        payload = {
            "donor_user_id": self.donor.user_id,
            "items": json.dumps(items),
            "preferred_pickup_date": (timezone.now() - timedelta(days=1)).isoformat(),
            "preferred_pickup_window_start": "10:00:00",
            "preferred_pickup_window_end": "12:00:00",
            "pickup_display_address": "Test",
            "pickup_latitude": "14.5645000",
            "pickup_longitude": "120.9930000",
        }
        response = self.client.post(reverse('donation-list'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('preferred_pickup_date', response.data)

    def test_donor_cannot_create_for_others(self):
        other_donor = User.objects.create_user(
            email="other@example.com", password="Pass", role="Donor", contact_no="+639003", status="ACTIVE"
        )
        self.client.force_authenticate(user=self.donor)
        items = [{"lookup_id": self.lookup.lookup_id, "weight_kg": 1.5, "condition_rating": "Good"}]
        payload = {
            "donor_user_id": other_donor.user_id, # Attempting to create for another donor
            "items": json.dumps(items),
            "preferred_pickup_date": (timezone.now() + timedelta(days=1)).isoformat(),
            "preferred_pickup_window_start": "10:00:00",
            "preferred_pickup_window_end": "12:00:00",
            "pickup_display_address": "Test",
            "pickup_latitude": "14.5645000",
            "pickup_longitude": "120.9930000",
        }
        response = self.client.post(reverse('donation-list'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('donor_user_id', response.data)

    def test_inactive_user_cannot_create(self):
        self.donor.status = 'UNDER_REVIEW'
        self.donor.save()
        self.client.force_authenticate(user=self.donor)
        
        items = [{"lookup_id": self.lookup.lookup_id, "weight_kg": 1.5, "condition_rating": "Good"}]
        payload = {
            "donor_user_id": self.donor.user_id,
            "items": json.dumps(items),
            "preferred_pickup_date": (timezone.now() + timedelta(days=1)).isoformat(),
            "preferred_pickup_window_start": "10:00:00",
            "preferred_pickup_window_end": "12:00:00",
            "pickup_display_address": "Test",
            "pickup_latitude": "14.5645000",
            "pickup_longitude": "120.9930000",
        }
        response = self.client.post(reverse('donation-list'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_donation_invalid_lookup_id(self):
        items = [{"lookup_id": 99999, "weight_kg": 1.5, "condition_rating": "Good"}]
        payload = {
            "donor_user_id": self.donor.user_id,
            "items": json.dumps(items),
            "preferred_pickup_date": (timezone.now() + timedelta(days=1)).isoformat(),
            "preferred_pickup_window_start": "10:00:00",
            "preferred_pickup_window_end": "12:00:00",
            "pickup_display_address": "Test",
            "pickup_latitude": "14.5645000",
            "pickup_longitude": "120.9930000",
        }
        response = self.client.post(reverse('donation-list'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('items', response.data)
        self.assertIn('99999 does not exist', str(response.data['items']))

    def test_donor_create_without_id(self):
        """Test that a donor can create a donation without providing donor_user_id explicitly."""
        self.client.force_authenticate(user=self.donor)
        
        payload = {
            "items": json.dumps([{"lookup_id": self.lookup.lookup_id, "weight_kg": 2.0, "condition_rating": "Fair"}]),
            "preferred_pickup_date": (timezone.now() + timedelta(days=5)).isoformat(),
            "preferred_pickup_window_start": "08:00:00",
            "preferred_pickup_window_end": "10:00:00",
            "pickup_display_address": "Home",
            "pickup_latitude": "14.5645000",
            "pickup_longitude": "120.9930000",
        }
        
        response = self.client.post(reverse('donation-list'), payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['donor']['user_id'], self.donor.user_id)
