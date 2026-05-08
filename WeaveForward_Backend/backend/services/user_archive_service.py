from dataclasses import dataclass, field

from django.utils import timezone

from ..models import (
    Donation,
    DonationDeliveryMethod,
    DonationStatus,
    InventoryLedger,
    InventoryLifecycleStatus,
    Subscription,
    SubscriptionStatus,
    User,
    UserAccountStatus,
    UserRole,
)


ARCHIVE_BLOCKED_IN_TRANSIT_MESSAGE = (
    "Archiving is not allowed while an associated delivery donation is in transit."
)
ARCHIVE_ADMIN_TARGET_MESSAGE = "Admin users cannot be archived through this endpoint."
ARCHIVE_UNSUPPORTED_ROLE_MESSAGE = (
    "Only Donor and TUAB users can be archived through this endpoint."
)


@dataclass
class ArchiveUserResult:
    status_code: int
    detail: str | None = None
    user: User | None = None
    changed_donations: list = field(default_factory=list)
    changed_inventory_ledgers: list = field(default_factory=list)
    user_updated: bool = False


def archive_user(*, target_user_id):
    result = ArchiveUserResult(status_code=204)

    try:
        target_user = User.objects.select_for_update().get(pk=target_user_id)
    except User.DoesNotExist:
        return ArchiveUserResult(status_code=404, detail="Not found.")

    if target_user.role == UserRole.ADMIN:
        return ArchiveUserResult(status_code=400, detail=ARCHIVE_ADMIN_TARGET_MESSAGE)

    if target_user.role not in (UserRole.DONOR, UserRole.TUAB):
        return ArchiveUserResult(status_code=400, detail=ARCHIVE_UNSUPPORTED_ROLE_MESSAGE)

    result.user = target_user
    if target_user.status == UserAccountStatus.ARCHIVED:
        return result

    donation_filter = (
        {'donor': target_user}
        if target_user.role == UserRole.DONOR
        else {'claimed_by_tuab': target_user}
    )
    affected_donations = list(Donation.objects.select_for_update().filter(**donation_filter).order_by('donation_id'))
    active_subscriptions = list(
        Subscription.objects.select_for_update()
        .filter(user=target_user, status=SubscriptionStatus.ACTIVE)
        .order_by('subscription_id')
    )

    has_blocking_in_transit_delivery = any(
        donation.delivery_method == DonationDeliveryMethod.DELIVERY
        and donation.status == DonationStatus.IN_TRANSIT
        for donation in affected_donations
    )
    if has_blocking_in_transit_delivery:
        return ArchiveUserResult(status_code=400, detail=ARCHIVE_BLOCKED_IN_TRANSIT_MESSAGE)

    for donation in affected_donations:
        if donation.status not in (DonationStatus.PENDING, DonationStatus.CLAIMED):
            continue

        if (
            donation.status == DonationStatus.CLAIMED
            and donation.delivery_method == DonationDeliveryMethod.DELIVERY
        ):
            # Future feature: cancel the Lalamove delivery through its API endpoint here.
            pass

        donation.status = DonationStatus.ARCHIVED
        result.changed_donations.append(donation)

    if result.changed_donations:
        Donation.objects.bulk_update(result.changed_donations, ['status'])

    for subscription in active_subscriptions:
        subscription.status = SubscriptionStatus.CANCELLED
    if active_subscriptions:
        Subscription.objects.bulk_update(active_subscriptions, ['status'])

    if target_user.role == UserRole.TUAB and result.changed_donations:
        result.changed_inventory_ledgers = list(
            InventoryLedger.objects.select_for_update()
            .filter(source_donation__in=result.changed_donations)
            .order_by('inventory_id')
        )
        archived_at = timezone.now()
        for ledger in result.changed_inventory_ledgers:
            ledger.lifecycle_status = InventoryLifecycleStatus.ARCHIVED
            ledger.was_forced_archived = True
            ledger.archived_at = archived_at
        if result.changed_inventory_ledgers:
            InventoryLedger.objects.bulk_update(
                result.changed_inventory_ledgers,
                ['lifecycle_status', 'was_forced_archived', 'archived_at']
            )

    target_user.status = UserAccountStatus.ARCHIVED
    target_user.maya_customer_id = None
    target_user.maya_card_id = None
    target_user.save(update_fields=['status', 'maya_customer_id', 'maya_card_id', 'updated_at'])

    result.user_updated = True
    return result
