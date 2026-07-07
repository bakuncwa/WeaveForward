from django.utils import timezone
from django.core.files.storage import default_storage
from django.db.models import Value, Max, Subquery, OuterRef, Exists
from django.db.models.functions import Concat

from ..models import (
    Donation,
    Order, OrderPayment,
    Subscription, SubscriptionPayment,
    User, UserRole, UserAccountStatus,
    AuditTrail,
)


_TEN_YEARS = timezone.timedelta(days=3650)   # BIR RR 17-2013 — payment records only


def run_data_retention():
    result = {}
    archived_user_ids = _anonymize_users()
    result['anonymized_users'] = len(archived_user_ids)
    if archived_user_ids:
        result.update(_anonymize_locations(archived_user_ids))
        result.update(_anonymize_payments(archived_user_ids))
    return result


def _anonymize_user(user):
    user.first_name = None
    user.last_name = None
    user.middle_name = None
    user.business_name = None
    user.description = None
    user.social_link = None
    user.barangay = None
    user.display_address = None
    user.latitude = None
    user.longitude = None
    user.totp_secret = None
    if user.upload:
        if user.upload.file_path:
            default_storage.delete(user.upload.file_path)
        user.upload.delete()
    if user.documentation:
        if user.documentation.file_path:
            default_storage.delete(user.documentation.file_path)
        user.documentation.delete()
    user.upload = None
    user.documentation = None
    user.maya_customer_id = None
    user.maya_card_id = None
    user.max_active_claims = None
    user.target_fibers = None
    user.min_biodeg_score = None
    user.max_distance_km = None
    user.operational_status = None
    user.rejection_reason = None
    user.contact_no = f'ANON{user.user_id}'
    user.email = f'deleted-{user.user_id}@weaveforward.ph'
    user.set_unusable_password()
    user.save(update_fields=[
        'first_name', 'last_name', 'middle_name',
        'business_name', 'description', 'social_link',
        'barangay', 'display_address', 'latitude', 'longitude',
        'totp_secret', 'upload', 'documentation',
        'maya_customer_id', 'maya_card_id',
        'max_active_claims', 'target_fibers',
        'min_biodeg_score', 'max_distance_km',
        'operational_status', 'rejection_reason',
        'contact_no', 'password', 'email', 'updated_at',
    ])


def _anonymize_users():
    cutoff = timezone.now() - timezone.timedelta(days=730)
    bir_cutoff = timezone.now() - _TEN_YEARS  # payment history still needs BIR-length lookback

    last_log_subquery = AuditTrail.objects.filter(
        actor=OuterRef('pk'),
    ).values('actor').annotate(
        last=Max('occurred_at'),
    ).values('last')

    recent_orders_as_tuab = Order.objects.filter(
        donation__claimed_by_tuab=OuterRef('pk'),
        created_at__gte=bir_cutoff,
    )
    recent_subscriptions = Subscription.objects.filter(
        user=OuterRef('pk'),
        created_at__gte=bir_cutoff,
    )

    users = User.objects.filter(
        status=UserAccountStatus.ARCHIVED,
        role__in=[UserRole.DONOR, UserRole.TUAB],
    ).annotate(
        last_audit=Subquery(last_log_subquery),
    ).filter(
        last_audit__lt=cutoff,
    ).exclude(
        email__startswith='deleted-',
    ).exclude(
        Exists(recent_orders_as_tuab),
    ).exclude(
        Exists(recent_subscriptions),
    )

    anonymized_ids = []
    for user in users:
        _anonymize_user(user)
        anonymized_ids.append(user.user_id)

    return anonymized_ids


def _anonymize_locations(archived_user_ids):
    donation_count = Donation.objects.filter(
        donor__in=archived_user_ids,
        status__in=['RECEIVED', 'REJECTED', 'CANCELLED', 'ARCHIVED'],
    ).exclude(
        pickup_latitude=0, pickup_longitude=0,
    ).update(
        pickup_latitude=0,
        pickup_longitude=0,
        pickup_display_address=Concat('pickup_barangay', Value(', '), 'pickup_city'),
    )

    order_count = Order.objects.filter(
        donation__claimed_by_tuab__in=archived_user_ids,
        status__in=['COMPLETED', 'CANCELLED', 'FAILED'],
    ).exclude(
        dropoff_latitude=0, dropoff_longitude=0,
    ).update(
        dropoff_latitude=0,
        dropoff_longitude=0,
        dropoff_display_address='',
    )

    return {'donations_scrubbed': donation_count, 'orders_scrubbed': order_count}


def _anonymize_payments(archived_user_ids):
    order_count = Order.objects.filter(
        donation__claimed_by_tuab__in=archived_user_ids,
    ).exclude(
        lalamove_order_id__isnull=True,
    ).update(
        lalamove_order_id=None,
    )

    order_payment_count = OrderPayment.objects.filter(
        order__donation__claimed_by_tuab__in=archived_user_ids,
    ).exclude(
        payment_reference__isnull=True,
    ).update(
        payment_reference=None,
        amount=0,
        status='FAILED',
    )

    sub_payment_count = SubscriptionPayment.objects.filter(
        subscription__user__in=archived_user_ids,
    ).exclude(
        payment_reference__isnull=True,
    ).update(
        payment_reference=None,
        amount=0,
        status='FAILED',
    )

    return {
        'orders_payment_scrubbed': order_count,
        'order_payments_scrubbed': order_payment_count,
        'sub_payments_scrubbed': sub_payment_count,
    }
