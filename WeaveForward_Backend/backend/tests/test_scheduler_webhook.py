import json
from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch, Mock

from ..models import (
    User,
    Subscription,
    SubscriptionStatus,
    Donation,
    DonationStatus,
    UserRole,
    UserAccountStatus,
    MatchPrediction,
    BrandFiberLookup,
    DonationItem,
    AuditTrail,
)

@override_settings(
    SCHEDULER_SECRET="test-scheduler-secret-key-xyz"
)
class SchedulerWebhookTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@weaveforward.com",
            password="SecureAdminPassword123",
            role=UserRole.ADMIN,
            contact_no="+639150000301",
            status=UserAccountStatus.ACTIVE,
        )
        self.tuab = User.objects.create_user(
            email="tuab@example.com",
            password="Password123",
            role=UserRole.TUAB,
            contact_no="+639150000302",
            status=UserAccountStatus.ACTIVE,
            maya_customer_id="maya-customer-123",
            maya_card_id="maya-card-123",
        )
        self.donor = User.objects.create_user(
            email="donor@example.com",
            password="Password123",
            role=UserRole.DONOR,
            contact_no="+639150000303",
            status=UserAccountStatus.ACTIVE,
        )

    def test_webhook_fails_with_invalid_scheduler_secret(self):
        response = self.client.post(
            reverse('webhooks'),
            {},
            format='json',
            HTTP_X_SCHEDULER_SECRET="invalid-secret"
        )
        # Should fall back to IP check and return 403 Forbidden since IP is not allowlisted
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('backend.services.subscription_service.requests.delete')
    def test_webhook_succeeds_with_valid_scheduler_secret(self, mocked_delete):
        mocked_delete.return_value = Mock(status_code=200, text=json.dumps({"status": "deleted"}))

        # Create an expired subscription (end_date in the past)
        expired_sub = Subscription.objects.create(
            user=self.tuab,
            status=SubscriptionStatus.ACTIVE,
            subscription_tier="PRO",
            start_date=timezone.now() - timezone.timedelta(days=35),
            end_date=timezone.now() - timezone.timedelta(days=5),
        )

        # Create an expired donation (auto_archive_at in the past)
        expired_donation = Donation.objects.create(
            donor=self.donor,
            status=DonationStatus.PENDING,
            pickup_barangay="San Lorenzo",
            pickup_city="Makati",
            pickup_display_address="123 Main St",
            pickup_latitude=Decimal("14.5547"),
            pickup_longitude=Decimal("121.0244"),
            preferred_pickup_date=timezone.now() - timezone.timedelta(days=1),
            preferred_pickup_window_start="09:00:00",
            preferred_pickup_window_end="12:00:00",
            auto_archive_at=timezone.now() - timezone.timedelta(days=1),
        )

        # Create an archived match prediction
        lookup = BrandFiberLookup.objects.create(
            category="T-shirt",
            brand="Uniqlo",
            clothing_type="Top",
            fiber_json=json.dumps({"cotton": 100}),
        )
        item = DonationItem.objects.create(
            donation=expired_donation,
            lookup=lookup,
            condition_rating="GOOD",
            weight_kg=Decimal("0.5"),
        )
        archived_pred = MatchPrediction.objects.create(
            item=item,
            tuab=self.tuab,
            is_match=True,
            match_prob=Decimal("0.95"),
            is_archived_version=True,
        )

        # Hit the webhook with the correct scheduler secret header
        response = self.client.post(
            reverse('webhooks'),
            {},
            format='json',
            HTTP_X_SCHEDULER_SECRET="test-scheduler-secret-key-xyz"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['detail'],
            "Successfully processed subscriptions, auto-archived donations, and cleared predictions."
        )
        self.assertEqual(response.data['results']['cancelled_subscriptions_count'], 1)
        self.assertEqual(response.data['results']['archived_donations_count'], 1)
        self.assertEqual(response.data['results']['deleted_predictions_count'], 1)

        # Verify database updates
        expired_sub.refresh_from_db()
        expired_donation.refresh_from_db()
        self.tuab.refresh_from_db()

        self.assertEqual(expired_sub.status, SubscriptionStatus.CANCELLED)
        self.assertIsNone(self.tuab.maya_card_id)
        self.assertEqual(expired_donation.status, DonationStatus.ARCHIVED)
        
        # Verify match prediction was deleted
        self.assertFalse(MatchPrediction.objects.filter(pk=archived_pred.pk).exists())

        # Verify subscription cancel audit log has admin as actor
        sub_audit = AuditTrail.objects.filter(entity_type="users", action="STATUS_CHANGE").latest("occurred_at")
        self.assertEqual(sub_audit.actor, self.admin)
        
        # Verify donation archive audit log has admin as actor
        don_audit = AuditTrail.objects.filter(entity_type="donations", action="STATUS_CHANGE").latest("occurred_at")
        self.assertEqual(don_audit.actor, self.admin)


