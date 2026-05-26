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
    DonationDeliveryMethod, DonationStatus,
    InventoryLedger, InventoryLifecycleStatus,
    MatchPrediction, AuditTrail,
    Order, OrderPayment,
    Subscription, SubscriptionStatus, SubscriptionTier,
)
from backend.services.prediction_service import run_predictions_for_donation


def get_lookup(fiber, fallback_lookups):
    """Fetch a real BrandFiberLookup with the given dominant fiber, or fall back."""
    qs = BrandFiberLookup.objects.filter(is_active=True, dominant_fiber__iexact=fiber)
    if qs.exists():
        return qs.first()
    return fallback_lookups[0]


def seed():
    print("Starting database seeding...")

    # 1. Clean existing mock data in FK-safe order (keep admin)
    MatchPrediction.objects.all().delete()
    InventoryLedger.objects.all().delete()
    OrderPayment.objects.all().delete()
    Order.objects.all().delete()
    Donation.objects.all().delete()
    AuditTrail.objects.filter(actor__email__in=User.objects.exclude(email="admin@weaveforward.com").values("email")).delete()
    Subscription.objects.exclude(user__email="admin@weaveforward.com").delete()
    User.objects.exclude(email="admin@weaveforward.com").delete()

    # 2. Get BrandFiberLookup objects
    fallback_lookups = list(BrandFiberLookup.objects.filter(is_active=True)[:10])
    if not fallback_lookups:
        print("[WARNING] No BrandFiberLookups found! Make sure populate_catalog has run.")
        fallback = BrandFiberLookup.objects.create(
            category="Jeans",
            brand="Levi's",
            clothing_type="Pants",
            fiber_json='{"cotton": 100}',
            dominant_fiber="cotton",
            biodeg_score=Decimal("100.00"),
            is_active=True
        )
        fallback_lookups = [fallback]

    # Fiber-keyed lookup cache
    fiber_lookup = {}
    for fiber in ["cotton", "denim", "wool", "linen", "silk", "polyester", "bamboo", "rayon"]:
        fiber_lookup[fiber] = get_lookup(fiber, fallback_lookups)

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
        latitude=Decimal("14.5645000"),
        longitude=Decimal("120.9930000"),
        display_address="Taft Ave, Malate, Manila"
    )
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
        latitude=Decimal("14.5547000"),
        longitude=Decimal("121.0244000"),
        display_address="Ayala Ave, Makati"
    )
    donor3 = User.objects.create_user(
        email="donor3@weaveforward.com",
        password="Password123",
        role=UserRole.DONOR,
        first_name="Jose",
        last_name="Rizal",
        contact_no="+639170000003",
        status=UserAccountStatus.ACTIVE,
        barangay="Poblacion",
        city="Makati",
        latitude=Decimal("14.5649000"),
        longitude=Decimal("121.0328000"),
        display_address="P. Burgos St, Poblacion, Makati"
    )
    donor4 = User.objects.create_user(
        email="donor4@weaveforward.com",
        password="Password123",
        role=UserRole.DONOR,
        first_name="Ana",
        last_name="Santos",
        contact_no="+639170000004",
        status=UserAccountStatus.ACTIVE,
        barangay="Commonwealth",
        city="Quezon City",
        latitude=Decimal("14.6760000"),
        longitude=Decimal("121.0437000"),
        display_address="Commonwealth Ave, Quezon City"
    )
    donor5 = User.objects.create_user(
        email="donor5@weaveforward.com",
        password="Password123",
        role=UserRole.DONOR,
        first_name="Carlo",
        last_name="Reyes",
        contact_no="+639170000005",
        status=UserAccountStatus.ACTIVE,
        barangay="Kapitolyo",
        city="Pasig",
        latitude=Decimal("14.5764000"),
        longitude=Decimal("121.0851000"),
        display_address="Kapitolyo, Pasig City"
    )
    donor6 = User.objects.create_user(
        email="donor6@weaveforward.com",
        password="Password123",
        role=UserRole.DONOR,
        first_name="Liza",
        last_name="Mangubat",
        contact_no="+639170000006",
        status=UserAccountStatus.ACTIVE,
        barangay="Western Bicutan",
        city="Taguig",
        latitude=Decimal("14.5243000"),
        longitude=Decimal("121.0792000"),
        display_address="BGC, Taguig City"
    )
    print(f"Created 6 Donors.")

    # 4. Create TUABs
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
        latitude=Decimal("14.5688000"),
        longitude=Decimal("120.9902000"),
        display_address="Vito Cruz, Malate, Manila"
    )
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
        latitude=Decimal("14.5612000"),
        longitude=Decimal("121.0315000"),
        display_address="Sen. Gil Puyat Ave, Makati"
    )
    print(f"Created TUABs: {tuab1.business_name}, {tuab2.business_name}")

    # 5. Create PRO Subscriptions for both TUABs (required for run_predictions_for_donation)
    now = timezone.now()
    Subscription.objects.create(
        user=tuab1,
        status=SubscriptionStatus.ACTIVE,
        subscription_tier=SubscriptionTier.PRO,
        start_date=now - timedelta(days=30),
        end_date=now + timedelta(days=335),
    )
    Subscription.objects.create(
        user=tuab2,
        status=SubscriptionStatus.ACTIVE,
        subscription_tier=SubscriptionTier.PRO,
        start_date=now - timedelta(days=15),
        end_date=now + timedelta(days=350),
    )
    print("Created PRO subscriptions for both TUABs.")

    # 6. Helper: create a PENDING pickup donation
    city_data = {
        "Manila":       {"barangay": "Barangay 662", "lat": Decimal("14.5645000"), "lng": Decimal("120.9930000"), "addr": "Taft Ave, Malate, Manila"},
        "Makati":       {"barangay": "San Lorenzo",  "lat": Decimal("14.5547000"), "lng": Decimal("121.0244000"), "addr": "Ayala Ave, Makati"},
        "Quezon City":  {"barangay": "Commonwealth", "lat": Decimal("14.6760000"), "lng": Decimal("121.0437000"), "addr": "Commonwealth Ave, Quezon City"},
        "Pasig":        {"barangay": "Kapitolyo",    "lat": Decimal("14.5764000"), "lng": Decimal("121.0851000"), "addr": "Kapitolyo, Pasig City"},
        "Taguig":       {"barangay": "Western Bicutan","lat": Decimal("14.5243000"), "lng": Decimal("121.0792000"), "addr": "BGC, Taguig City"},
        "Mandaluyong":  {"barangay": "Wack-Wack",   "lat": Decimal("14.5794000"), "lng": Decimal("121.0359000"), "addr": "Shaw Blvd, Mandaluyong"},
        "Paranaque":    {"barangay": "BF Homes",    "lat": Decimal("14.4793000"), "lng": Decimal("121.0198000"), "addr": "Quirino Ave, Parañaque"},
        "Las Pinas":    {"barangay": "Almanza Uno", "lat": Decimal("14.4446000"), "lng": Decimal("120.9939000"), "addr": "Alabang-Zapote Rd, Las Piñas"},
    }

    def make_pending(donor, city_name, items_spec, pickup_days=3):
        c = city_data[city_name]
        d = Donation.objects.create(
            donor=donor,
            status=DonationStatus.PENDING,
            delivery_method=DonationDeliveryMethod.PICKUP,
            preferred_pickup_date=now + timedelta(days=pickup_days),
            preferred_pickup_window_start="09:00:00",
            preferred_pickup_window_end="12:00:00",
            pickup_barangay=c["barangay"],
            pickup_city=city_name,
            pickup_display_address=c["addr"],
            pickup_latitude=c["lat"],
            pickup_longitude=c["lng"],
        )
        for fiber, condition, weight in items_spec:
            DonationItem.objects.create(
                donation=d,
                lookup=fiber_lookup[fiber],
                condition_rating=condition,
                weight_kg=Decimal(str(weight)),
            )
        return d

    C = DonationItemConditionRating
    pending_donations = []

    # 20 varied PENDING donations: skewed toward cotton/denim (tuab1 target) and wool/linen (tuab2 target)
    pending_donations.append(make_pending(donor1, "Manila",      [("cotton",   C.LIKE_NEW, 2.5), ("denim",    C.GOOD,     1.2)], 2))
    pending_donations.append(make_pending(donor2, "Makati",      [("wool",     C.GOOD,     4.8)], 3))
    pending_donations.append(make_pending(donor3, "Makati",      [("linen",    C.FAIR,     3.0), ("cotton",   C.GOOD,     1.5)], 4))
    pending_donations.append(make_pending(donor4, "Quezon City", [("denim",    C.GOOD,     5.0), ("cotton",   C.LIKE_NEW, 2.0)], 2))
    pending_donations.append(make_pending(donor5, "Pasig",       [("silk",     C.NEW,      0.8), ("rayon",    C.FAIR,     1.0)], 5))
    pending_donations.append(make_pending(donor6, "Taguig",      [("polyester",C.FAIR,     3.5)], 3))
    pending_donations.append(make_pending(donor1, "Manila",      [("bamboo",   C.GOOD,     2.0), ("linen",    C.LIKE_NEW, 1.8)], 4))
    pending_donations.append(make_pending(donor2, "Makati",      [("cotton",   C.NEW,      6.0)], 2))
    pending_donations.append(make_pending(donor3, "Makati",      [("denim",    C.GOOD,     4.5), ("denim",    C.FAIR,     2.5)], 3))
    pending_donations.append(make_pending(donor4, "Quezon City", [("wool",     C.LIKE_NEW, 3.2), ("wool",     C.GOOD,     2.0)], 5))
    pending_donations.append(make_pending(donor5, "Pasig",       [("cotton",   C.GOOD,     1.5), ("cotton",   C.FAIR,     0.8)], 4))
    pending_donations.append(make_pending(donor6, "Taguig",      [("linen",    C.NEW,      2.8)], 2))
    pending_donations.append(make_pending(donor1, "Mandaluyong", [("rayon",    C.GOOD,     1.5), ("silk",     C.LIKE_NEW, 0.6)], 6))
    pending_donations.append(make_pending(donor2, "Paranaque",   [("cotton",   C.FAIR,     4.0), ("polyester",C.POOR,     1.0)], 3))
    pending_donations.append(make_pending(donor3, "Las Pinas",   [("wool",     C.GOOD,     5.5)], 4))
    pending_donations.append(make_pending(donor4, "Quezon City", [("denim",    C.LIKE_NEW, 7.0)], 2))
    pending_donations.append(make_pending(donor5, "Pasig",       [("bamboo",   C.NEW,      2.2), ("linen",    C.GOOD,     3.0)], 5))
    pending_donations.append(make_pending(donor6, "Taguig",      [("cotton",   C.GOOD,     3.8), ("denim",    C.GOOD,     2.1)], 3))
    pending_donations.append(make_pending(donor1, "Manila",      [("silk",     C.LIKE_NEW, 1.0), ("wool",     C.FAIR,     2.5)], 7))
    pending_donations.append(make_pending(donor2, "Makati",      [("polyester",C.GOOD,     2.0), ("rayon",    C.GOOD,     1.5)], 4))
    pending_donations.append(make_pending(donor3, "Mandaluyong", [("cotton",   C.NEW,      5.0), ("bamboo",   C.LIKE_NEW, 1.0)], 3))
    pending_donations.append(make_pending(donor4, "Quezon City", [("linen",    C.GOOD,     4.2)], 2))

    print(f"Created {len(pending_donations)} PENDING donations with varied fibers across NCR.")

    # 7. Create RECEIVED donations (feed inventory ledger)
    donation_rcv1 = Donation.objects.create(
        donor=donor1,
        claimed_by_tuab=tuab1,
        status=DonationStatus.RECEIVED,
        delivery_method=DonationDeliveryMethod.PICKUP,
        preferred_pickup_date=now - timedelta(days=10),
        preferred_pickup_window_start="09:00:00",
        preferred_pickup_window_end="12:00:00",
        pickup_barangay="Barangay 662",
        pickup_city="Manila",
        pickup_display_address="Taft Ave, Malate, Manila",
        pickup_latitude=Decimal("14.5645000"),
        pickup_longitude=Decimal("120.9930000"),
    )
    DonationItem.objects.create(donation=donation_rcv1, lookup=fiber_lookup["cotton"], condition_rating=C.GOOD,     weight_kg=Decimal("3.000"))
    DonationItem.objects.create(donation=donation_rcv1, lookup=fiber_lookup["denim"],  condition_rating=C.LIKE_NEW, weight_kg=Decimal("2.000"))

    donation_rcv2 = Donation.objects.create(
        donor=donor2,
        claimed_by_tuab=tuab1,
        status=DonationStatus.RECEIVED,
        delivery_method=DonationDeliveryMethod.PICKUP,
        preferred_pickup_date=now - timedelta(days=45),
        preferred_pickup_window_start="10:00:00",
        preferred_pickup_window_end="13:00:00",
        pickup_barangay="San Lorenzo",
        pickup_city="Makati",
        pickup_display_address="Ayala Ave, Makati",
        pickup_latitude=Decimal("14.5547000"),
        pickup_longitude=Decimal("121.0244000"),
    )
    DonationItem.objects.create(donation=donation_rcv2, lookup=fiber_lookup["denim"], condition_rating=C.FAIR, weight_kg=Decimal("5.500"))

    donation_rcv3 = Donation.objects.create(
        donor=donor3,
        claimed_by_tuab=tuab2,
        status=DonationStatus.RECEIVED,
        delivery_method=DonationDeliveryMethod.PICKUP,
        preferred_pickup_date=now - timedelta(days=5),
        preferred_pickup_window_start="13:00:00",
        preferred_pickup_window_end="16:00:00",
        pickup_barangay="Poblacion",
        pickup_city="Makati",
        pickup_display_address="P. Burgos St, Poblacion, Makati",
        pickup_latitude=Decimal("14.5649000"),
        pickup_longitude=Decimal("121.0328000"),
    )
    DonationItem.objects.create(donation=donation_rcv3, lookup=fiber_lookup["wool"],  condition_rating=C.GOOD, weight_kg=Decimal("6.200"))
    DonationItem.objects.create(donation=donation_rcv3, lookup=fiber_lookup["linen"], condition_rating=C.NEW,  weight_kg=Decimal("1.800"))
    print("Created 3 RECEIVED donations for inventory seeding.")

    # 8. Create InventoryLedger entries for RECEIVED donations
    inv1 = InventoryLedger.objects.create(
        source_donation=donation_rcv1,
        usage_amount_kg=Decimal("0.500"),
        weight_before_kg=Decimal("5.000"),
        current_weight_kg=Decimal("4.500"),
        lifecycle_status=InventoryLifecycleStatus.ACTIVE,
        is_upcyclable=True,
        low_stock_threshold=Decimal("1.300"),
        notes="Initial ingestion from received donation (cotton/denim batch)"
    )
    print(f"Created InventoryLedger #{inv1.inventory_id} for donation_rcv1 (tuab1, active).")

    inv2 = InventoryLedger.objects.create(
        source_donation=donation_rcv2,
        usage_amount_kg=Decimal("1.200"),
        weight_before_kg=Decimal("5.500"),
        current_weight_kg=Decimal("4.300"),
        lifecycle_status=InventoryLifecycleStatus.ACTIVE,
        is_upcyclable=True,
        low_stock_threshold=Decimal("1.300"),
        notes="Initial ingestion from older donation (audit flag expected)"
    )
    InventoryLedger.objects.filter(pk=inv2.pk).update(updated_at=now - timedelta(days=45))
    print(f"Created InventoryLedger #{inv2.inventory_id} for donation_rcv2 (tuab1, audit required).")

    inv3 = InventoryLedger.objects.create(
        source_donation=donation_rcv3,
        usage_amount_kg=Decimal("0.000"),
        weight_before_kg=Decimal("8.000"),
        current_weight_kg=Decimal("8.000"),
        lifecycle_status=InventoryLifecycleStatus.ACTIVE,
        is_upcyclable=True,
        low_stock_threshold=Decimal("1.300"),
        notes="Initial ingestion from wool/linen batch (tuab2)"
    )
    print(f"Created InventoryLedger #{inv3.inventory_id} for donation_rcv3 (tuab2, active).")

    # 9. Run ML predictions for all PENDING donations
    print(f"\nRunning ML fiber-match predictions for {len(pending_donations)} PENDING donations...")
    success_count = 0
    for d in pending_donations:
        try:
            run_predictions_for_donation(d.donation_id)
            success_count += 1
        except Exception as e:
            print(f"  [WARN] Prediction failed for donation {d.donation_id}: {e}")

    print(f"\nDatabase seeding completed successfully!")
    print(f"  Donors: 6 | TUABs: 2 (both PRO subscribers)")
    print(f"  Donations: {len(pending_donations)} PENDING + 3 RECEIVED = {len(pending_donations)+3} total")
    print(f"  InventoryLedger: 3 entries (1 audit-flagged)")
    print(f"  ML Predictions: ran for {success_count}/{len(pending_donations)} donations")
    print()
    print("Login credentials (all use password: Password123)")
    print("  Donors : donor1–donor6@weaveforward.com")
    print("  TUABs  : artisan1@weaveforward.com (GreenWeave Studio)")
    print("           artisan2@weaveforward.com (EcoThread Creations)")

if __name__ == "__main__":
    seed()
