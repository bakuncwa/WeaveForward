import os
import django
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'WeaveForward_Backend.settings')
django.setup()

from backend.models import (
    User, UserRole, UserAccountStatus, UserOperationalStatus,
    BrandFiberLookup, Donation, DonationItem, DonationItemConditionRating,
    DonationDeliveryMethod, DonationStatus
)

def seed():
    print("Starting database seeding...")

    # 1. Clean existing mock data (optional, but keep admin)
    User.objects.exclude(email="admin@weaveforward.com").delete()
    Donation.objects.all().delete()
    
    # 2. Get some BrandFiberLookup objects to link items
    lookups = list(BrandFiberLookup.objects.all()[:10])
    if not lookups:
        print("[WARNING] No BrandFiberLookups found! Make sure populate_catalog has run.")
        # Create a fallback lookup
        fallback = BrandFiberLookup.objects.create(
            category="Jeans",
            brand="Levi's",
            clothing_type="Pants",
            fiber_json='{"cotton": 100}',
            dominant_fiber="cotton",
            biodeg_score=Decimal("100.00"),
            is_active=True
        )
        lookups = [fallback]

    # 3. Create Donors
    donor1 = User.objects.create_user(
        email="donor1@weaveforward.com",
        password="Password123",
        role=UserRole.DONOR,
        first_name="Juan",
        last_name="Dela Cruz",
        contact_no="+639170000001",
        status=UserAccountStatus.ACTIVE,
        barangay="Barangay 662",
        city="Manila",
        latitude=Decimal("14.5645"),
        longitude=Decimal("120.9930"),
        display_address="Taft Ave, Malate, Manila"
    )
    print(f"Created Donor: {donor1.email}")

    donor2 = User.objects.create_user(
        email="donor2@weaveforward.com",
        password="Password123",
        role=UserRole.DONOR,
        first_name="Maria",
        last_name="Clara",
        contact_no="+639170000002",
        status=UserAccountStatus.ACTIVE,
        barangay="San Lorenzo",
        city="Makati",
        latitude=Decimal("14.5547"),
        longitude=Decimal("121.0244"),
        display_address="Ayala Ave, Makati"
    )
    print(f"Created Donor: {donor2.email}")

    # 4. Create TUABs (Artisan Businesses)
    tuab1 = User.objects.create_user(
        email="artisan1@weaveforward.com",
        password="Password123",
        role=UserRole.TUAB,
        business_name="GreenWeave Studio",
        description="A sustainable upcycling studio focusing on cotton and denim fabric scraps to create stylish tote bags and home accessories.",
        social_link="https://instagram.com/greenweavestudio",
        max_active_claims=5,
        target_fibers="cotton,denim",
        min_biodeg_score=Decimal("50.00"),
        max_distance_km=Decimal("25.00"),
        operational_status=UserOperationalStatus.ACTIVE,
        status=UserAccountStatus.ACTIVE,
        contact_no="+639180000001",
        barangay="Barangay 701",
        city="Manila",
        latitude=Decimal("14.5688"),
        longitude=Decimal("120.9902"),
        display_address="Vito Cruz, Malate, Manila"
    )
    print(f"Created TUAB: {tuab1.business_name} ({tuab1.email})")

    tuab2 = User.objects.create_user(
        email="artisan2@weaveforward.com",
        password="Password123",
        role=UserRole.TUAB,
        business_name="EcoThread Creations",
        description="We craft premium quilts, rugs, and custom garments from 100% natural wool, cotton, and linen donation surpluses.",
        social_link="https://facebook.com/ecothreadcreations",
        max_active_claims=3,
        target_fibers="wool,cotton,linen",
        min_biodeg_score=Decimal("60.00"),
        max_distance_km=Decimal("50.00"),
        operational_status=UserOperationalStatus.ACTIVE,
        status=UserAccountStatus.ACTIVE,
        contact_no="+639180000002",
        barangay="Bel-Air",
        city="Makati",
        latitude=Decimal("14.5612"),
        longitude=Decimal("121.0315"),
        display_address="Sen. Gil Puyat Ave, Makati"
    )
    print(f"Created TUAB: {tuab2.business_name} ({tuab2.email})")

    # 5. Create some Donations
    donation1 = Donation.objects.create(
        donor=donor1,
        status=DonationStatus.PENDING,
        delivery_method=DonationDeliveryMethod.PICKUP,
        preferred_pickup_date=timezone.now() + timedelta(days=2),
        preferred_pickup_window_start="09:00:00",
        preferred_pickup_window_end="12:00:00",
        pickup_barangay="Barangay 662",
        pickup_city="Manila",
        pickup_display_address="Taft Ave, Malate, Manila",
        pickup_latitude=Decimal("14.5645"),
        pickup_longitude=Decimal("120.9930")
    )
    
    DonationItem.objects.create(
        donation=donation1,
        lookup=lookups[0],
        condition_rating=DonationItemConditionRating.GOOD,
        weight_kg=Decimal("2.500")
    )
    DonationItem.objects.create(
        donation=donation1,
        lookup=lookups[min(1, len(lookups)-1)],
        condition_rating=DonationItemConditionRating.LIKE_NEW,
        weight_kg=Decimal("1.200")
    )
    print(f"Created Donation 1 from {donor1.email} with 2 items.")

    donation2 = Donation.objects.create(
        donor=donor2,
        status=DonationStatus.PENDING,
        delivery_method=DonationDeliveryMethod.PICKUP,
        preferred_pickup_date=timezone.now() + timedelta(days=3),
        preferred_pickup_window_start="14:00:00",
        preferred_pickup_window_end="17:00:00",
        pickup_barangay="San Lorenzo",
        pickup_city="Makati",
        pickup_display_address="Ayala Ave, Makati",
        pickup_latitude=Decimal("14.5547"),
        pickup_longitude=Decimal("121.0244")
    )
    
    DonationItem.objects.create(
        donation=donation2,
        lookup=lookups[min(2, len(lookups)-1)],
        condition_rating=DonationItemConditionRating.FAIR,
        weight_kg=Decimal("4.800")
    )
    print(f"Created Donation 2 from {donor2.email} with 1 item.")

    print("\nDatabase seeding completed successfully!")

if __name__ == "__main__":
    seed()
