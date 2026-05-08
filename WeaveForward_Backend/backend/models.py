from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django_mysql.models import EnumField
from decimal import Decimal


class TinyIntegerField(models.PositiveSmallIntegerField):
    """Emits TINYINT UNSIGNED on MySQL (0–255) to match the data dictionary."""
    def db_type(self, connection):
        return "tinyint UNSIGNED"

    def get_internal_type(self):
        return "PositiveSmallIntegerField"


class UserRole(models.TextChoices):
    DONOR = "Donor", "Donor"
    TUAB  = "TUAB",  "TUAB"
    ADMIN = "Admin", "Admin"


class UserOperationalStatus(models.TextChoices):
    ACTIVE      = "ACTIVE",      "Active"
    HIBERNATING = "HIBERNATING", "Hibernating"
    ARCHIVED    = "ARCHIVED",    "Archived"


class UserAccountStatus(models.TextChoices):
    ACTIVE       = "ACTIVE",       "Active"
    UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
    REJECTED     = "REJECTED",     "Rejected"
    ARCHIVED     = "ARCHIVED",     "Archived"


class DonationStatus(models.TextChoices):
    PENDING    = "PENDING",    "Pending"
    CLAIMED    = "CLAIMED",    "Claimed"
    IN_TRANSIT = "IN_TRANSIT", "In Transit"
    RECEIVED   = "RECEIVED",   "Received"
    REJECTED   = "REJECTED",   "Rejected"
    CANCELLED  = "CANCELLED",  "Cancelled"
    ARCHIVED   = "ARCHIVED",   "Archived"


class DonationDeliveryMethod(models.TextChoices):
    PICKUP   = "PICKUP",   "Pickup"
    DELIVERY = "DELIVERY", "Delivery"


class DonationItemConditionRating(models.TextChoices):
    NEW      = "NEW",      "New"
    LIKE_NEW = "LIKE_NEW", "Like New"
    GOOD     = "GOOD",     "Good"
    FAIR     = "FAIR",     "Fair"
    POOR     = "POOR",     "Poor"


class BiodegTier(models.TextChoices):
    HIGH   = "HIGH",   "High"
    MEDIUM = "MEDIUM", "Medium"
    LOW    = "LOW",    "Low"


class MatchRecommendationStatus(models.TextChoices):
    PENDING  = "PENDING",  "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"


class InventoryLifecycleStatus(models.TextChoices):
    ACTIVE          = "ACTIVE",          "Active"
    PENDING_ARCHIVE = "PENDING_ARCHIVE", "Pending Archive"
    ARCHIVED        = "ARCHIVED",        "Archived"


class InventoryExitState(models.TextChoices):
    UPCYCLED = "UPCYCLED", "Upcycled"
    SHREDDED = "SHREDDED", "Shredded"
    LANDFILL = "LANDFILL", "Landfill"


class SubscriptionStatus(models.TextChoices):
    ACTIVE    = "ACTIVE",    "Active"
    CANCELLED = "CANCELLED", "Cancelled"


class SubscriptionTier(models.TextChoices):
    FREE = "FREE", "Free"
    PRO  = "PRO",  "Pro"


class PaymentStatus(models.TextChoices):
    SUCCESS = "SUCCESS", "Success"
    FAILED  = "FAILED",  "Failed"
    PENDING = "PENDING", "Pending"


class OrderStatus(models.TextChoices):
    ASSIGNING_DRIVER = "ASSIGNING_DRIVER", "Assigning Driver"
    ON_GOING         = "ON_GOING",         "On Going"
    PICKED_UP        = "PICKED_UP",        "Picked Up"
    COMPLETED        = "COMPLETED",        "Completed"
    CANCELLED        = "CANCELLED",        "Cancelled"
    FAILED           = "FAILED",           "Failed"


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.ADMIN)
        extra_fields.setdefault("status", UserAccountStatus.ACTIVE)
        return self.create_user(email, password, **extra_fields)


class Upload(models.Model):
    upload_id = models.AutoField(primary_key=True)
    file_path = models.CharField(max_length=255)
    name      = models.CharField(max_length=50)

    class Meta:
        db_table = "uploads"


