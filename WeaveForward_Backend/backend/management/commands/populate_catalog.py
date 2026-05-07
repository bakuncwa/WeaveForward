import csv
import os
from django.core.management.base import BaseCommand
from backend.models import BrandFiberLookup, BiodegTier
from decimal import Decimal

class Command(BaseCommand):
    help = 'Populates the BrandFiberLookup table from the webscraped catalog archive CSV.'

    def handle(self, *args, **options):
        csv_path = os.path.join('backend', 'data', 'webscraped_data', 'webscraped_catalog_archive.csv')
        
        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f'CSV file not found at {csv_path}'))
            return

        self.stdout.write(self.style.SUCCESS(f'Populating database from {csv_path}...'))

        # Clear existing data to avoid duplicates
        BrandFiberLookup.objects.all().delete()

        lookups_to_create = []
        
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Map CSV fields to model fields
                tier_raw = row.get('fs_biodeg_tier', '').upper()
                # Validate tier against Enum
                biodeg_tier = None
                if tier_raw in [choice[0] for choice in BiodegTier.choices]:
                    biodeg_tier = tier_raw

                # Clean up boolean
                is_active = row.get('is_active', 'True').lower() == 'true'

                # Truncate strings to match model max_lengths
                category = row.get('product_name', 'Unknown')[:100]
                brand = row.get('brand', 'Unknown')[:200]
                clothing_type = row.get('clothing_type', 'Unknown')[:200]
                dominant_fiber = row.get('most_dominant_fiber')
                if dominant_fiber:
                    dominant_fiber = dominant_fiber[:200]

                lookups_to_create.append(BrandFiberLookup(
                    category=category,
                    brand=brand,
                    clothing_type=clothing_type,
                    fiber_json=row.get('fiber_json', '{}'),
                    dominant_fiber=dominant_fiber,
                    biodeg_score=Decimal(row.get('fs_bio_share', 0)) if row.get('fs_bio_share') else None,
                    biodeg_tier=biodeg_tier,
                    is_active=is_active
                ))

                # Bulk create in chunks to avoid memory issues
                if len(lookups_to_create) >= 1000:
                    BrandFiberLookup.objects.bulk_create(lookups_to_create)
                    lookups_to_create = []

        # Create remaining items
        if lookups_to_create:
            BrandFiberLookup.objects.bulk_create(lookups_to_create)

        self.stdout.write(self.style.SUCCESS('Successfully populated BrandFiberLookup table!'))
