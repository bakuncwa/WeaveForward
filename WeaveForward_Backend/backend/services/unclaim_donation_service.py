from ..models import Donation, DonationDeliveryMethod, DonationStatus


def unclaim_tuab_donations(*, tuab):
    affected_donations = list(
        Donation.objects.select_for_update()
        .filter(claimed_by_tuab=tuab)
        .order_by('donation_id')
    )

    has_blocking_in_transit_delivery = any(
        donation.delivery_method == DonationDeliveryMethod.DELIVERY
        and donation.status == DonationStatus.IN_TRANSIT
        for donation in affected_donations
    )
    if has_blocking_in_transit_delivery:
        return {
            "status_code": 400,
            "detail": "Archiving is not allowed while an associated delivery donation is in transit.",
            "changed_donations": [],
        }

    changed_donations = []
    for donation in affected_donations:
        is_claimed_pickup = (
            donation.status == DonationStatus.CLAIMED
            and donation.delivery_method == DonationDeliveryMethod.PICKUP
        )
        is_in_transit_pickup = (
            donation.status == DonationStatus.IN_TRANSIT
            and donation.delivery_method == DonationDeliveryMethod.PICKUP
        )
        is_claimed_delivery = (
            donation.status == DonationStatus.CLAIMED
            and donation.delivery_method == DonationDeliveryMethod.DELIVERY
        )

        if not (is_claimed_pickup or is_in_transit_pickup or is_claimed_delivery):
            continue

        if is_claimed_delivery:
            # Future feature: cancel the Lalamove delivery through its API endpoint here.
            pass

        donation.claimed_by_tuab = None
        donation.delivery_method = None
        donation.status = DonationStatus.PENDING
        changed_donations.append(donation)

    if changed_donations:
        Donation.objects.bulk_update(
            changed_donations,
            ['claimed_by_tuab', 'delivery_method', 'status'],
        )

    return {
        "status_code": 204,
        "detail": None,
        "changed_donations": changed_donations,
    }
