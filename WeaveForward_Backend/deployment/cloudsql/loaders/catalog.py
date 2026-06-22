"""
Sync the brand-fiber catalog from the CSV file into Cloud SQL.

Behaviour
─────────
- New rows   → inserted
- Rows whose is_active status differs from CSV → updated
- All other rows → untouched
"""
import csv
import os
from decimal import Decimal
from django.conf import settings


def apply() -> dict:
    from backend.models import BrandFiberLookup, BiodegTier

    csv_path = getattr(settings, "CATALOG_CSV_PATH", None) or os.environ.get("CATALOG_CSV_PATH")
    if not csv_path or not os.path.exists(csv_path):
        return {"status": "SKIP", "detail": f"Catalog CSV not found at: {csv_path}"}

    existing = {
        (obj.brand, obj.product_name, obj.clothing_type): obj
        for obj in BrandFiberLookup.objects.all()
    }

    to_create: list[BrandFiberLookup] = []
    to_update: list[BrandFiberLookup] = []

    with open(csv_path, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            brand        = row.get("brand", "Unknown")[:200]
            product_name = row.get("product_name", "Unknown")[:100]
            clothing_type = row.get("clothing_type", "Unknown")[:200]
            tier_raw     = row.get("fs_biodeg_tier", "").upper()
            biodeg_tier  = tier_raw if tier_raw in [c[0] for c in BiodegTier.choices] else None
            is_active    = row.get("is_active", "True").lower() == "true"
            key          = (brand, product_name, clothing_type)

            if key in existing:
                obj = existing[key]
                if obj.is_active != is_active:
                    obj.is_active = is_active
                    to_update.append(obj)
            else:
                to_create.append(BrandFiberLookup(
                    brand=brand,
                    product_name=product_name,
                    clothing_type=clothing_type,
                    fiber_json=row.get("fiber_json", "{}"),
                    dominant_fiber=row.get("most_dominant_fiber", "")[:200] or None,
                    biodeg_score=Decimal(row["fs_bio_share"]) if row.get("fs_bio_share") else None,
                    biodeg_tier=biodeg_tier,
                    is_active=is_active,
                ))

            if len(to_create) >= 2000:
                BrandFiberLookup.objects.bulk_create(to_create)
                to_create.clear()

    if to_create:
        BrandFiberLookup.objects.bulk_create(to_create)
    if to_update:
        BrandFiberLookup.objects.bulk_update(to_update, ["is_active"])

    return {
        "status": "OK",
        "detail": f"Catalog synced — inserted: {len(to_create)}, status-updated: {len(to_update)}",
    }
