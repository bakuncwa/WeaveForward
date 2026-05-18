from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch, Mock

from ..models import User, Donation, DonationStatus, DonationDeliveryMethod, Order, OrderStatus, OrderPayment, PaymentStatus, AuditTrail


class CancelDonationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create a donor user who owns the test donation
        self.donor = User.objects.create_user(
            email="donor_cancel@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639900000001",
            status="ACTIVE"
        )

        # Create another donor user to verify authorization boundaries
        self.other_donor = User.objects.create_user(
            email="other_donor@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639900000002",
            status="ACTIVE"
        )

        # Create a TUAB user who claims the donation
        self.tuab = User.objects.create_user(
            email="tuab_cancel@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639900000003",
            status="ACTIVE"
        )

        # Create an admin user who has elevated control permissions
        self.admin = User.objects.create_user(
            email="admin_cancel@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639900000004",
            status="ACTIVE"
        )

        # Create a pending donation belonging to the first donor
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

    def test_donor_cancel_own_pending_success(self):
        # Authenticate as the donation owner (Donor)
        self.client.force_authenticate(user=self.donor)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify response is 200 OK and status updated
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CANCELLED)
        
        # Confirm audit log records correct status transition
        self.assertTrue(AuditTrail.objects.filter(
            actor=self.donor,
            entity_type="donations",
            action="STATUS_CHANGE",
            fields_modified='["status"]'
        ).exists())

    def test_donor_cancel_other_pending_forbidden(self):
        # Authenticate as a different donor
        self.client.force_authenticate(user=self.other_donor)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify 403 Forbidden is returned and status remains unchanged
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.PENDING)

    def test_donor_cancel_own_claimed_pickup_forbidden(self):
        # Update the donation status to CLAIMED PICKUP
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.PICKUP
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()
        
        # Authenticate as the donation owner (Donor)
        self.client.force_authenticate(user=self.donor)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify 409 Conflict is returned and status remains unchanged
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CLAIMED)

    def test_donor_cancel_own_claimed_delivery_forbidden(self):
        # Update the donation status to CLAIMED DELIVERY
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.DELIVERY
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()
        
        # Authenticate as the donation owner (Donor)
        self.client.force_authenticate(user=self.donor)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify 409 Conflict is returned and status remains unchanged
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CLAIMED)

    def test_admin_cancel_any_pending_success(self):
        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify response is 200 OK and status updated
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CANCELLED)
        
        # Confirm audit log records correct status transition by Admin
        self.assertTrue(AuditTrail.objects.filter(
            actor=self.admin,
            entity_type="donations",
            action="STATUS_CHANGE",
            fields_modified='["status"]'
        ).exists())

    def test_admin_cancel_claimed_pickup_success(self):
        # Update the donation status to CLAIMED PICKUP
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.PICKUP
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify response is 200 OK and status updated
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CANCELLED)
        
        # Confirm audit log records correct status transition by Admin
        self.assertTrue(AuditTrail.objects.filter(
            actor=self.admin,
            entity_type="donations",
            action="STATUS_CHANGE",
            fields_modified='["status"]'
        ).exists())

    @patch("backend.services.lalamove_service.requests.delete")
    def test_admin_cancel_claimed_delivery_success(self, mock_delete):
        # Route delete requests to handle both Lalamove cancellation (204) and Maya voiding (200)
        def mock_delete_side_effect(url, *args, **kwargs):
            if "lalamove" in url or "orders" in url:
                return Mock(status_code=204)
            else:
                return Mock(status_code=200)
        mock_delete.side_effect = mock_delete_side_effect

        # Update the donation status to CLAIMED DELIVERY
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.DELIVERY
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()

        # Pre-create logistics Order record
        order = Order.objects.create(
            donation=self.donation,
            status=OrderStatus.ASSIGNING_DRIVER,
            lalamove_order_id="lala-order-999",
            dropoff_display_address="TUAB HQ, Manila",
            dropoff_latitude=14.5700,
            dropoff_longitude=120.9800
        )

        # Pre-create payment record associated with Order
        payment = OrderPayment.objects.create(
            order=order,
            amount=250.00,
            status=PaymentStatus.SUCCESS,
            payment_reference="maya-payment-123"
        )

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify response is 200 OK and statuses updated
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CANCELLED)
        
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        
        # Verify the new ledger reversal payment record with negative amount exists
        reversal_payment = OrderPayment.objects.filter(order=order).exclude(pk=payment.pk).first()
        self.assertIsNotNone(reversal_payment)
        self.assertEqual(reversal_payment.amount, -payment.amount)
        self.assertEqual(reversal_payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(reversal_payment.payment_reference, f"void-{payment.payment_reference}")
        
        # Check that Lalamove cancellation API was invoked with correct DELETE parameters
        called_urls = [call[0][0] for call in mock_delete.call_args_list]
        self.assertTrue(any("v3/orders/lala-order-999" in url for url in called_urls))
        
        # Confirm audit log records correct status transition by Admin
        self.assertTrue(AuditTrail.objects.filter(
            actor=self.admin,
            entity_type="donations",
            action="STATUS_CHANGE",
            fields_modified='["status"]'
        ).exists())

    @patch("backend.services.lalamove_service.requests.delete")
    def test_admin_cancel_claimed_delivery_lalamove_failure(self, mock_delete):
        # Setup Lalamove mock response as a failure (409 Cancellation Forbidden)
        mock_delete.return_value = Mock(status_code=409, text="Order cannot be cancelled at this stage.")

        # Update the donation status to CLAIMED DELIVERY
        self.donation.status = DonationStatus.CLAIMED
        self.donation.delivery_method = DonationDeliveryMethod.DELIVERY
        self.donation.claimed_by_tuab = self.tuab
        self.donation.save()

        # Pre-create logistics Order record
        order = Order.objects.create(
            donation=self.donation,
            status=OrderStatus.ASSIGNING_DRIVER,
            lalamove_order_id="lala-order-999",
            dropoff_display_address="TUAB HQ, Manila",
            dropoff_latitude=14.5700,
            dropoff_longitude=120.9800
        )

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify 502 Bad Gateway is returned due to Lalamove cancellation failure
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Lalamove cancellation failed", response.data["detail"])
        
        # Verify transaction rolled back completely, leaving statuses unchanged
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.CLAIMED)
        
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.ASSIGNING_DRIVER)

    def test_tuab_cancel_forbidden(self):
        # Authenticate as a TUAB
        self.client.force_authenticate(user=self.tuab)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify 403 Forbidden is returned and status remains unchanged
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.PENDING)

    def test_admin_cancel_non_allowed_status_forbidden(self):
        # Update status to RECEIVED (which is immutable/not allowed for cancel)
        self.donation.status = DonationStatus.RECEIVED
        self.donation.save()

        # Authenticate as Admin
        self.client.force_authenticate(user=self.admin)
        url = reverse("donation-cancel", kwargs={"pk": self.donation.pk})
        
        # Execute the POST request to cancel
        response = self.client.post(url)
        
        # Verify 409 Conflict is returned and status remains unchanged
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, DonationStatus.RECEIVED)
