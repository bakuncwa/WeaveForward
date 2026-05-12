from django.utils import timezone
import requests
from django.conf import settings

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
from .unclaim_donation_service import unclaim_tuab_donations

# Archive rules:
# - Donor archive:
#   - Reject the archive if any donor-owned donation is IN_TRANSIT with DELIVERY.
#   - Archive donor-owned donations in these cases:
#     - PENDING
#     - CLAIMED with PICKUP
#     - IN_TRANSIT with PICKUP
#     - CLAIMED with DELIVERY
#   - Leave other donation statuses unchanged.
# - TUAB archive:
#   - Reject the archive if any claimed donation is IN_TRANSIT with DELIVERY.
#   - Unclaim claimed donations in these cases:
#     - CLAIMED with PICKUP
#     - IN_TRANSIT with PICKUP
#     - CLAIMED with DELIVERY
#   - For those unclaimed donations:
#     - reset status to PENDING
#     - clear claimed_by_tuab
#     - clear delivery_method
#   - Archive all non-archived inventory ledgers linked to the TUAB's claimed
#     donations as loaded before unclaiming.
# - Both roles:
#   - Cancel ACTIVE subscriptions.
#   - Preserve maya_customer_id and clear maya_card_id.
#   - Set the user status to ARCHIVED.

