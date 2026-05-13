import csv

file_path = 'backend/data/webscraped_data/20260425-002653-webscraped_catalog_archive.csv'
brands_to_check = ['Giordano PH', 'Levis PH', "Levi's"]

with open(file_path, mode='r', encoding='utf-8') as f:
    reader = csv.reader(f)
    next(reader) # skip header
    found = set()
    for row in reader:
        if not row: continue
        brand = row[0]
        for target in brands_to_check:
            if brand.strip() == target:
                if brand not in found:
                    print(f"Found: '{brand}' | Length: {len(brand)} | Stripped Length: {len(brand.strip())}")
                    found.add(brand)
