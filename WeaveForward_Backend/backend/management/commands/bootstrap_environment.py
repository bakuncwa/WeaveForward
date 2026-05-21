import os

import MySQLdb
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Bootstrap the environment once: ensure DB exists, run migrations, optionally create admin, and populate the catalog."

    def handle(self, *args, **options):
        db_name = os.getenv("DB_NAME")
        db_user = os.getenv("DB_USER", "root")
        db_password = os.getenv("DB_PASSWORD", "")
        db_host = os.getenv("DB_HOST", "127.0.0.1")
        db_port = int(os.getenv("DB_PORT", 3306))
        instance_connection_name = os.getenv("CLOUD_SQL_CONNECTION_NAME")

        if not db_name:
            raise CommandError("DB_NAME not found in environment.")

        self._ensure_database_exists(
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            db_host=db_host,
            db_port=db_port,
            instance_connection_name=instance_connection_name,
        )

        self.stdout.write("[MIGRATE] Running migrations...")
        call_command("migrate", interactive=False)

        self.stdout.write("[ADMIN] Bootstrapping admin account if ADMIN_EMAIL and ADMIN_PASSWORD are set...")
        call_command("setup_admin")

        self.stdout.write("[CATALOG] Populating product catalog...")
        call_command("populate_catalog")

        self.stdout.write(self.style.SUCCESS("Initialization complete!"))

    def _ensure_database_exists(
        self,
        *,
        db_name,
        db_user,
        db_password,
        db_host,
        db_port,
        instance_connection_name,
    ):
        try:
            if instance_connection_name:
                self.stdout.write(
                    f"[CONNECT] Connecting via Cloud SQL Socket: /cloudsql/{instance_connection_name}..."
                )
                conn = MySQLdb.connect(
                    user=db_user,
                    passwd=db_password,
                    unix_socket=f"/cloudsql/{instance_connection_name}",
                )
            else:
                self.stdout.write(f"[CONNECT] Connecting to local MySQL at {db_host}:{db_port}...")
                conn = MySQLdb.connect(
                    host=db_host,
                    user=db_user,
                    passwd=db_password,
                    port=db_port,
                )

            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
            self.stdout.write(self.style.SUCCESS(f"[OK] Database '{db_name}' is ready."))
            cursor.close()
            conn.close()
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"[ERROR] Database Creation Error: {exc}"))
            self.stdout.write("Attempting to proceed with migrations anyway...")
