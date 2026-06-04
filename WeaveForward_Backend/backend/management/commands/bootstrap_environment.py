import os
import csv
from decimal import Decimal

import MySQLdb
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from backend.models import BrandFiberLookup, BiodegTier, User, UserAccountStatus, UserRole


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
        self._setup_admin()

        self.stdout.write("[CATALOG] Populating product catalog...")
        self._populate_catalog()

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

    def _setup_admin(self):
        email = os.getenv('ADMIN_EMAIL')
        password = os.getenv('ADMIN_PASSWORD')

        # Note: We use email as the username in this project
        if not email or not password:
            self.stdout.write(self.style.WARNING('ADMIN_EMAIL or ADMIN_PASSWORD not set. Skipping admin setup.'))
            return

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'role': UserRole.ADMIN,
                'status': UserAccountStatus.ACTIVE,
                'contact_no': '00000000000' # Required field
            }
        )

        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f'Admin user created: {email}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Admin user password updated: {email}'))

    def _populate_catalog(self):
        # Use settings for the CSV path
        csv_path = settings.CATALOG_CSV_PATH

        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f'CSV file not found at {csv_path}'))
            return

        self.stdout.write(self.style.SUCCESS(f'Synchronizing database with {csv_path}...'))

        # 1. Load existing records into memory for fast lookup
        # Key: (brand, category, clothing_type)
        existing_map = {
            (obj.brand, obj.category, obj.clothing_type): obj 
            for obj in BrandFiberLookup.objects.all()
        }

        lookups_to_create = []
        lookups_to_update = []

        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Map and Truncate
                brand = row.get('brand', 'Unknown')[:200]
                category = row.get('product_name', 'Unknown')[:100] # Truncated to match model
                clothing_type = row.get('clothing_type', 'Unknown')[:200]

                # Cleanup tier
                tier_raw = row.get('fs_biodeg_tier', '').upper()
                biodeg_tier = tier_raw if tier_raw in [c[0] for c in BiodegTier.choices] else None

                # Cleanup boolean
                is_active_csv = row.get('is_active', 'True').lower() == 'true'
                key = (brand, category, clothing_type)

                if key in existing_map:
                    obj = existing_map[key]
                    # Check if status has flipped
                    if obj.is_active != is_active_csv:
                        obj.is_active = is_active_csv
                        lookups_to_update.append(obj)
                else:
                    # Create new
                    lookups_to_create.append(BrandFiberLookup(
                        brand=brand,
                        category=category,
                        clothing_type=clothing_type,
                        fiber_json=row.get('fiber_json', '{}'),
                        dominant_fiber=row.get('most_dominant_fiber')[:200] if row.get('most_dominant_fiber') else None,
                        biodeg_score=Decimal(row.get('fs_bio_share', 0)) if row.get('fs_bio_share') else None,
                        biodeg_tier=biodeg_tier,
                        is_active=is_active_csv
                    ))

                # Periodic flush for memory safety
                if len(lookups_to_create) >= 2000:
                    BrandFiberLookup.objects.bulk_create(lookups_to_create)
                    lookups_to_create = []

        # Final batch processing
        if lookups_to_create:
            BrandFiberLookup.objects.bulk_create(lookups_to_create)

        if lookups_to_update:
            BrandFiberLookup.objects.bulk_update(lookups_to_update, ['is_active'])

        self.stdout.write(self.style.SUCCESS(
            f'Sync Complete! Created: {len(lookups_to_create) + (BrandFiberLookup.objects.count() - len(existing_map))}, '
            f'Updated (status flipped): {len(lookups_to_update)}'
        ))
