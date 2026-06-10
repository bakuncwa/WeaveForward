"""Apply all pending Django database migrations to the Cloud SQL instance."""
from django.core.management import call_command


def apply() -> dict:
    call_command("migrate", interactive=False, verbosity=1)
    return {"status": "OK", "detail": "Migrations applied."}
