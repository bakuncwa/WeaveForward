import json
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.utils import timezone
from ..models import (
    User, Donation, DonationStatus, DonationDeliveryMethod,
    BrandFiberLookup, DonationItem, Order, OrderStatus, AuditTrail, InventoryLedger
)


class ResolveDonationAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create lookup data
        self.lookup = BrandFiberLookup.objects.create(
            category="Jeans",
            brand="Levi's",
            clothing_type="Pants",
            fiber_json='{"cotton": 100}'
        )

        # Users
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639000000001",
            status="ACTIVE"
        )
        self.donor = User.objects.create_user(
            email="donor@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639000000002",
            status="ACTIVE"
        )
        self.tuab = User.objects.create_user(
            email="tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000000003",
            status="ACTIVE"
        )
        self.other_tuab = User.objects.create_user(
            email="othertuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000000004",
            status="ACTIVE"
        )
        self.inactive_tuab = User.objects.create_user(
            email="inactivetuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639000000005",
            status="UNDER_REVIEW"
        )

        # Base pickup donation in transit
        self.pickup_donation = Donation.objects.create(
            donor=self.donor,
            status=DonationStatus.IN_TRANSIT,
            claimed_by_tuab=self.tuab,
            delivery_method=DonationDeliveryMethod.PICKUP,
            pickup_display_address="Test Address",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now(),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        self.pickup_item = DonationItem.objects.create(
            donation=self.pickup_donation,
            lookup=self.lookup,
            weight_kg=1.5,
            condition_rating="GOOD"
        )

        # Base delivery donation in transit with COMPLETED order
        self.delivery_donation = Donation.objects.create(
            donor=self.donor,
            status=DonationStatus.IN_TRANSIT,
            claimed_by_tuab=self.tuab,
            delivery_method=DonationDeliveryMethod.DELIVERY,
            pickup_display_address="Test Address",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now(),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        self.delivery_item = DonationItem.objects.create(
            donation=self.delivery_donation,
            lookup=self.lookup,
            weight_kg=2.0,
            condition_rating="NEW"
        )
        self.completed_order = Order.objects.create(
            donation=self.delivery_donation,
            status=OrderStatus.COMPLETED,
            dropoff_display_address="TUAB Address",
            dropoff_latitude=14.5600,
            dropoff_longitude=120.9900
        )

    def test_unauthenticated_gets_401(self):
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})
        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_donor_gets_403(self):
        self.client.force_authenticate(user=self.donor)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})
        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_tuab_gets_403(self):
        self.pickup_donation.claimed_by_tuab = self.inactive_tuab
        self.pickup_donation.save()
        
        self.client.force_authenticate(user=self.inactive_tuab)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})
        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("active", res.data['detail'].lower())

    def test_unassociated_tuab_gets_403(self):
        self.client.force_authenticate(user=self.other_tuab)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})
        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("claimed by your own business", res.data['detail'].lower())

    def test_pickup_not_in_transit_gets_409(self):
        self.client.force_authenticate(user=self.tuab)
        self.pickup_donation.status = DonationStatus.CLAIMED
        self.pickup_donation.save()

        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})
        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("must be in-transit", res.data['detail'].lower())

    def test_delivery_not_in_transit_gets_409(self):
        self.client.force_authenticate(user=self.tuab)
        self.delivery_donation.status = DonationStatus.CLAIMED
        self.delivery_donation.save()

        url = reverse('donation-resolve', kwargs={'pk': self.delivery_donation.pk})
        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("must be in-transit", res.data['detail'].lower())

    def test_delivery_order_not_completed_gets_409(self):
        self.client.force_authenticate(user=self.tuab)
        self.completed_order.status = OrderStatus.PICKED_UP
        self.completed_order.save()

        url = reverse('donation-resolve', kwargs={'pk': self.delivery_donation.pk})
        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("order must be completed", res.data['detail'].lower())

    def test_pickup_resolve_received_success(self):
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})

        items_patch = [
            {
                "item_id": self.pickup_item.item_id,
                "weight_kg": 2.5,
                "condition_rating": "POOR"
            }
        ]

        res = self.client.post(
            url,
            {
                "status": "RECEIVED",
                "items": json.dumps(items_patch)
            },
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.pickup_donation.refresh_from_db()
        self.assertEqual(self.pickup_donation.status, DonationStatus.RECEIVED)
        self.assertIsNone(self.pickup_donation.rejection_reason)

        # Check item was updated
        self.pickup_item.refresh_from_db()
        self.assertEqual(self.pickup_item.weight_kg, 2.5)
        self.assertEqual(self.pickup_item.condition_rating, "POOR")

        # Verify audit trail
        self.assertTrue(
            AuditTrail.objects.filter(
                entity_type="donations",
                action="STATUS_CHANGE",
                actor=self.tuab
            ).exists()
        )

    def test_pickup_resolve_rejected_success(self):
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})

        res = self.client.post(
            url,
            {
                "status": "REJECTED",
                "rejection_reason": "Damaged and unsanitary items"
            },
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.pickup_donation.refresh_from_db()
        self.assertEqual(self.pickup_donation.status, DonationStatus.REJECTED)
        self.assertEqual(self.pickup_donation.rejection_reason, "Damaged and unsanitary items")

    def test_reject_requires_reason(self):
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})

        res = self.client.post(
            url,
            {
                "status": "REJECTED",
                "rejection_reason": "   "
            },
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rejection_reason", res.data)

    def test_admin_cannot_resolve_donation(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})

        res = self.client.post(url, {"status": "RECEIVED"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.pickup_donation.refresh_from_db()
        self.assertNotEqual(self.pickup_donation.status, DonationStatus.RECEIVED)

    def test_resolve_donation_creates_single_inventory_and_audit(self):
        self.client.force_authenticate(user=self.tuab)
        url = reverse('donation-resolve', kwargs={'pk': self.pickup_donation.pk})

        payload = {
            "status": "RECEIVED",
            "items": json.dumps([
                {
                    "item_id": self.pickup_item.pk,
                    "weight_kg": 2.5,
                    "is_archived": False
                },
                {
                    "lookup": self.lookup.pk,
                    "weight_kg": 3.4,
                    "condition_rating": "GOOD"
                }
            ])
        }

        initial_inventory_count = InventoryLedger.objects.count()
        initial_audit_count = AuditTrail.objects.filter(entity_type="inventory_ledger", action="CONSUMPTION_LOG").count()

        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Check that one InventoryLedger record was created for the entire donation
        self.assertEqual(InventoryLedger.objects.count(), initial_inventory_count + 1)
        new_ledger = InventoryLedger.objects.latest('inventory_id')
        self.assertEqual(new_ledger.source_donation, self.pickup_donation)
        self.assertEqual(float(new_ledger.weight_before_kg), 5.9)
        self.assertEqual(float(new_ledger.current_weight_kg), 5.9)
        self.assertEqual(float(new_ledger.usage_amount_kg), 0)

        # Check that an AuditTrail record with action CONSUMPTION_LOG was created
        self.assertEqual(
            AuditTrail.objects.filter(entity_type="inventory_ledger", action="CONSUMPTION_LOG").count(),
            initial_audit_count + 1
        )
        new_audit = AuditTrail.objects.filter(entity_type="inventory_ledger", action="CONSUMPTION_LOG").latest('audit_id')
        self.assertEqual(new_audit.actor, self.tuab)