def archive_user(*, target_user_id):
    try:
        target_user = User.objects.select_for_update().get(pk=target_user_id)
    except User.DoesNotExist:
        return {
            "status_code": 404,
            "detail": "Not found.",
            "changed_donations": [],
            "changed_inventory_ledgers": [],
            "user_updated": False,
        }

    if target_user.role == UserRole.ADMIN:
        return {
            "status_code": 400,
            "detail": "Admin users cannot be archived through this endpoint.",
            "changed_donations": [],
            "changed_inventory_ledgers": [],
            "user_updated": False,
        }

    if target_user.role not in (UserRole.DONOR, UserRole.TUAB):
        return {
            "status_code": 400,
            "detail": "Only Donor and TUAB users can be archived through this endpoint.",
            "changed_donations": [],
            "changed_inventory_ledgers": [],
            "user_updated": False,
        }

    if target_user.status == UserAccountStatus.ARCHIVED:
        return {
            "status_code": 204,
            "detail": None,
            "changed_donations": [],
            "changed_inventory_ledgers": [],
            "user_updated": False,
        }

    active_subscriptions = list(
        Subscription.objects.select_for_update()
        .filter(user=target_user, status=SubscriptionStatus.ACTIVE)
        .order_by('subscription_id')
    )
    changed_donations = []
    changed_inventory_ledgers = []
    tuab_donations = []

    if target_user.role == UserRole.TUAB:
        tuab_donations = list(
            Donation.objects.select_for_update()
            .filter(claimed_by_tuab=target_user)
            .order_by('donation_id')
        )
        has_blocking_in_transit_delivery = any(
            donation.delivery_method == DonationDeliveryMethod.DELIVERY
            and donation.status == DonationStatus.IN_TRANSIT
            for donation in tuab_donations
        )
        if has_blocking_in_transit_delivery:
            return {
                "status_code": 400,
                "detail": "Archiving is not allowed while an associated delivery donation is in transit.",
                "changed_donations": [],
                "changed_inventory_ledgers": [],
                "user_updated": False,
            }

        if target_user.maya_customer_id and target_user.maya_card_id:
            base_url = settings.MAYA_SANDBOX_BASE_URL.rstrip('/')
            try:
                delete_response = requests.delete(
                    f"{base_url}/customers/{target_user.maya_customer_id}/cards/{target_user.maya_card_id}",
                    headers={
                        'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                    },
                    timeout=30,
                )
            except requests.RequestException as exc:
                return {
                    "status_code": 502,
                    "detail": f"Maya card deletion failed: {exc}",
                    "changed_donations": [],
                    "changed_inventory_ledgers": [],
                    "user_updated": False,
                }
            if delete_response.status_code != 200:
                try:
                    delete_payload = delete_response.json()
                    delete_error = (
                        delete_payload.get('error') or delete_payload.get('message') or delete_payload.get('detail') or str(delete_payload)
                        if isinstance(delete_payload, dict) else str(delete_payload)
                    )
                except ValueError:
                    delete_error = delete_response.text or "Maya request failed."
                return {
                    "status_code": 502,
                    "detail": f"Maya card deletion failed: {delete_error}",
                    "changed_donations": [],
                    "changed_inventory_ledgers": [],
                    "user_updated": False,
                }

        donation_result = unclaim_tuab_donations(tuab=target_user)
        if donation_result["detail"] is not None:
            return {
                "status_code": donation_result["status_code"],
                "detail": donation_result["detail"],
                "changed_donations": [],
                "changed_inventory_ledgers": [],
                "user_updated": False,
            }
        changed_donations = donation_result["changed_donations"]
    else:
        donor_donations = list(
            Donation.objects.select_for_update()
            .filter(donor=target_user)
            .order_by('donation_id')
        )
        has_blocking_in_transit_delivery = any(
            donation.delivery_method == DonationDeliveryMethod.DELIVERY
            and donation.status == DonationStatus.IN_TRANSIT
            for donation in donor_donations
        )
        if has_blocking_in_transit_delivery:
            return {
                "status_code": 400,
                "detail": "Archiving is not allowed while an associated delivery donation is in transit.",
                "changed_donations": [],
                "changed_inventory_ledgers": [],
                "user_updated": False,
            }

        if target_user.maya_customer_id and target_user.maya_card_id:
            base_url = settings.MAYA_SANDBOX_BASE_URL.rstrip('/')
            try:
                delete_response = requests.delete(
                    f"{base_url}/customers/{target_user.maya_customer_id}/cards/{target_user.maya_card_id}",
                    headers={
                        'Authorization': settings.MAYA_SANDBOX_SECRET_BASIC_AUTH,
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                    },
                    timeout=30,
                )
            except requests.RequestException as exc:
                return {
                    "status_code": 502,
                    "detail": f"Maya card deletion failed: {exc}",
                    "changed_donations": [],
                    "changed_inventory_ledgers": [],
                    "user_updated": False,
                }
            if delete_response.status_code != 200:
                try:
                    delete_payload = delete_response.json()
                    delete_error = (
                        delete_payload.get('error') or delete_payload.get('message') or delete_payload.get('detail') or str(delete_payload)
                        if isinstance(delete_payload, dict) else str(delete_payload)
                    )
                except ValueError:
                    delete_error = delete_response.text or "Maya request failed."
                return {
                    "status_code": 502,
                    "detail": f"Maya card deletion failed: {delete_error}",
                    "changed_donations": [],
                    "changed_inventory_ledgers": [],
                    "user_updated": False,
                }

        for donation in donor_donations:
            if donation.status == DonationStatus.PENDING:
                donation.status = DonationStatus.ARCHIVED
            elif (
                donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT)
                and donation.delivery_method == DonationDeliveryMethod.PICKUP
            ):
                donation.status = DonationStatus.ARCHIVED
            elif (
                donation.status == DonationStatus.CLAIMED
                and donation.delivery_method == DonationDeliveryMethod.DELIVERY
            ):
                # Future feature: cancel the Lalamove delivery through its API endpoint here.
                donation.status = DonationStatus.ARCHIVED
            else:
                continue

            changed_donations.append(donation)

        if changed_donations:
            Donation.objects.bulk_update(changed_donations, ['status'])

    if tuab_donations:
        changed_inventory_ledgers = list(
            InventoryLedger.objects.select_for_update()
            .filter(source_donation__in=tuab_donations)
            .exclude(lifecycle_status=InventoryLifecycleStatus.ARCHIVED)
            .order_by('inventory_id')
        )
        archived_at = timezone.now()
        for ledger in changed_inventory_ledgers:
            ledger.lifecycle_status = InventoryLifecycleStatus.ARCHIVED
            ledger.was_forced_archived = True
            ledger.archived_at = archived_at
        if changed_inventory_ledgers:
            InventoryLedger.objects.bulk_update(
                changed_inventory_ledgers,
                ['lifecycle_status', 'was_forced_archived', 'archived_at']
            )

    for subscription in active_subscriptions:
        subscription.status = SubscriptionStatus.CANCELLED
    if active_subscriptions:
        Subscription.objects.bulk_update(active_subscriptions, ['status'])

    target_user.status = UserAccountStatus.ARCHIVED
    target_user.maya_card_id = None
    target_user.save(update_fields=['status', 'maya_card_id', 'updated_at'])

    return {
        "status_code": 204,
        "detail": None,
        "changed_donations": changed_donations,
        "changed_inventory_ledgers": changed_inventory_ledgers,
        "user_updated": True,
    }