class User(AbstractBaseUser):
    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["role", "contact_no"]
    objects         = UserManager()
    last_login      = None  # column dropped; set SIMPLE_JWT["UPDATE_LAST_LOGIN"] = False or logins will crash

    user_id            = models.AutoField(primary_key=True)  # set SIMPLE_JWT["USER_ID_FIELD"] = "user_id" and ["USER_ID_CLAIM"] = "user_id" or protected endpoints will 401
    email              = models.CharField(max_length=100, unique=True)  # set TokenObtainPairSerializer.username_field = "email" or login will reject valid credentials
    password           = models.CharField(max_length=70, db_column="password_hash")
    role               = EnumField(choices=UserRole.choices)
    first_name         = models.CharField(max_length=50,  null=True, default=None)
    last_name          = models.CharField(max_length=50,  null=True, default=None)
    middle_name        = models.CharField(max_length=50,  null=True, default=None)
    business_name      = models.CharField(max_length=125, null=True, default=None)
    description        = models.TextField(null=True, default=None)
    social_link        = models.TextField(null=True, default=None)
    max_active_claims  = TinyIntegerField(null=True, default=3, validators=[MinValueValidator(1), MaxValueValidator(255)])
    target_fibers      = models.TextField(null=True, default=None)
    min_biodeg_score   = models.DecimalField(max_digits=5,  decimal_places=2, null=True, default=None, validators=[MinValueValidator(0.00), MaxValueValidator(100.00)])
    max_distance_km    = models.DecimalField(max_digits=6,  decimal_places=2, null=True, default=None, validators=[MinValueValidator(0.00), MaxValueValidator(1000.00)])
    operational_status = EnumField(choices=UserOperationalStatus.choices, null=True, default=None)
    contact_no         = models.CharField(max_length=13, unique=True)
    barangay           = models.CharField(max_length=50,  null=True, blank=True)
    city               = models.CharField(max_length=50,  null=True, blank=True)
    latitude           = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude          = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    display_address    = models.TextField(null=True, blank=True)
    maya_customer_id   = models.CharField(max_length=50,  null=True, default=None)
    maya_card_id       = models.CharField(max_length=20,  null=True, default=None)
    status             = EnumField(choices=UserAccountStatus.choices, default=UserAccountStatus.UNDER_REVIEW)
    is_2fa_enabled     = models.BooleanField(default=False)
    totp_secret        = models.CharField(max_length=64, null=True, default=None)
    upload             = models.ForeignKey(Upload, on_delete=models.SET_NULL, null=True, default=None, related_name="profile_photo_users",  db_column="upload_id")
    documentation      = models.ForeignKey(Upload, on_delete=models.SET_NULL, null=True, default=None, related_name="documentation_users", db_column="documentation_id")
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    @property
    def is_active(self):
        # Allow ACTIVE and UNDER_REVIEW users to authenticate
        return self.status in [UserAccountStatus.ACTIVE, UserAccountStatus.UNDER_REVIEW]

    @property
    def is_staff(self):
        return self.role == UserRole.ADMIN

    class Meta:
        db_table = "users"


class BrandFiberLookup(models.Model):
    lookup_id      = models.AutoField(primary_key=True)
    category       = models.CharField(max_length=100)
    brand          = models.CharField(max_length=200)
    clothing_type  = models.CharField(max_length=200)
    fiber_json     = models.TextField()
    dominant_fiber = models.CharField(max_length=200, null=True, default=None)
    biodeg_score   = models.DecimalField(max_digits=5, decimal_places=2, null=True, default=None)
    biodeg_tier    = EnumField(choices=BiodegTier.choices, null=True, default=None)
    is_active      = models.BooleanField(default=True)
    scraped_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "brand_fiber_lookup"


class Donation(models.Model):
    donation_id                   = models.AutoField(primary_key=True)
    donor                         = models.ForeignKey(User,   on_delete=models.RESTRICT, related_name="donations_as_donor", db_column="donor_id")
    claimed_by_tuab               = models.ForeignKey(User,   on_delete=models.SET_NULL, related_name="donations_claimed",  db_column="claimed_by_tuab", null=True, default=None)
    upload                        = models.ForeignKey(Upload, on_delete=models.SET_NULL, related_name="donation_proofs",    db_column="upload_id",       null=True, default=None)
    status                        = EnumField(choices=DonationStatus.choices, default=DonationStatus.PENDING)
    is_flagged                    = models.BooleanField(default=False)
    delivery_method               = EnumField(choices=DonationDeliveryMethod.choices, null=True, default=None)
    flag_reason                   = models.TextField(null=True, default=None)
    auto_archive_at               = models.DateTimeField(null=True, default=None)
    submitted_at                  = models.DateTimeField(auto_now_add=True, db_index=True)
    rejection_reason              = models.CharField(max_length=200, null=True, default=None)
    updated_at                    = models.DateTimeField(auto_now=True)
    pickup_barangay               = models.CharField(max_length=50)
    pickup_city                   = models.CharField(max_length=50)
    pickup_display_address        = models.TextField()
    pickup_latitude               = models.DecimalField(max_digits=18, decimal_places=15)
    pickup_longitude              = models.DecimalField(max_digits=18, decimal_places=15)
    preferred_pickup_date         = models.DateTimeField()
    preferred_pickup_window_start = models.TimeField()
    preferred_pickup_window_end   = models.TimeField()

    class Meta:
        db_table = "donations"


class DonationItem(models.Model):
    item_id          = models.AutoField(primary_key=True)
    donation         = models.ForeignKey(Donation,        on_delete=models.CASCADE,  related_name="items",          db_column="donation_id")
    lookup           = models.ForeignKey(BrandFiberLookup, on_delete=models.RESTRICT, related_name="donation_items", db_column="lookup_id")
    condition_rating = EnumField(choices=DonationItemConditionRating.choices)
    weight_kg        = models.DecimalField(max_digits=8, decimal_places=3)
    is_archived      = models.BooleanField(default=False)

    class Meta:
        db_table = "donation_items"


