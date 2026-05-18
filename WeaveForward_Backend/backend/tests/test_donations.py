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

    def test_create_donation_model_unavailable(self):
        from unittest.mock import patch
        from backend.services.prediction_service import MatchPredictionService
        
        # Force model reload on next call
        original_model = MatchPredictionService._model
        MatchPredictionService._model = None
        
        try:
            # Patch builtins.open to simulate missing model/metadata files
            with patch('builtins.open', side_effect=FileNotFoundError):
                items = [{"lookup_id": self.lookup.lookup_id, "weight_kg": 1.5, "condition_rating": "Good"}]
                payload = {
                    "donor_user_id": self.donor.user_id,
                    "items": json.dumps(items),
                    "preferred_pickup_date": (timezone.now() + timedelta(days=5)).isoformat(),
                    "preferred_pickup_window_start": "10:00:00",
                    "preferred_pickup_window_end": "12:00:00",
                    "pickup_display_address": "Test",
                    "pickup_latitude": "14.5645000",
                    "pickup_longitude": "120.9930000",
                }
                
                response = self.client.post(reverse('donation-list'), payload, format='multipart')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("Prediction model is unavailable", response.data['detail'])
        finally:
            MatchPredictionService._model = original_model

    def test_edit_donation_model_unavailable(self):
        from unittest.mock import patch
        from backend.services.prediction_service import MatchPredictionService
        from decimal import Decimal
        
        # 1. Create a successful donation first
        donation = Donation.objects.create(
            donor=self.donor,
            preferred_pickup_date='2026-06-01',
            preferred_pickup_window_start='10:00:00',
            preferred_pickup_window_end='12:00:00',
            pickup_display_address="Manila",
            pickup_latitude=Decimal('14.5645000'),
            pickup_longitude=Decimal('120.9930000'),
            status='PENDING'
        )
        DonationItem.objects.create(
            donation=donation,
            lookup=self.lookup,
            weight_kg=1.5,
            condition_rating='GOOD'
        )
        
        self.client.force_authenticate(user=self.donor)
        
        # Force model reload on next call
        original_model = MatchPredictionService._model
        MatchPredictionService._model = None
        
        try:
            # Patch builtins.open to simulate missing model/metadata files
            with patch('builtins.open', side_effect=FileNotFoundError):
                items_payload = [
                    {
                        "item_id": DonationItem.objects.filter(donation=donation).first().item_id,
                        "weight_kg": 2.5
                    }
                ]
                payload = {
                    "pickup_display_address": "Updated Manila Address",
                    "items": json.dumps(items_payload)
                }
                
                from backend.services.etag_service import build_updated_at_etag
                etag = build_updated_at_etag(donation)
                
                response = self.client.patch(
                    reverse('donation-detail', kwargs={'pk': donation.donation_id}),
                    payload,
                    HTTP_IF_MATCH=etag
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("Prediction model is unavailable", response.data['detail'])
                
                # Check that the database update was rolled back
                donation.refresh_from_db()
                self.assertEqual(donation.pickup_display_address, "Manila")
        finally:
            MatchPredictionService._model = original_model

    def test_edit_donation_metadata_only_does_not_trigger_prediction_model(self):
        from unittest.mock import patch
        from backend.services.prediction_service import MatchPredictionService
        from decimal import Decimal
        
        # 1. Create a successful donation first
        donation = Donation.objects.create(
            donor=self.donor,
            preferred_pickup_date='2026-06-01',
            preferred_pickup_window_start='10:00:00',
            preferred_pickup_window_end='12:00:00',
            pickup_display_address="Manila",
            pickup_latitude=Decimal('14.5645000'),
            pickup_longitude=Decimal('120.9930000'),
            status='PENDING'
        )
        DonationItem.objects.create(
            donation=donation,
            lookup=self.lookup,
            weight_kg=1.5,
            condition_rating='GOOD'
        )
        
        self.client.force_authenticate(user=self.donor)
        
        # Force model reload on next call
        original_model = MatchPredictionService._model
        MatchPredictionService._model = None
        
        try:
            # Patch builtins.open to simulate missing model/metadata files
            # If the prediction logic runs, it will raise FileNotFoundError.
            # But since we do NOT pass "items" in the edit payload, it should skip it entirely and succeed!
            with patch('builtins.open', side_effect=FileNotFoundError):
                payload = {
                    "pickup_display_address": "Updated Manila Address"
                }
                
                from backend.services.etag_service import build_updated_at_etag
                etag = build_updated_at_etag(donation)
                
                response = self.client.patch(
                    reverse('donation-detail', kwargs={'pk': donation.donation_id}),
                    payload,
                    HTTP_IF_MATCH=etag
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                
                # Verify address was successfully updated without any rollback
                donation.refresh_from_db()
                self.assertEqual(donation.pickup_display_address, "Updated Manila Address")
        finally:
            MatchPredictionService._model = original_model
