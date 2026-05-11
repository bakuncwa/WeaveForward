from django.db import transaction


def enable_two_factor(*, target_user, secret):
    with transaction.atomic():
        target_user.is_2fa_enabled = True
        target_user.totp_secret = secret
        target_user.save(update_fields=['is_2fa_enabled', 'totp_secret'])

    return {
        "detail": "2FA enabled successfully.",
        "fields_modified": ['is_2fa_enabled', 'totp_secret'],
    }


def disable_two_factor(*, target_user):
    with transaction.atomic():
        target_user.is_2fa_enabled = False
        target_user.totp_secret = None
        target_user.save(update_fields=['is_2fa_enabled', 'totp_secret'])

    return {
        "detail": "2FA disabled successfully.",
        "fields_modified": ['is_2fa_enabled', 'totp_secret'],
    }
