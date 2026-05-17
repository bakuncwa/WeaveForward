from django.utils import timezone
from ..models import Donation, DonationDeliveryMethod, DonationStatus


def unclaim_tuab_donations(*, tuab):
    # Lock and load all donations claimed by this TUAB to prevent race conditions and deadlocks during unclaiming
    affected_donations = list(Donation.objects.select_for_update().filter(claimed_by_tuab=tuab).order_by('donation_id'))

    # Guard: Block archiving if any claimed delivery is currently in progress (CLAIMED or IN_TRANSIT with DELIVERY method)
    if any(donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT) and donation.delivery_method == DonationDeliveryMethod.DELIVERY for donation in affected_donations):
        return {
            "status_code": 409,
            "detail": "Archiving is not allowed while an associated delivery is in progress.",
            "changed_donations": [],
        }

    for donation in affected_donations:
        # Case 1: Claimed Pickup (safe to unclaim directly)
        if donation.status == DonationStatus.CLAIMED and donation.delivery_method == DonationDeliveryMethod.PICKUP:
            donation.claimed_by_tuab = None
            donation.delivery_method = None
            donation.status = DonationStatus.PENDING
            donation.updated_at = timezone.now()
            donation.save(update_fields=['claimed_by_tuab', 'delivery_method', 'status', 'updated_at'])

        # Case 2: In-Transit Pickup (self-pickup, safe to unclaim directly)
        elif donation.status == DonationStatus.IN_TRANSIT and donation.delivery_method == DonationDeliveryMethod.PICKUP:
            donation.claimed_by_tuab = None
            donation.delivery_method = None
            donation.status = DonationStatus.PENDING
            donation.updated_at = timezone.now()
            donation.save(update_fields=['claimed_by_tuab', 'delivery_method', 'status', 'updated_at'])

    return {
        "status_code": 204,
        "detail": None,
        "changed_donations": [donation for donation in affected_donations if donation.claimed_by_tuab is None],
    }


def archive_donor_donations(*, donor):
    # Lock and load all donations owned by this Donor to prevent concurrency issues during archiving
    affected_donations = list(Donation.objects.select_for_update().filter(donor=donor).order_by('donation_id'))

    # Guard: Block archiving if any owned delivery is currently in progress (CLAIMED or IN_TRANSIT with DELIVERY method)
    if any(donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT) and donation.delivery_method == DonationDeliveryMethod.DELIVERY for donation in affected_donations):
        return {
            "status_code": 409,
            "detail": "Archiving is not allowed while an associated delivery is in progress.",
            "changed_donations": [],
        }

    for donation in affected_donations:
        # Case 1: Pending Donation (safe to archive directly)
        if donation.status == DonationStatus.PENDING:
            donation.status = DonationStatus.ARCHIVED
            donation.updated_at = timezone.now()
            donation.save(update_fields=['status', 'updated_at'])

        # Case 2: Claimed or In-Transit Pickup Donation (pickup method, safe to archive directly)
        elif (
            donation.status in (DonationStatus.CLAIMED, DonationStatus.IN_TRANSIT)
            and donation.delivery_method == DonationDeliveryMethod.PICKUP
        ):
            donation.status = DonationStatus.ARCHIVED
            donation.updated_at = timezone.now()
            donation.save(update_fields=['status', 'updated_at'])

    return {
        "status_code": 204,
        "detail": None,
        "changed_donations": [donation for donation in affected_donations if donation.status == DonationStatus.ARCHIVED],
    }
