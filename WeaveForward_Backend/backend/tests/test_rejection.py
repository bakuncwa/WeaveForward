import json
from django.urls import reverse
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from ..models import User, UserRole, UserAccountStatus, AuditTrail
from ..services.etag_service import build_updated_at_etag

class UserRejectionAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="Password123",
            role=UserRole.ADMIN,
            contact_no="+639150000001",
            status=UserAccountStatus.ACTIVE
        )
        self.tuab_under_review = User.objects.create_user(
            email="tuab_review@example.com",
            password="Password123",
            role=UserRole.TUAB,
            contact_no="+639150000002",
            status=UserAccountStatus.UNDER_REVIEW
        )

    def test_admin_can_reject_tuab_with_reason(self):
        self.client.force_authenticate(user=self.admin)
        rejection_reason = "Missing documentation"
        
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_under_review.user_id}),
            {"status": "REJECTED", "rejection_reason": rejection_reason},
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        self.tuab_under_review.refresh_from_db()
        self.assertEqual(self.tuab_under_review.status, UserAccountStatus.REJECTED)
        self.assertEqual(self.tuab_under_review.rejection_reason, rejection_reason)
        
        # Verify Audit Log
        audit = AuditTrail.objects.filter(
            entity_type='users',
            action='STATUS_CHANGE',
            actor=self.admin
        ).last()
        self.assertIsNotNone(audit)
        self.assertIn('rejection_reason', audit.fields_modified)

    def test_admin_reject_requires_non_empty_reason(self):
        self.client.force_authenticate(user=self.admin)
        
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_under_review.user_id}),
            {"status": "REJECTED", "rejection_reason": "   "},
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Rejection reason is required", res.data['detail'])

    def test_admin_reject_reason_length_limit(self):
        self.client.force_authenticate(user=self.admin)
        long_reason = "a" * 201
        
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_under_review.user_id}),
            {"status": "REJECTED", "rejection_reason": long_reason},
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("too long", res.data['detail'])

    def test_admin_requires_valid_status(self):
        self.client.force_authenticate(user=self.admin)
        
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_under_review.user_id}),
            {"status": "ARCHIVED"},
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Must be ACTIVE or REJECTED", res.data['detail'])

    def test_admin_can_still_approve_tuab(self):
        self.client.force_authenticate(user=self.admin)
        
        res = self.client.post(
            reverse('user-approve', kwargs={'pk': self.tuab_under_review.user_id}),
            {"status": "ACTIVE"},
            format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.tuab_under_review.refresh_from_db()
        self.assertEqual(self.tuab_under_review.status, UserAccountStatus.ACTIVE)
        self.assertIsNone(self.tuab_under_review.rejection_reason)
