from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from ..models import User, Donation, DonationStatus, DonationDeliveryMethod, BrandFiberLookup, AuditTrail
from django.utils import timezone

class MarkInTransitTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        # Create a donor
        self.donor = User.objects.create_user(
            email="donor@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639000000001",
            status="ACTIVE"
        )
        
        # Create an active TUAB
        self.tuab = User.objects.create_user(
            email="tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000000002",
            status="ACTIVE"
        )
        
        # Create an inactive TUAB
        self.inactive_tuab = User.objects.create_user(
            email="inactive_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000000003",
            status="UNDER_REVIEW"
        )
        
        # Create a donation
        self.donation = Donation.objects.create(
            donor=self.donor,
            status=DonationStatus.CLAIMED,
            claimed_by_tuab=self.tuab,
            delivery_method=DonationDeliveryMethod.PICKUP,
            pickup_display_address="Test Address",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now(),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )

    def test_mark_in_transit_success(self):
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.IN_TRANSIT)
        
        # Check audit trail
        self.assertTrue(AuditTrail.objects.filter(entity_type="donations", action="STATUS_CHANGE", actor=self.tuab).exists())

    def test_mark_in_transit_not_owner(self):
        other_tuab = User.objects.create_user(
            email="other_tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000000004",
            status="ACTIVE"
        )
        self.client.force_authenticate(user=other_tuab)
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("claimed by your own business", response.data['detail'])

    def test_mark_in_transit_inactive_user(self):
        self.donation.claimed_by_tuab = self.inactive_tuab
        self.donation.save()
        
        self.client.force_authenticate(user=self.inactive_tuab)
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        # Note: Generic ViewSet retrieve/get_object might fail if user can't see it, 
        # but here the status is UNDER_REVIEW, so authentication passes but status check in service fails.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("business account must be active", response.data['detail'])

    def test_mark_in_transit_not_pickup(self):
        self.donation.delivery_method = DonationDeliveryMethod.DELIVERY
        self.donation.save()
        
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Only pick-up donations", response.data['detail'])

    def test_mark_in_transit_not_claimed(self):
        self.donation.status = DonationStatus.PENDING
        self.donation.save()
        
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("cannot be marked as in-transit", response.data['detail'])

    def test_mark_in_transit_donor_role(self):
        # A Donor is not allowed to mark in-transit
        self.client.force_authenticate(user=self.donor)
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mark_in_transit_unauthenticated(self):
        # Unauthenticated user should get 401 Unauthorized
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mark_in_transit_etag_updated(self):
        old_updated_at = self.donation.updated_at
        
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-transit', kwargs={'pk': self.donation.pk})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertNotEqual(self.donation.updated_at, old_updated_at)
