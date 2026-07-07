import base64
import hashlib

from cryptography.hazmat.primitives.keywrap import aes_key_wrap, aes_key_unwrap
from django.conf import settings
from django.db import transaction


def encrypt_totp(secret):
    kek = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.b64encode(aes_key_wrap(kek, secret.encode('ascii'))).decode()

def decrypt_totp(encrypted):
    kek = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return aes_key_unwrap(kek, base64.b64decode(encrypted)).decode('ascii')


def enable_two_factor(*, target_user, secret):
    with transaction.atomic():
        target_user.is_2fa_enabled = True
        target_user.totp_secret = encrypt_totp(secret)
        target_user.save(update_fields=['is_2fa_enabled', 'totp_secret', 'updated_at'])

    return {
        "detail": "2FA enabled successfully.",
        "fields_modified": ['is_2fa_enabled', 'totp_secret'],
        "user": target_user
    }


def disable_two_factor(*, target_user):
    with transaction.atomic():
        target_user.is_2fa_enabled = False
        target_user.totp_secret = None
        target_user.save(update_fields=['is_2fa_enabled', 'totp_secret', 'updated_at'])

    return {
        "detail": "2FA disabled successfully.",
        "fields_modified": ['is_2fa_enabled', 'totp_secret'],
        "user": target_user
    }
