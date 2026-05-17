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
    ApiToken,
)
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from .unclaim_donation_service import unclaim_tuab_donations, archive_donor_donations

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
        return {"status_code": 404, "detail": "Not found.", "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}


    if target_user.role == UserRole.ADMIN:
        return {"status_code": 409, "detail": "Admin users cannot be archived through this endpoint.", "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}

    if target_user.role not in (UserRole.DONOR, UserRole.TUAB):
        return {"status_code": 409, "detail": "Only Donor and TUAB users can be archived through this endpoint.", "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}

    if target_user.status == UserAccountStatus.ARCHIVED:
        return {"status_code": 409, "detail": "This user is already archived.", "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}

    changed_donations, changed_inventory_ledgers, tuab_donations = [], [], []


    if target_user.role == UserRole.TUAB:
        # Lock and load all donations claimed by this TUAB to prevent concurrency issues during archiving
        tuab_donations = list(Donation.objects.select_for_update().filter(claimed_by_tuab=target_user).order_by('donation_id'))

        # Guard: Block archiving if any claimed delivery is currently in progress (CLAIMED or IN_TRANSIT with DELIVERY method)
        in_progress = [donation for donation in tuab_donations if donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT) and donation.delivery_method == DonationDeliveryMethod.DELIVERY]
        if in_progress:
            donation_ids = ", ".join(str(donation.donation_id) for donation in in_progress)
            return {"status_code": 409, "detail": f"Archiving is not allowed while an associated delivery is in progress. Affected donation IDs: {donation_ids}", "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}


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
        # Guard: Exit early if unclaiming fails (e.g. logistics cancellation or driver assignment checks fail)
        if donation_result["detail"] is not None:
            return {"status_code": donation_result["status_code"], "detail": donation_result["detail"], "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}

        changed_donations = donation_result["changed_donations"]

        # Lock and load all active inventory ledgers linked to the TUAB's claimed donations to prevent deadlocks and race conditions
        changed_inventory_ledgers = list(InventoryLedger.objects.select_for_update().filter(source_donation__in=tuab_donations).exclude(lifecycle_status=InventoryLifecycleStatus.ARCHIVED).order_by('inventory_id'))

        # Force archive all active inventory ledgers since the TUAB is being archived
        archived_at = timezone.now()
        for ledger in changed_inventory_ledgers: ledger.lifecycle_status, ledger.was_forced_archived, ledger.archived_at, ledger.updated_at = InventoryLifecycleStatus.ARCHIVED, True, archived_at, archived_at
        InventoryLedger.objects.bulk_update(changed_inventory_ledgers, ['lifecycle_status', 'was_forced_archived', 'archived_at', 'updated_at'])
        # Cancel active subscriptions at the end of the block so it only runs if all external network calls succeed.
        active_subscriptions = list(Subscription.objects.select_for_update().filter(user=target_user, status=SubscriptionStatus.ACTIVE).order_by('subscription_id'))
        now = timezone.now()
        for subscription in active_subscriptions: subscription.status, subscription.updated_at = SubscriptionStatus.CANCELLED, now
        if active_subscriptions:
            Subscription.objects.bulk_update(active_subscriptions, ['status', 'updated_at'])

        # Save TUAB status changes and clear the local maya_card_id reference.
        target_user.status = UserAccountStatus.ARCHIVED
        target_user.maya_card_id = None
        target_user.save(update_fields=['status', 'maya_card_id', 'updated_at'])

    elif target_user.role == UserRole.DONOR:
        donor_donations = list(Donation.objects.select_for_update().filter(donor=target_user).order_by('donation_id'))
        # Guard: Block archiving if any owned delivery is currently in progress (CLAIMED or IN_TRANSIT with DELIVERY method)
        in_progress = [donation for donation in donor_donations if donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT) and donation.delivery_method == DonationDeliveryMethod.DELIVERY]
        if in_progress:
            donation_ids = ", ".join(str(donation.donation_id) for donation in in_progress)
            return {"status_code": 409, "detail": f"Archiving is not allowed while an associated delivery is in progress. Affected donation IDs: {donation_ids}", "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}

        donation_result = archive_donor_donations(donor=target_user)
        if donation_result["detail"] is not None:
            return {"status_code": donation_result["status_code"], "detail": donation_result["detail"], "changed_donations": [], "changed_inventory_ledgers": [], "user_updated": False}

        changed_donations = donation_result["changed_donations"]
        # Cancel active subscriptions at the end of the block to ensure all check guards pass first.
        active_subscriptions = list(Subscription.objects.select_for_update().filter(user=target_user, status=SubscriptionStatus.ACTIVE).order_by('subscription_id'))
        now = timezone.now()
        for subscription in active_subscriptions: subscription.status, subscription.updated_at = SubscriptionStatus.CANCELLED, now
        if active_subscriptions:
            Subscription.objects.bulk_update(active_subscriptions, ['status', 'updated_at'])

        # Save Donor status changes (Donors do not register payment details).
        target_user.status = UserAccountStatus.ARCHIVED
        target_user.maya_card_id = None
        target_user.save(update_fields=['status', 'maya_card_id', 'updated_at'])

    # Blacklist ALL SimpleJWT tokens for the user
    tokens = OutstandingToken.objects.filter(user=target_user)
    for token in tokens:
        BlacklistedToken.objects.get_or_create(token=token)

    # Delete any custom API tokens
    ApiToken.objects.filter(user=target_user).delete()

    return {
        "status_code": 204,
        "detail": None,
        "changed_donations": changed_donations,
        "changed_inventory_ledgers": changed_inventory_ledgers,
        "user_updated": True,
    }
