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

    def test_edit_donation_validation_errors_all_at_once(self):
        from decimal import Decimal
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
        
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(donation)
        
        payload = {
            "pickup_display_address": "  ",
            "preferred_pickup_date": None,
            "preferred_pickup_window_start": "  ",
            "pickup_latitude": "invalid_lat",
            "pickup_longitude": "120.993",
        }
        
        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pickup_display_address', response.data)
        self.assertIn('preferred_pickup_date', response.data)
        self.assertIn('preferred_pickup_window_start', response.data)
        self.assertIn('pickup_latitude', response.data)
        self.assertIn('pickup_longitude', response.data)


class DonationListSerializerTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin_list@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639000001001",
            status="ACTIVE",
        )
        self.donor = User.objects.create_user(
            email="donor_list@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639000001002",
            status="ACTIVE",
            first_name="Listy",
            last_name="Donor",
        )
        self.tuab = User.objects.create_user(
            email="tuab_list@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000001003",
            status="ACTIVE",
            business_name="Upcycle Labs",
        )
        self.upload = Upload.objects.create(file_path="donations/test.jpg", name="test.jpg")
        self.lookup = BrandFiberLookup.objects.create(
            category="Tops",
            brand="Uniqlo",
            clothing_type="t-shirt",
            fiber_json='{"cotton": 100}',
            dominant_fiber="cotton",
            biodeg_score="88.50",
            biodeg_tier="HIGH",
            is_active=True,
        )
        self.donation = Donation.objects.create(
            donor=self.donor,
            claimed_by_tuab=self.tuab,
            upload=self.upload,
            status="PENDING",
            is_flagged=True,
            delivery_method="PICKUP",
            flag_reason="Flag reason should not be listed",
            auto_archive_at=timezone.now() + timedelta(days=30),
            pickup_barangay="Barangay 123",
            pickup_city="Manila",
            pickup_display_address="123 Test Street",
            pickup_latitude="14.5645000",
            pickup_longitude="120.9930000",
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00",
            rejection_reason="Unused in list",
        )
        DonationItem.objects.create(
            donation=self.donation,
            lookup=self.lookup,
            condition_rating="GOOD",
            weight_kg="1.500",
        )



    def test_donation_retrieve_remains_detailed(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(reverse('donation-detail', kwargs={'pk': self.donation.donation_id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        donation_data = response.data

        for detailed_field in ['pickup_barangay', 'pickup_city', 'flag_reason', 'auto_archive_at', 'submitted_at', 'rejection_reason', 'updated_at']:
            self.assertIn(detailed_field, donation_data)

        self.assertIn('user_id', donation_data['donor'])
        self.assertIn('item_id', donation_data['items'][0])
        self.assertIn('condition_rating', donation_data['items'][0])
        self.assertIn('weight_kg', donation_data['items'][0])
        self.assertIn('lookup_id', donation_data['items'][0]['lookup_details'])


from unittest.mock import patch
from decimal import Decimal
from backend.models import Order

class AdminDonationUpdateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin_update@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639000002001",
            status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="donor_update@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639000002002",
            status="ACTIVE"
        )
        self.tuab = User.objects.create_user(
            email="tuab_update@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000002003",
            status="ACTIVE",
            business_name="Test Business"
        )
        self.lookup = BrandFiberLookup.objects.create(
            category="Tops",
            brand="Uniqlo",
            clothing_type="t-shirt",
            fiber_json='{"cotton": 100}',
            dominant_fiber="cotton",
            biodeg_score="88.50",
            biodeg_tier="HIGH",
            is_active=True,
        )
        # Create a claimed donation
        self.donation = Donation.objects.create(
            donor=self.donor,
            claimed_by_tuab=self.tuab,
            status="CLAIMED",
            delivery_method="DELIVERY",
            pickup_display_address="DLSU Manila",
            pickup_latitude=Decimal('14.5645000'),
            pickup_longitude=Decimal('120.9930000'),
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        DonationItem.objects.create(
            donation=self.donation,
            lookup=self.lookup,
            condition_rating="GOOD",
            weight_kg="1.500",
        )
        # Create associated order
        self.order = Order.objects.create(
            donation=self.donation,
            lalamove_order_id="12345_lalamove",
            status="ASSIGNING_DRIVER",
            dropoff_display_address="Initial Address",
            dropoff_latitude=Decimal('14.5648520'),
            dropoff_longitude=Decimal('120.9978767')
        )

    @patch('requests.patch')
    def test_admin_update_claimed_only_dropoff_success(self, mock_patch):
        mock_patch.return_value.status_code = 200
        mock_patch.return_value.json.return_value = {"status": "SUCCESS"}

        self.client.force_authenticate(user=self.admin)
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(self.donation)

        payload = {
            "dropoff_display_address": "CSB Taft Manila",
            "dropoff_latitude": "14.5648520",
            "dropoff_longitude": "120.9978767"
        }

        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.order.refresh_from_db()
        self.assertEqual(self.order.dropoff_display_address, "CSB Taft Manila")
        mock_patch.assert_called_once()

    def test_admin_update_claimed_blocked_pickup_fields(self):
        self.client.force_authenticate(user=self.admin)
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(self.donation)

        # Attempt to change pickup address (which is blocked)
        payload = {
            "pickup_display_address": "New Pickup Address"
        }

        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pickup_display_address", response.data)
        self.assertEqual(response.data["pickup_display_address"][0], "Cannot edit pickup location details once the delivery has been claimed.")

    @patch('requests.patch')
    def test_admin_update_claimed_allowed_non_pickup_fields(self, mock_patch):
        mock_patch.return_value.status_code = 200
        mock_patch.return_value.json.return_value = {"status": "SUCCESS"}

        self.client.force_authenticate(user=self.admin)
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(self.donation)

        # Admin updates dropoff and is_flagged (both allowed)
        payload = {
            "is_flagged": True,
            "dropoff_display_address": "CSB Taft Manila",
            "dropoff_latitude": "14.5648520",
            "dropoff_longitude": "120.9978767"
        }

        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.donation.refresh_from_db()
        self.assertTrue(self.donation.is_flagged)
        self.order.refresh_from_db()
        self.assertEqual(self.order.dropoff_display_address, "CSB Taft Manila")
        mock_patch.assert_called_once()

    def test_donor_cannot_edit_claimed_donation(self):
        self.client.force_authenticate(user=self.donor)
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(self.donation)

        payload = {
            "dropoff_display_address": "CSB Taft Manila",
            "dropoff_latitude": "14.5648520",
            "dropoff_longitude": "120.9978767"
        }

        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_admin_update_pickup_donation_fails_with_dropoff(self):
        pickup_donation = Donation.objects.create(
            donor=self.donor,
            status="PENDING",
            delivery_method="PICKUP",
            pickup_display_address="DLSU Manila",
            pickup_latitude=Decimal('14.5645000'),
            pickup_longitude=Decimal('120.9930000'),
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        DonationItem.objects.create(
            donation=pickup_donation,
            lookup=self.lookup,
            condition_rating="GOOD",
            weight_kg="1.500",
        )

        self.client.force_authenticate(user=self.admin)
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(pickup_donation)

        payload = {
            "dropoff_display_address": "CSB Taft Manila",
            "dropoff_latitude": "14.5648520",
            "dropoff_longitude": "120.9978767"
        }

        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': pickup_donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        for field in ["dropoff_display_address", "dropoff_latitude", "dropoff_longitude"]:
            self.assertIn(field, response.data)
            self.assertEqual(response.data[field][0], "Dropoff details are not allowed for PICKUP donations.")

    def test_admin_update_received_blocked_fields(self):
        # Move donation and order status to RECEIVED
        self.donation.status = "RECEIVED"
        self.donation.save()
        self.order.status = "COMPLETED"
        self.order.save()

        self.client.force_authenticate(user=self.admin)
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(self.donation)

        # Attempt to change dropoff address
        payload = {
            "dropoff_display_address": "New Dropoff Address"
        }
        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("dropoff_display_address", response.data)
        self.assertEqual(response.data["dropoff_display_address"][0], "Cannot edit dropoff location details once the delivery is received.")

        # Attempt to change pickup address
        payload = {
            "pickup_display_address": "New Pickup Address"
        }
        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pickup_display_address", response.data)
        self.assertEqual(response.data["pickup_display_address"][0], "Cannot edit pickup location details once the delivery is received.")

    def test_admin_update_rejected_blocked_fields(self):
        # Move donation and order status to REJECTED / FAILED
        self.donation.status = "REJECTED"
        self.donation.save()
        self.order.status = "FAILED"
        self.order.save()

        self.client.force_authenticate(user=self.admin)
        from backend.services.etag_service import build_updated_at_etag
        etag = build_updated_at_etag(self.donation)

        # Attempt to change dropoff address
        payload = {
            "dropoff_display_address": "New Dropoff Address"
        }
        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("dropoff_display_address", response.data)
        self.assertEqual(response.data["dropoff_display_address"][0], "Cannot edit dropoff location details once the delivery is rejected.")

        # Attempt to change pickup address
        payload = {
            "pickup_display_address": "New Pickup Address"
        }
        response = self.client.patch(
            reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
            payload,
            HTTP_IF_MATCH=etag,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pickup_display_address", response.data)
        self.assertEqual(response.data["pickup_display_address"][0], "Cannot edit pickup location details once the delivery is rejected.")

    def test_admin_edit_items_triggers_prediction_model(self):
        from backend.services.prediction_service import MatchPredictionService

        self.client.force_authenticate(user=self.admin)
        original_model = MatchPredictionService._model
        MatchPredictionService._model = None

        try:
            with patch('builtins.open', side_effect=FileNotFoundError):
                item = DonationItem.objects.filter(donation=self.donation).first()
                payload = {
                    "items": json.dumps([
                        {
                            "item_id": item.item_id,
                            "weight_kg": "2.000"
                        }
                    ])
                }

                from backend.services.etag_service import build_updated_at_etag
                etag = build_updated_at_etag(self.donation)

                response = self.client.patch(
                    reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
                    payload,
                    HTTP_IF_MATCH=etag,
                    format='json'
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("Prediction model is unavailable", response.data['detail'])
        finally:
            MatchPredictionService._model = original_model

    def test_admin_metadata_only_does_not_trigger_prediction_model(self):
        from backend.services.prediction_service import MatchPredictionService

        self.client.force_authenticate(user=self.admin)
        original_model = MatchPredictionService._model
        MatchPredictionService._model = None

        try:
            with patch('builtins.open', side_effect=FileNotFoundError):
                payload = {
                    "is_flagged": True
                }

                from backend.services.etag_service import build_updated_at_etag
                etag = build_updated_at_etag(self.donation)

                response = self.client.patch(
                    reverse('donation-detail', kwargs={'pk': self.donation.donation_id}),
                    payload,
                    HTTP_IF_MATCH=etag,
                    format='json'
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)

                self.donation.refresh_from_db()
                self.assertTrue(self.donation.is_flagged)
        finally:
            MatchPredictionService._model = original_model