class MatchPrediction(models.Model):
    pair_id               = models.AutoField(primary_key=True)
    item                  = models.ForeignKey(DonationItem, on_delete=models.RESTRICT, related_name="match_predictions", db_column="item_id")
    tuab                  = models.ForeignKey(User,         on_delete=models.RESTRICT, related_name="match_predictions", db_column="tuab_id")
    is_match              = models.BooleanField()
    pct_target_fiber      = models.DecimalField(max_digits=5, decimal_places=2, null=True, default=None)
    biodeg_target_fiber   = models.DecimalField(max_digits=5, decimal_places=2, null=True, default=None)
    match_prob            = models.DecimalField(max_digits=6, decimal_places=5)
    distance_km           = models.DecimalField(max_digits=8, decimal_places=3, null=True, default=None)
    is_archived_version   = models.BooleanField(default=False)
    recommendation_status = EnumField(choices=MatchRecommendationStatus.choices, default=MatchRecommendationStatus.PENDING)
    tuab_rejection_reason = models.TextField(null=True, default=None)
    predicted_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "match_predictions"


class InventoryLedger(models.Model):
    inventory_id        = models.AutoField(primary_key=True)
    source_donation     = models.ForeignKey(Donation, on_delete=models.RESTRICT, related_name="inventory_ledger_entries", db_column="source_donation_id")
    usage_amount_kg     = models.DecimalField(max_digits=10, decimal_places=3)
    weight_before_kg    = models.DecimalField(max_digits=10, decimal_places=3)
    current_weight_kg   = models.DecimalField(max_digits=10, decimal_places=3)
    lifecycle_status    = EnumField(choices=InventoryLifecycleStatus.choices, default=InventoryLifecycleStatus.ACTIVE)
    exit_state          = EnumField(choices=InventoryExitState.choices, null=True, default=None)
    is_upcyclable       = models.BooleanField(default=True)
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal("1.3"))
    was_forced_archived = models.BooleanField(default=False)
    ingested_at         = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)
    archived_at         = models.DateTimeField(null=True, default=None)
    notes               = models.TextField(null=True, default=None)

    class Meta:
        db_table = "inventory_ledger"


class Subscription(models.Model):
    subscription_id   = models.AutoField(primary_key=True)
    user              = models.ForeignKey(User, on_delete=models.RESTRICT, related_name="subscriptions", db_column="user_id")
    status            = EnumField(choices=SubscriptionStatus.choices)
    subscription_tier = EnumField(choices=SubscriptionTier.choices)
    start_date        = models.DateTimeField()
    end_date          = models.DateTimeField()
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions"


class SubscriptionPayment(models.Model):
    payment_id        = models.AutoField(primary_key=True)
    subscription      = models.ForeignKey(Subscription, on_delete=models.RESTRICT, related_name="payments", db_column="subscription_id")
    amount            = models.DecimalField(max_digits=10, decimal_places=2)
    status            = EnumField(choices=PaymentStatus.choices)
    payment_reference = models.CharField(max_length=255, null=True, default=None)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscription_payments"


class AuditTrail(models.Model):
    audit_id        = models.AutoField(primary_key=True)
    actor           = models.ForeignKey(User, on_delete=models.RESTRICT, related_name="audit_events", db_column="actor_id")
    entity_type     = models.CharField(max_length=50)
    action          = models.CharField(max_length=100)
    fields_modified = models.CharField(max_length=100, null=True, default=None)
    ip_address      = models.CharField(max_length=45,  null=True, default=None)
    occurred_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_trail"


class ApiToken(models.Model):
    api_token_id = models.AutoField(primary_key=True)
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens", db_column="user_id")
    token        = models.CharField(max_length=50)
    created_at   = models.DateTimeField(auto_now_add=True)
    expires_at   = models.DateTimeField(null=True, default=None)

    class Meta:
        db_table = "api_tokens"


class Order(models.Model):
    order_id                = models.AutoField(primary_key=True)
    donation                = models.ForeignKey(Donation, on_delete=models.RESTRICT, related_name="orders", db_column="donation_id")
    lalamove_order_id       = models.CharField(max_length=50, null=True, default=None)
    status                  = EnumField(choices=OrderStatus.choices)
    dropoff_display_address = models.TextField()
    dropoff_latitude        = models.DecimalField(max_digits=18, decimal_places=15)
    dropoff_longitude       = models.DecimalField(max_digits=18, decimal_places=15)
    has_been_edited         = models.BooleanField(default=False)
    scheduled_at            = models.DateTimeField(null=True, default=None)
    expires_at              = models.DateTimeField(null=True, default=None)
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)
    no_reassigned           = TinyIntegerField(default=0, validators=[MaxValueValidator(255)])

    class Meta:
        db_table = "orders"


class OrderPayment(models.Model):
    order_payment_id  = models.AutoField(primary_key=True)
    order             = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name="payments", db_column="order_id")
    amount            = models.DecimalField(max_digits=10, decimal_places=2)
    status            = EnumField(choices=PaymentStatus.choices)
    payment_reference = models.CharField(max_length=255, null=True, default=None)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "order_payments"
