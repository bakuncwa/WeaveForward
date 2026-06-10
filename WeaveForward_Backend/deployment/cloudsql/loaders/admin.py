"""Seed or update the admin account from ADMIN_EMAIL / ADMIN_PASSWORD env vars."""
import os


def apply() -> dict:
    from backend.models import User, UserRole, UserAccountStatus

    email    = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")

    if not email or not password:
        return {"status": "SKIP", "detail": "ADMIN_EMAIL or ADMIN_PASSWORD not set — skipping admin seed."}

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "role":       UserRole.ADMIN,
            "status":     UserAccountStatus.ACTIVE,
            "contact_no": "00000000000",
        },
    )
    user.set_password(password)
    user.save()

    action = "created" if created else "password updated"
    return {"status": "OK", "detail": f"Admin user {action}: {email}"}
