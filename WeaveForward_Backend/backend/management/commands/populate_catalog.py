import csv
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from backend.models import BrandFiberLookup, BiodegTier
from decimal import Decimal

class Command(BaseCommand):
    help = 'Bulk Upserts BrandFiberLookup table from CSV, handling truncation and status flips.'

    def handle(self, *args, **options):
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
