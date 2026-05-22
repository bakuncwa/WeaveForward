from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch

from ..models import User, Donation, DonationStatus, DonationItem, BrandFiberLookup


@override_settings(USE_TZ=False)
class ImpactDashboardTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create active Donor user
        self.donor1 = User.objects.create_user(
            email="donor1@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639900000101",
            status="ACTIVE",
            first_name="John",
            last_name="Doe"
        )
        self.donor2 = User.objects.create_user(
            email="donor2@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639900000102",
            status="ACTIVE",
            first_name="Jane",
            last_name="Smith"
        )
        self.donor_no_name = User.objects.create_user(
            email="donor_noname@example.com",
            password="Password123",
            role="Donor",
            contact_no="+639900000103",
            status="ACTIVE",
            first_name="",
            last_name=""
        )

        # Create active TUAB user
        self.tuab = User.objects.create_user(
            email="tuab@example.com",
            password="Password123",
            role="TUAB",
            contact_no="+639900000104",
            status="ACTIVE",
            business_name="TUAB Business"
        )

        # Create Admin user
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="Password123",
            role="Admin",
            contact_no="+639900000105",
            status="ACTIVE"
        )

        # Create brand lookup items
        self.lookup_tshirt = BrandFiberLookup.objects.create(
            category="Tops",
            brand="Uniqlo",
            clothing_type="t-shirt",
            fiber_json='{"cotton": 100}',
            dominant_fiber="cotton",
            biodeg_score=100.0,
            biodeg_tier="HIGH",
            is_active=True
        )
        self.lookup_pants = BrandFiberLookup.objects.create(
            category="Bottoms",
            brand="Levi's",
            clothing_type="pants",
            fiber_json='{"cotton": 100}',
            dominant_fiber="cotton",
            biodeg_score=100.0,
            biodeg_tier="HIGH",
            is_active=True
        )

        self.url = reverse('impact-dashboard')

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_anonymous_user_forbidden(self, mock_load_ncr):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_tuab_user_forbidden(self, mock_load_ncr):
        self.client.force_authenticate(user=self.tuab)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["detail"], "Only donors and admins can access the impact dashboard.")

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_donor_and_admin_allowed(self, mock_load_ncr):
        mock_load_ncr.return_value = []
        for user in [self.donor1, self.admin]:
            self.client.force_authenticate(user=user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_dashboard_with_no_data(self, mock_load_ncr):
        mock_load_ncr.return_value = []
        self.client.force_authenticate(user=self.donor1)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["donations"], 0)
        self.assertEqual(response.data["donors"], 0)
        self.assertEqual(response.data["top_donors"], [])
        self.assertEqual(response.data["barangay_breakdown"], [])

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_dashboard_filters_only_received_donations(self, mock_load_ncr):
        mock_load_ncr.return_value = []
        # Create one RECEIVED donation, and one PENDING donation
        Donation.objects.create(
            donor=self.donor1,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy A",
            pickup_city="Manila",
            pickup_display_address="Address 1",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        Donation.objects.create(
            donor=self.donor2,
            status=DonationStatus.PENDING,
            pickup_barangay="Brgy B",
            pickup_city="Quezon City",
            pickup_display_address="Address 2",
            pickup_latitude=14.6760,
            pickup_longitude=121.0437,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only count received donations
        self.assertEqual(response.data["donations"], 1)
        self.assertEqual(response.data["donors"], 1)
        self.assertEqual(len(response.data["top_donors"]), 1)
        self.assertEqual(response.data["top_donors"][0]["full_name"], "John Doe")
        self.assertEqual(response.data["top_donors"][0]["donation_count"], 1)

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_top_donors_name_handling_and_sorting(self, mock_load_ncr):
        mock_load_ncr.return_value = []
        # Create multiple received donations for different donors to verify ranking/sorting and name display
        # donor1: 2 donations
        # donor2: 1 donation
        # donor_no_name: 3 donations
        for _ in range(2):
            Donation.objects.create(
                donor=self.donor1,
                status=DonationStatus.RECEIVED,
                pickup_barangay="Brgy A",
                pickup_city="Manila",
                pickup_display_address="Address",
                pickup_latitude=14.5645,
                pickup_longitude=120.9930,
                preferred_pickup_date=timezone.now() + timedelta(days=2),
                preferred_pickup_window_start="10:00:00",
                preferred_pickup_window_end="12:00:00"
            )
        Donation.objects.create(
            donor=self.donor2,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy A",
            pickup_city="Manila",
            pickup_display_address="Address",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        for _ in range(3):
            Donation.objects.create(
                donor=self.donor_no_name,
                status=DonationStatus.RECEIVED,
                pickup_barangay="Brgy B",
                pickup_city="Manila",
                pickup_display_address="Address",
                pickup_latitude=14.5645,
                pickup_longitude=120.9930,
                preferred_pickup_date=timezone.now() + timedelta(days=2),
                preferred_pickup_window_start="10:00:00",
                preferred_pickup_window_end="12:00:00"
            )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["donations"], 6)
        self.assertEqual(response.data["donors"], 3)
        
        top_donors = response.data["top_donors"]
        self.assertEqual(len(top_donors), 3)
        # Check sorting order: donor_no_name (3), donor1 (2), donor2 (1)
        self.assertEqual(top_donors[0]["full_name"], None) # donor_no_name has empty name fields
        self.assertEqual(top_donors[0]["donation_count"], 3)
        
        self.assertEqual(top_donors[1]["full_name"], "John Doe")
        self.assertEqual(top_donors[1]["donation_count"], 2)

        self.assertEqual(top_donors[2]["full_name"], "Jane Smith")
        self.assertEqual(top_donors[2]["donation_count"], 1)

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_barangay_breakdown_coordinates_lookup(self, mock_load_ncr):
        # Mock load_ncr_features to return geographical data
        mock_load_ncr.return_value = [
            (
                {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [120.9930, 14.5640],
                            [120.9940, 14.5650],
                            [120.9950, 14.5660]
                        ]
                    ]
                },
                "Brgy A",
                "Manila"
            ),
            (
                {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [121.0400, 14.6700],
                                [121.0500, 14.6800]
                            ]
                        ]
                    ]
                },
                "Brgy B",
                "Quezon City"
            )
        ]

        # Create received donations in Brgy A and Brgy B
        Donation.objects.create(
            donor=self.donor1,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy A",
            pickup_city="Manila",
            pickup_display_address="Address 1",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        Donation.objects.create(
            donor=self.donor2,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy B",
            pickup_city="Quezon City",
            pickup_display_address="Address 2",
            pickup_latitude=14.6760,
            pickup_longitude=121.0437,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        Donation.objects.create(
            donor=self.donor1,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy C", # Brgy C won't have matched coordinates
            pickup_city="Manila",
            pickup_display_address="Address 3",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check barangay breakdown structure and centroid calculation
        breakdown = {b["barangay"]: b for b in response.data["barangay_breakdown"]}
        self.assertEqual(len(breakdown), 3)

        # Brgy A centroid calculation:
        # Lat = (14.5640 + 14.5650 + 14.5660) / 3 = 14.565
        # Lon = (120.9930 + 120.9940 + 120.9950) / 3 = 120.994
        self.assertAlmostEqual(float(breakdown["Brgy A"]["latitude"]), 14.565, places=4)
        self.assertAlmostEqual(float(breakdown["Brgy A"]["longitude"]), 120.994, places=4)
        self.assertEqual(breakdown["Brgy A"]["donation_count"], 1)

        # Brgy B centroid calculation:
        # Lat = (14.6700 + 14.6800) / 2 = 14.675
        # Lon = (121.0400 + 121.0500) / 2 = 121.045
        self.assertAlmostEqual(float(breakdown["Brgy B"]["latitude"]), 14.675, places=4)
        self.assertAlmostEqual(float(breakdown["Brgy B"]["longitude"]), 121.045, places=4)
        self.assertEqual(breakdown["Brgy B"]["donation_count"], 1)

        # Brgy C is not matched
        self.assertIsNone(breakdown["Brgy C"]["latitude"])
        self.assertIsNone(breakdown["Brgy C"]["longitude"])
        self.assertEqual(breakdown["Brgy C"]["donation_count"], 1)

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_dashboard_filters(self, mock_load_ncr):
        mock_load_ncr.return_value = []
        now = timezone.now()
        
        # d1: donor1, city Manila, clothing type t-shirt, updated 5 days ago
        d1 = Donation.objects.create(
            donor=self.donor1,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy A",
            pickup_city="Manila",
            pickup_display_address="Address 1",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=now - timedelta(days=5),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        Donation.objects.filter(pk=d1.pk).update(updated_at=now - timedelta(days=5))
        DonationItem.objects.create(
            donation=d1,
            lookup=self.lookup_tshirt,
            condition_rating="GOOD",
            weight_kg=1.0
        )

        # d2: donor2, city Quezon City, clothing type pants, updated now
        d2 = Donation.objects.create(
            donor=self.donor2,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy B",
            pickup_city="Quezon City",
            pickup_display_address="Address 2",
            pickup_latitude=14.6760,
            pickup_longitude=121.0437,
            preferred_pickup_date=now,
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        Donation.objects.filter(pk=d2.pk).update(updated_at=now)
        DonationItem.objects.create(
            donation=d2,
            lookup=self.lookup_pants,
            condition_rating="GOOD",
            weight_kg=2.0
        )

        self.client.force_authenticate(user=self.admin)

        # Filter by pickup_city
        response = self.client.get(self.url, {"pickup_city": "manila"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["donations"], 1)

        # Filter by clothing_type
        response = self.client.get(self.url, {"clothing_type": "pants"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["donations"], 1)

        # Filter by date_from (only d2 matches)
        date_from_str = (now - timedelta(days=2)).date().isoformat()
        response = self.client.get(self.url, {"date_from": date_from_str})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["donations"], 1)

        # Filter by date_to (only d1 matches)
        date_to_str = (now - timedelta(days=2)).date().isoformat()
        response = self.client.get(self.url, {"date_to": date_to_str})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["donations"], 1)

        # Invalid date filters (ignored)
        response = self.client.get(self.url, {"date_from": "invalid-date", "date_to": "2026-99-99"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["donations"], 2)

    @patch("backend.views.impact_dashboard.load_ncr_features")
    def test_dashboard_excludes_admin_donors_from_donor_list(self, mock_load_ncr):
        mock_load_ncr.return_value = []
        # Create a RECEIVED donation from donor1 (Donor)
        Donation.objects.create(
            donor=self.donor1,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy A",
            pickup_city="Manila",
            pickup_display_address="Address 1",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )
        # Create a RECEIVED donation from admin (Admin)
        Donation.objects.create(
            donor=self.admin,
            status=DonationStatus.RECEIVED,
            pickup_barangay="Brgy B",
            pickup_city="Manila",
            pickup_display_address="Address 2",
            pickup_latitude=14.5645,
            pickup_longitude=120.9930,
            preferred_pickup_date=timezone.now() + timedelta(days=2),
            preferred_pickup_window_start="10:00:00",
            preferred_pickup_window_end="12:00:00"
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 2 donations in total
        self.assertEqual(response.data["donations"], 2)
        # Only 1 donor (donor1, since self.admin has Admin role, not Donor role)
        self.assertEqual(response.data["donors"], 1)
        # Only donor1 should be in top_donors
        self.assertEqual(len(response.data["top_donors"]), 1)
        self.assertEqual(response.data["top_donors"][0]["full_name"], "John Doe")

