from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, Mock

from ..models import User, Donation, DonationStatus, DonationDeliveryMethod, Order, OrderStatus, OrderPayment, PaymentStatus, AuditTrail


class ArchiveDonationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create a donor user
        self.donor = User.objects.create_user(
            email="donor_archive@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639900000001",
            status="ACTIVE"
        )

        # Create a TUAB user
        self.tuab = User.objects.create_user(
            email="tuab_archive@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639900000002",
            status="ACTIVE"
        )

        # Create an admin user
        self.admin = User.objects.create_user(
            email="admin_archive@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639900000003",
            status="ACTIVE"
        )

        # Create a pending donation
        self.donation = Donation.objects.create(
            donor=self.donor,
            status=DonationStatus.PENDING,
            pickup_display_address="Benilde Campus, Manila",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )

    def test_donor_archive_forbidden(self):
        # Authenticate as Donor
        self.client.force_authenticate(user=self.donor)
        url = reverse("donation-archive", kwargs={"pk": self.donation.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.PENDING)

    def test_tuab_archive_forbidden(self):
        # Authenticate as TUAB
        self.client.force_authenticate(user=self.tuab)
        url = reverse("donation-archive", kwargs={"pk": self.donation.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.PENDING)

    def test_admin_archive_pending_success(self):
        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-archive", kwargs={"pk": self.donation.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.ARCHIVED)
        
        # Confirm audit log records correct status transition
        self.assertTrue(AuditTrail.objects.filter(
            actor=self.admin,
            entity_type="donations",
            action="STATUS_CHANGE",
            fields_modified='["status"]'
        ).exists())

    def test_admin_archive_claimed_pickup_success(self):
        # Set donation to claimed pickup
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.PICKUP
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-archive", kwargs={"pk": self.donation.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.ARCHIVED)

    @patch("backend.services.lalamove_service.requests.delete")
    def test_admin_archive_in_progress_delivery_success(self, mock_delete):
        # Route delete requests to handle both Lalamove cancellation (204) and Maya voiding (200)
        def mock_delete_side_effect(url, *args, **kwargs):
            if "lalamove" in url or "orders" in url:
                return Mock(status_code=204)
            else:
                return Mock(status_code=200)
        mock_delete.side_effect = mock_delete_side_effect

        # Set donation to claimed delivery
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.DELIVERY
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()

        # Create logistics Order record (in-progress)
        order = Order.objects.create(
            donation=self.donation,
            status=OrderStatus.ASSIGNING_DRIVER,
            lalamove_order_id="lala-order-111",
            dropoff_display_address="TUAB HQ, Manila",
            dropoff_latitude=14.5700,
            dropoff_longitude=120.9800
        )

        # Create payment record associated with Order
        payment = OrderPayment.objects.create(
            order=order,
            amount=250.00,
            status=PaymentStatus.SUCCESS,
            payment_reference="maya-payment-111"
        )

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-archive", kwargs={"pk": self.donation.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.ARCHIVED)
        
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        
        # Verify negative payment reversal exists
        reversal_payment = OrderPayment.objects.filter(order=order).exclude(pk=payment.pk).first()
        self.assertIsNotNone(reversal_payment)
        self.assertEqual(reversal_payment.amount, -payment.amount)
        
        # Verify Lalamove cancel was called
        called_urls = [call[0][0] for call in mock_delete.call_args_list]
        self.assertTrue(any("v3/orders/lala-order-111" in url for url in called_urls))

    @patch("backend.services.lalamove_service.requests.delete")
    def test_admin_archive_in_progress_delivery_failure_rolls_back(self, mock_delete):
        # Setup mock response to fail (409 Cancellation Forbidden)
        mock_delete.return_value = Mock(status_code=409, text="Order cannot be cancelled at this stage.")

        # Set donation to claimed delivery
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.DELIVERY
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()

        # Create logistics Order record (in-progress)
        order = Order.objects.create(
            donation=self.donation,
            status=OrderStatus.ASSIGNING_DRIVER,
            lalamove_order_id="lala-order-222",
            dropoff_display_address="TUAB HQ, Manila",
            dropoff_latitude=14.5700,
            dropoff_longitude=120.9800
        )

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-archive", kwargs={"pk": self.donation.pk})
        
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Lalamove cancellation failed", response.data["detail"])
        
        # Verify transaction rolled back completely
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CLAIMED)
        
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.ASSIGNING_DRIVER)

    def test_admin_archive_completed_delivery_no_cancel_called(self):
        # Set donation to received (delivery completed)
        self.donation.status = DonationStatus.RECEIVED
        self.donation.delivery_method = DonationDeliveryMethod.DELIVERY
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()

        # Create logistics Order record (completed)
        order = Order.objects.create(
            donation=self.donation,
            status=OrderStatus.COMPLETED,
            lalamove_order_id="lala-order-333",
            dropoff_display_address="TUAB HQ, Manila",
            dropoff_latitude=14.5700,
            dropoff_longitude=120.9800
        )

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-archive", kwargs={"pk": self.donation.pk})
        
        # We do not mock requests.delete; if it tries to call cancel_lalamove_order, it will raise connection error / perform real request and crash.
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.ARCHIVED)
        
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
