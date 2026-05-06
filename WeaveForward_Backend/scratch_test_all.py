import os
import sys
import django
from django.core.files.uploadedfile import SimpleUploadedFile

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "WeaveForward_Backend.settings")
django.setup()

from backend.serializers import DonorRegisterSerializer, TUABRegisterSerializer

# Helper function to print results cleanly
def run_test(name, serializer_class, payload, files=None, expected_success=True, expected_error_key=None):
    if files:
        # SimpleUploadedFile mocks a file upload. We wrap payload and files manually or use data/files.
        # But serializers just take a dict where files are values
        data = payload.copy()
        data.update(files)
        serializer = serializer_class(data=data)
    else:
        serializer = serializer_class(data=payload)
        
    is_valid = serializer.is_valid()
    
    if is_valid == expected_success:
        if not expected_success and expected_error_key and expected_error_key not in serializer.errors:
            print(f"❌ [FAIL] {name}: Failed as expected, but wrong error key! Expected '{expected_error_key}', got {serializer.errors}")
            return False
        print(f"✅ [PASS] {name}")
        return True
    else:
        print(f"❌ [FAIL] {name}: Expected {expected_success}, got {is_valid}. Errors: {serializer.errors if not is_valid else 'None'}")
        return False

# Base payloads that are VALID
donor_base = {
    'first_name': 'Valid',
    'last_name': 'Donor',
    'email': 'valid_donor@test.com',
    'contact_no': '+639150812228',
    'password': 'ValidPassword1',
    'confirm_password': 'ValidPassword1',
    'latitude': '14.5995120',  # Exactly 7 decimals
    'longitude': '120.9842220', # Exactly 7 decimals
    'display_address': 'Manila'
}

# Create a mock valid PDF and Image
valid_pdf = SimpleUploadedFile("doc.pdf", b"file_content", content_type="application/pdf")
invalid_exe = SimpleUploadedFile("virus.exe", b"bad_content", content_type="application/x-msdownload")
large_pdf = SimpleUploadedFile("huge.pdf", b"0" * (51 * 1024 * 1024), content_type="application/pdf") # 51 MB

tuab_base = {
    'business_name': 'Valid Business',
    'email': 'valid_tuab@test.com',
    'contact_no': '+639150812228',
    'password': 'ValidPassword1',
    'confirm_password': 'ValidPassword1',
    'latitude': '14.5995120',
    'longitude': '120.9842220',
    'display_address': 'Manila',
    'target_fibers': 'cotton,polyester',
    'max_distance_km': '10.5',
    'min_biodeg_score': '50.0'
}

print("\n==== RUNNING EXTENSIVE VALIDATION SUITE ====\n")

tests = [
    # ---- DONOR TESTS ----
    ("Donor: Perfect Payload", DonorRegisterSerializer, donor_base, None, True, None),
    ("Donor: Passwords don't match", DonorRegisterSerializer, {**donor_base, 'confirm_password': 'Mismatch!1'}, None, False, 'password'),
    ("Donor: Password too short", DonorRegisterSerializer, {**donor_base, 'password': 'A1', 'confirm_password': 'A1'}, None, False, 'password'),
    ("Donor: Password no letters", DonorRegisterSerializer, {**donor_base, 'password': '1234567890', 'confirm_password': '1234567890'}, None, False, 'password'),
    ("Donor: Password no numbers", DonorRegisterSerializer, {**donor_base, 'password': 'PasswordOnly', 'confirm_password': 'PasswordOnly'}, None, False, 'password'),
    ("Donor: Phone bad prefix", DonorRegisterSerializer, {**donor_base, 'contact_no': '09150812228'}, None, False, 'phone'),
    ("Donor: Phone wrong length", DonorRegisterSerializer, {**donor_base, 'contact_no': '+6391508122'}, None, False, 'phone'),
    ("Donor: Location wrong decimals (lat)", DonorRegisterSerializer, {**donor_base, 'latitude': '14.599'}, None, False, 'location'),
    ("Donor: Location wrong decimals (lng)", DonorRegisterSerializer, {**donor_base, 'longitude': '120.98422200'}, None, False, 'location'),
    ("Donor: Outside NCR (Antipolo)", DonorRegisterSerializer, {**donor_base, 'latitude': '14.6212120', 'longitude': '121.1684340'}, None, False, 'location'),

    # ---- TUAB TESTS ----
    ("TUAB: Perfect Payload with File", TUABRegisterSerializer, tuab_base, {'documentation': valid_pdf}, True, None),
    ("TUAB: Perfect Payload without File", TUABRegisterSerializer, tuab_base, None, True, None),
    ("TUAB: Passwords don't match", TUABRegisterSerializer, {**tuab_base, 'confirm_password': 'Wrong1'}, None, False, 'password'),
    ("TUAB: Password too short", TUABRegisterSerializer, {**tuab_base, 'password': '123', 'confirm_password': '123'}, None, False, 'password'),
    ("TUAB: Invalid Fiber Format (spaces)", TUABRegisterSerializer, {**tuab_base, 'target_fibers': 'cotton, polyester'}, None, False, 'target_fibers'),
    ("TUAB: Invalid Fiber Format (uppercase)", TUABRegisterSerializer, {**tuab_base, 'target_fibers': 'Cotton,polyester'}, None, False, 'target_fibers'),
    ("TUAB: Non-whitelist Fiber", TUABRegisterSerializer, {**tuab_base, 'target_fibers': 'cotton,adamantium'}, None, False, 'target_fibers'),
    ("TUAB: Outside NCR (Antipolo)", TUABRegisterSerializer, {**tuab_base, 'latitude': '14.6212120', 'longitude': '121.1684340'}, None, False, 'location'),
    ("TUAB: File Extension Invalid", TUABRegisterSerializer, tuab_base, {'documentation': invalid_exe}, False, 'documentation'),
    # Note: large_pdf test might eat RAM, but let's test it
    ("TUAB: File Too Large (>50MB)", TUABRegisterSerializer, tuab_base, {'documentation': large_pdf}, False, 'documentation'),
]

passed = 0
for test in tests:
    if run_test(*test):
        passed += 1

print(f"\n==== SUITE COMPLETE: {passed}/{len(tests)} TESTS PASSED ====\n")
