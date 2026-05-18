import os
import json
import time
import random
import string
import requests
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

def get_random_string(length=8):
    return "".join(random.choices(string.ascii_letters, k=length))

def get_random_email():
    return f"{get_random_string(10).lower()}@example.com"

def get_random_phone():
    return "9" + "".join(random.choices(string.digits, k=9))

class RegistrationSeleniumTest(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Headless Chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        cls.driver = webdriver.Chrome(options=chrome_options)
        cls.driver.implicitly_wait(3)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.driver.delete_all_cookies()

    def test_donor_registration_wizard_flow_and_validation(self):
        # 1. Start Donor Registration
        self.driver.get(self.live_server_url + reverse('donor_registration'))
        
        # Step 1: Account Information should be visible
        self.assertTrue(self.driver.find_element(By.ID, "step1").is_displayed())
        self.assertFalse(self.driver.find_element(By.ID, "step2").is_displayed())

        # Test the Step 1 back navigation (Redirects to select role page)
        back_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), '❮')]")
        back_btn.click()
        WebDriverWait(self.driver, 3).until(EC.url_contains('/select-role/'))
        self.assertIn("/select-role/", self.driver.current_url)

        # Return to donor registration
        self.driver.get(self.live_server_url + reverse('donor_registration'))

        # Fill Step 1 with randomized inputs
        first_name = "Donor" + get_random_string(5)
        last_name = "Santos" + get_random_string(5)
        email = get_random_email()
        phone = get_random_phone()

        self.driver.find_element(By.NAME, "first_name").send_keys(first_name)
        self.driver.find_element(By.NAME, "last_name").send_keys(last_name)
        self.driver.find_element(By.NAME, "email").send_keys(email)
        self.driver.find_element(By.NAME, "contact_no").send_keys(phone)
        self.driver.find_element(By.NAME, "password").send_keys("Password123")
        self.driver.find_element(By.NAME, "confirm_password").send_keys("Password123")

        # Click Next (❯)
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()

        # Step 2: Location Information should be visible now
        WebDriverWait(self.driver, 3).until(EC.visibility_of_element_located((By.ID, "step2")))
        self.assertTrue(self.driver.find_element(By.ID, "step2").is_displayed())
        self.assertFalse(self.driver.find_element(By.ID, "step1").is_displayed())

        # Fill Step 2 Location Fields (Metro Manila coordinates so it passes geofencing!)
        self.driver.find_element(By.NAME, "display_address").send_keys("V. Luna Road, Diliman, Quezon City")
        self.driver.execute_script("document.getElementById('lat').value = '14.6300000';")
        self.driver.execute_script("document.getElementById('lng').value = '121.0500000';")
        self.driver.execute_script("document.getElementById('city').value = 'Quezon City';")
        self.driver.execute_script("document.getElementById('brgy').value = 'Pinyahan';")

        # Click Register (Submit)
        register_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Register')]")
        register_btn.click()

        # Verify redirect to Login Page (reverse('login') -> '/') on Success
        login_url = self.live_server_url + reverse('login')
        WebDriverWait(self.driver, 5).until(EC.url_to_be(login_url))
        self.assertEqual(self.driver.current_url, login_url)

    def test_donor_registration_password_mismatch(self):
        # Start Donor Registration
        self.driver.get(self.live_server_url + reverse('donor_registration'))

        # Fill Step 1 with mismatched passwords and random other inputs
        first_name = "Donor" + get_random_string(5)
        last_name = "Santos" + get_random_string(5)
        email = get_random_email()
        phone = get_random_phone()

        self.driver.find_element(By.NAME, "first_name").send_keys(first_name)
        self.driver.find_element(By.NAME, "last_name").send_keys(last_name)
        self.driver.find_element(By.NAME, "email").send_keys(email)
        self.driver.find_element(By.NAME, "contact_no").send_keys(phone)
        self.driver.find_element(By.NAME, "password").send_keys("Password123")
        self.driver.find_element(By.NAME, "confirm_password").send_keys("DifferentPassword!")

        # Go to Step 2
        self.driver.find_element(By.ID, "next-btn").click()
        
        # Fill Step 2 Display Address
        self.driver.find_element(By.NAME, "display_address").send_keys("Quezon City")

        # Submit
        self.driver.find_element(By.XPATH, "//button[contains(text(), 'Register')]").click()

        # Verify the custom frontend password-mismatch warning is visible on screen
        error_container = WebDriverWait(self.driver, 3).until(
            EC.visibility_of_element_located((By.XPATH, "//*[contains(text(), 'Passwords do not match.')]"))
        )
        self.assertIsNotNone(error_container)

    def test_tuab_registration_wizard_flow_and_validation(self):
        # Create dummy PDF file for uploading
        dummy_pdf_path = os.path.abspath("dummy.pdf")
        with open(dummy_pdf_path, "w") as f:
            f.write("Dummy PDF content")

        try:
            # 1. Start TUAB Registration
            self.driver.get(self.live_server_url + reverse('tuab_registration'))

            # Step 1: Account credentials should be visible
            self.assertTrue(self.driver.find_element(By.ID, "st1").is_displayed())
            self.assertFalse(self.driver.find_element(By.ID, "st2").is_displayed())
            self.assertFalse(self.driver.find_element(By.ID, "st3").is_displayed())

            # Test the Step 1 back navigation (Redirects to select role page)
            back_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), '❮')]")
            back_btn.click()
            WebDriverWait(self.driver, 3).until(EC.url_contains('/select-role/'))
            self.assertIn("/select-role/", self.driver.current_url)

            # Return to TUAB registration
            self.driver.get(self.live_server_url + reverse('tuab_registration'))

            # Fill Step 1 with randomized inputs
            biz_name = "Eco Weavers " + get_random_string(4)
            email = get_random_email()
            phone = get_random_phone()

            self.driver.find_element(By.NAME, "business_name").send_keys(biz_name)
            self.driver.find_element(By.NAME, "email").send_keys(email)
            self.driver.find_element(By.NAME, "contact_no").send_keys(phone)
            self.driver.find_element(By.NAME, "password").send_keys("Password123")
            self.driver.find_element(By.NAME, "confirm_password").send_keys("Password123")

            # Click Next (❯)
            next_btn = self.driver.find_element(By.ID, "nb")
            next_btn.click()

            # Step 2: Business Info & Preferences should be visible now
            WebDriverWait(self.driver, 3).until(EC.visibility_of_element_located((By.ID, "st2")))
            self.assertTrue(self.driver.find_element(By.ID, "st2").is_displayed())
            self.assertFalse(self.driver.find_element(By.ID, "st1").is_displayed())

            # Fill Step 2 Location with Metro Manila coordinates so it passes geofencing!
            self.driver.find_element(By.NAME, "display_address").send_keys("123 Taft Ave, Manila")
            self.driver.execute_script("document.getElementById('lat').value = '14.5800000';")
            self.driver.execute_script("document.getElementById('lng').value = '120.9800000';")
            self.driver.execute_script("document.getElementById('city').value = 'Manila';")
            self.driver.execute_script("document.getElementById('brgy').value = 'Malate';")
            
            # Enter operational metrics
            self.driver.find_element(By.NAME, "max_distance_km").clear()
            self.driver.find_element(By.NAME, "max_distance_km").send_keys("25")
            self.driver.find_element(By.NAME, "min_biodeg_score").clear()
            self.driver.find_element(By.NAME, "min_biodeg_score").send_keys("75")
            
            # Set target fibers (must be cotton, polyester, etc. in allowed fibers)
            self.driver.execute_script("document.getElementById('fibs').value = 'cotton,polyester';")

            # Click Next (❯) to go to Step 3
            next_btn.click()

            # Step 3: Business Authentication/Upload should be visible now
            WebDriverWait(self.driver, 3).until(EC.visibility_of_element_located((By.ID, "st3")))
            self.assertTrue(self.driver.find_element(By.ID, "st3").is_displayed())
            self.assertFalse(self.driver.find_element(By.ID, "st2").is_displayed())

            # Upload document
            file_input = self.driver.find_element(By.NAME, "documentation")
            file_input.send_keys(dummy_pdf_path)

            # Click Submit via JavaScript
            self.driver.execute_script("subFrm();")

            # Verify redirect to Login Page (reverse('login') -> '/') on Success
            login_url = self.live_server_url + reverse('login')
            WebDriverWait(self.driver, 5).until(EC.url_to_be(login_url))
            self.assertEqual(self.driver.current_url, login_url)
        finally:
            if os.path.exists(dummy_pdf_path):
                os.remove(dummy_pdf_path)

    def test_tuab_registration_comprehensive_api_errors(self):
        # Start TUAB Registration
        self.driver.get(self.live_server_url + reverse('tuab_registration'))

        # Step 1: Fill with invalid details
        self.driver.find_element(By.NAME, "email").send_keys("invalid-email")
        self.driver.find_element(By.NAME, "contact_no").send_keys("123")
        self.driver.find_element(By.NAME, "password").send_keys("Password123")
        self.driver.find_element(By.NAME, "confirm_password").send_keys("Password123")

        # Step 2: Next and Fill
        self.driver.find_element(By.ID, "nb").click()
        WebDriverWait(self.driver, 3).until(EC.visibility_of_element_located((By.ID, "st2")))
        
        # Set coordinates outside NCR (e.g. 0, 0)
        self.driver.execute_script("document.getElementById('lat').value = '0.0000000';")
        self.driver.execute_script("document.getElementById('lng').value = '0.0000000';")
        self.driver.find_element(By.NAME, "display_address").send_keys("Equator")
        
        # Set negative score
        self.driver.find_element(By.NAME, "min_biodeg_score").clear()
        self.driver.find_element(By.NAME, "min_biodeg_score").send_keys("-10.0")

        # Step 3: Next and Submit
        self.driver.find_element(By.ID, "nb").click()
        WebDriverWait(self.driver, 3).until(EC.visibility_of_element_located((By.ID, "st3")))
        
        # Submit via JavaScript
        self.driver.execute_script("subFrm();")

        # Wait for the reloaded page with errors to render
        WebDriverWait(self.driver, 8).until(
            EC.visibility_of_element_located((By.XPATH, "//*[contains(text(), 'Please fix these errors')]"))
        )

        # Verify all formatted/title-cased errors are visible on screen
        expected_errors = [
            "Email: Enter a valid email address.",
            "Min Biodeg Score: Ensure this value is greater than or equal to 0.0.",
            "Documentation: No file was submitted."
        ]
        
        for err_msg in expected_errors:
            element = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.XPATH, f"//li[contains(., '{err_msg}')]"))
            )
            self.assertIsNotNone(element)

    def test_donor_registration_comprehensive_api_errors(self):
        # Start Donor Registration
        self.driver.get(self.live_server_url + reverse('donor_registration'))

        # Step 1: Fill with invalid details
        self.driver.find_element(By.NAME, "email").send_keys("invalid-email")
        self.driver.find_element(By.NAME, "contact_no").send_keys("123")
        self.driver.find_element(By.NAME, "password").send_keys("Password123")
        self.driver.find_element(By.NAME, "confirm_password").send_keys("Password123")

        # Step 2: Next
        self.driver.find_element(By.ID, "next-btn").click()
        WebDriverWait(self.driver, 3).until(EC.visibility_of_element_located((By.ID, "step2")))
        
        # Set coordinates outside NCR (e.g. 0, 0)
        self.driver.execute_script("document.getElementById('lat').value = '0.0000000';")
        self.driver.execute_script("document.getElementById('lng').value = '0.0000000';")
        self.driver.find_element(By.NAME, "display_address").send_keys("Equator")

        # Submit via JavaScript
        self.driver.execute_script("document.getElementById('frm').submit();")

        # Wait for the reloaded page with errors to render
        WebDriverWait(self.driver, 8).until(
            EC.visibility_of_element_located((By.XPATH, "//*[contains(text(), 'Please fix these errors')]"))
        )

        # Verify all formatted/title-cased errors are visible on screen
        expected_errors = [
            "First Name",
            "Last Name",
            "Email: Enter a valid email address."
        ]
        
        for err_msg in expected_errors:
            element = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.XPATH, f"//li[contains(., '{err_msg}')]"))
            )
            self.assertIsNotNone(element)


class DonationSeleniumTest(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        cls.driver = webdriver.Chrome(options=chrome_options)
        cls.driver.implicitly_wait(3)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.donor_email = get_random_email()
        self.donor_password = "Password123"
        self.donor_phone = "+63" + get_random_phone()
        
        payload = {
            'role': 'Donor',
            'first_name': 'RealDonor',
            'last_name': 'Test',
            'email': self.donor_email,
            'password': self.donor_password,
            'contact_no': self.donor_phone,
            'display_address': 'Quezon City, Metro Manila',
            'latitude': '14.6500000',
            'longitude': '121.0500000'
        }
        resp = requests.post("http://127.0.0.1:8000/api/register", json=payload)
        self.assertEqual(resp.status_code, 201)
        
        # Ensure we clear all cookies so that any login state from a previous test is cleared!
        self.driver.delete_all_cookies()
        
        # Log in the donor using Selenium
        self.driver.get(self.live_server_url + reverse('login'))
        
        email_el = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        email_el.clear()
        email_el.send_keys(self.donor_email)
        
        pass_el = self.driver.find_element(By.NAME, "password")
        pass_el.clear()
        pass_el.send_keys(self.donor_password)
        
        self.driver.find_element(By.ID, "loginSubmit").click()
        
        # Wait until redirected to donor home/browse page
        WebDriverWait(self.driver, 5).until(EC.url_contains('/donor/'))

    def test_create_donation_happy_path(self):
        # Navigate to donation creation page
        self.driver.get(self.live_server_url + reverse('donor_create_donation'))
        
        # Verify form element is visible
        self.assertTrue(self.driver.find_element(By.ID, "create-frm").is_displayed())
        
        # 1. Randomly decide how many clothing cards to add (1 to 3 items)
        num_cards = random.randint(1, 3)
        for _ in range(num_cards - 1):
            self.driver.find_element(By.CLASS_NAME, "btn-add").click()

        # Fill each clothing card with dynamic randomized inputs
        cards = self.driver.find_elements(By.CLASS_NAME, "restored-card")
        for idx, card in enumerate(cards):
            # Fill clothing type select
            type_select = Select(card.find_element(By.CLASS_NAME, "type-sel"))
            type_select.select_by_value("t-shirt")
            
            # Fill brand select
            brand_select = Select(card.find_element(By.CLASS_NAME, "brand-sel"))
            brand_select.select_by_value("OXGN")
            
            # Wait until material input placeholder is "Search..." to guarantee options have finished loading
            mat_input = card.find_element(By.CLASS_NAME, "mat-in")
            WebDriverWait(self.driver, 5).until(
                lambda d: mat_input.get_attribute("placeholder") == "Search..."
            )
            
            # Click and send space key
            mat_input.click()
            mat_input.send_keys(" ")
            
            # Locate and click on a random loaded autocomplete option
            mat_options = WebDriverWait(card, 5).until(
                lambda c: c.find_elements(By.CLASS_NAME, "ss-item")
            )
            random.choice(mat_options).click()
            
            # Input a random weight
            weight_input = card.find_element(By.CLASS_NAME, "weight-in")
            weight_input.clear()
            weight_input.send_keys(f"{random.uniform(0.5, 10.0):.1f}")
            
            # Select random condition
            cond_select = Select(card.find_element(By.CLASS_NAME, "cond-sel"))
            cond_opts = [opt.get_attribute("value") for opt in cond_select.options if opt.get_attribute("value")]
            cond_select.select_by_value(random.choice(cond_opts))

        # 2. Fill randomized pickup location coordinates (within Metro Manila)
        # Using a tightly geofenced bounding box around a known Metro Manila point (Quezon City) to ensure 100% geofence-safe coordinates.
        random_lat = f"{random.uniform(14.6350000, 14.6650000):.7f}"
        random_lng = f"{random.uniform(121.0350000, 121.0650000):.7f}"
        self.driver.execute_script(f"document.getElementById('lat').value = '{random_lat}';")
        self.driver.execute_script(f"document.getElementById('lng').value = '{random_lng}';")
        self.driver.execute_script("document.getElementById('addr').value = 'Quezon City, Metro Manila';")

        # 3. Fill randomized future schedule preferences
        from datetime import date, timedelta
        random_days = random.randint(1, 28)
        pickup_date = (date.today() + timedelta(days=random_days)).strftime('%Y-%m-%d')
        
        start_hour = random.randint(8, 12)
        end_hour = random.randint(13, 18)
        pickup_start = f"{start_hour:02d}:00"
        pickup_end = f"{end_hour:02d}:00"

        self.driver.execute_script(f"document.getElementsByName('preferred_pickup_date')[0].value = '{pickup_date}';")
        self.driver.execute_script(f"document.getElementsByName('preferred_pickup_window_start')[0].value = '{pickup_start}';")
        self.driver.execute_script(f"document.getElementsByName('preferred_pickup_window_end')[0].value = '{pickup_end}';")
        
        # Submit
        submit_btn = self.driver.find_element(By.CLASS_NAME, "btn-submit")
        submit_btn.click()
        
        # Verify user is redirected to their donations listing page on success
        my_donations_url = self.live_server_url + reverse('donor_my_donations')
        WebDriverWait(self.driver, 5).until(EC.url_to_be(my_donations_url))
        self.assertEqual(self.driver.current_url, my_donations_url)

    def test_create_donation_all_validation_errors(self):
        # Navigate to donation creation page
        self.driver.get(self.live_server_url + reverse('donor_create_donation'))
        
        # Fill clothing cards
        clothing_select = Select(self.driver.find_element(By.CLASS_NAME, "type-sel"))
        clothing_select.select_by_value("t-shirt")
        brand_select = Select(self.driver.find_element(By.CLASS_NAME, "brand-sel"))
        brand_select.select_by_value("OXGN")
        
        # Wait until material input placeholder is "Search..." to guarantee options have finished loading
        mat_input = self.driver.find_element(By.CLASS_NAME, "mat-in")
        WebDriverWait(self.driver, 5).until(
            lambda d: mat_input.get_attribute("placeholder") == "Search..."
        )
        
        # Click and send space key
        mat_input.click()
        mat_input.send_keys(" ")
        
        mat_option = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "ss-item"))
        )
        mat_option.click()
        
        weight_input = self.driver.find_element(By.CLASS_NAME, "weight-in")
        weight_input.send_keys("2.5")
        
        # Inject invalid location coordinates outside NCR but with 7 decimal precision
        self.driver.execute_script("document.getElementById('lat').value = '0.0000000';")
        self.driver.execute_script("document.getElementById('lng').value = '0.0000000';")
        self.driver.execute_script("document.getElementById('addr').value = 'Equator';")
        
        # Inject invalid date in the past (yesterday)
        from datetime import date, timedelta
        yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
        self.driver.execute_script(f"document.getElementsByName('preferred_pickup_date')[0].value = '{yesterday}';")
        
        # Inject invalid time start > end
        self.driver.execute_script("document.getElementsByName('preferred_pickup_window_start')[0].value = '17:00';")
        self.driver.execute_script("document.getElementsByName('preferred_pickup_window_end')[0].value = '09:00';")
        
        # Submit to trigger errors
        submit_btn = self.driver.find_element(By.CLASS_NAME, "btn-submit")
        submit_btn.click()
        
        # Verify all formatted/joined errors are beautifully presented inside flash alerts
        expected_substrings = [
            "Pickup location must be within the National Capital Region (NCR).",
            "Preferred Pickup Date: Pickup date cannot be in the past.",
            "Preferred Pickup Window Start: Start time must be before end time."
        ]
        
        for substring in expected_substrings:
            alert_element = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.XPATH, f"//*[contains(., '{substring}')]"))
            )
            self.assertIsNotNone(alert_element)

    def test_update_profile_happy_path_and_2fa(self):
        try:
            # 1. Navigate directly to Edit Profile (since setUp logs the donor in by default)
            self.driver.get(self.live_server_url + reverse('edit_profile'))
            WebDriverWait(self.driver, 15).until(EC.visibility_of_element_located((By.ID, "ep-form")))

            # Update last name randomly
            new_last_name = "Santos" + get_random_string(5)
            last_name_input = self.driver.find_element(By.NAME, "last_name")
            last_name_input.clear()
            last_name_input.send_keys(new_last_name)

            # Update phone number randomly (valid 10 digit number)
            new_phone = "9" + "".join(random.choices(string.digits, k=9))
            phone_input = self.driver.find_element(By.NAME, "contact_no")
            phone_input.clear()
            phone_input.send_keys(new_phone)

            # Update address & coordinates within Metro Manila (geofence-safe)
            # Using a tightly geofenced bounding box around a known Metro Manila point (Quezon City) to ensure 100% geofence-safe coordinates.
            random_lat = f"{random.uniform(14.6350000, 14.6650000):.7f}"
            random_lng = f"{random.uniform(121.0350000, 121.0650000):.7f}"
            self.driver.execute_script(f"document.getElementById('lat').value = '{random_lat}';")
            self.driver.execute_script(f"document.getElementById('lng').value = '{random_lng}';")
            self.driver.execute_script("document.getElementById('addr').value = 'Mandaluyong City, Metro Manila';")

            # Toggle 2FA ON
            toggle_btn = self.driver.find_element(By.ID, "tgl")
            if "on" not in toggle_btn.get_attribute("class"):
                toggle_btn.click()

            # Click Save Changes to open the 2FA verify modal
            self.driver.find_element(By.ID, "save-btn").click()

            # Wait for 2FA verification modal to become visible
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.ID, "twofa-modal"))
            )

            # Read the generated secret displayed in the modal
            secret_element = self.driver.find_element(By.ID, "totp-secret-display")
            totp_secret = secret_element.text.strip()
            self.assertEqual(len(totp_secret), 32)

            # Dynamically generate the valid 6-digit TOTP code
            import pyotp
            totp = pyotp.TOTP(totp_secret)
            valid_otp = totp.now()

            # Type the valid OTP code into the code input
            otp_input = self.driver.find_element(By.ID, "totp-in")
            otp_input.clear()
            otp_input.send_keys(valid_otp)

            # Click Verify & Save
            verify_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Verify & Save')]")
            verify_btn.click()

            # Verify redirection to donor profile page on success
            WebDriverWait(self.driver, 15).until(EC.url_contains('/donor/profile/'))

            # Verify that the updated last name and enabled 2FA status are shown
            WebDriverWait(self.driver, 15).until(
                EC.text_to_be_present_in_element((By.TAG_NAME, "body"), new_last_name)
            )
            self.assertIn("Enabled", self.driver.page_source)

            # 3. Disable 2FA
            self.driver.get(self.live_server_url + reverse('edit_profile'))
            WebDriverWait(self.driver, 15).until(EC.visibility_of_element_located((By.ID, "ep-form")))

            # Click toggle to turn OFF
            toggle_btn = self.driver.find_element(By.ID, "tgl")
            if "on" in toggle_btn.get_attribute("class"):
                toggle_btn.click()

            # Save changes (should save immediately and redirect since we are turning off 2FA)
            self.driver.find_element(By.ID, "save-btn").click()
            WebDriverWait(self.driver, 15).until(EC.url_contains('/donor/profile/'))
            self.assertIn("Disabled", self.driver.page_source)
        except Exception as e:
            with open("diagnostic_happy.txt", "w", encoding="utf-8") as f:
                f.write(f"URL: {self.driver.current_url}\n")
                f.write(f"CONSOLE LOGS: {self.driver.get_log('browser')}\n")
                f.write(f"PAGE SOURCE:\n{self.driver.page_source}\n")
            raise e

    def test_update_profile_all_validation_errors(self):
        try:
            # 1. Navigate directly to Edit Profile (since setUp logs the donor in by default)
            self.driver.get(self.live_server_url + reverse('edit_profile'))
            WebDriverWait(self.driver, 15).until(EC.visibility_of_element_located((By.ID, "ep-form")))

            # --- Validation 1: Passwords do not match ---
            new_pass_input = self.driver.find_element(By.NAME, "new_password")
            new_pass_input.clear()
            new_pass_input.send_keys("Password123")
            confirm_pass_input = self.driver.find_element(By.NAME, "confirm_password")
            confirm_pass_input.clear()
            confirm_pass_input.send_keys("DifferentPassword123")

            self.driver.find_element(By.ID, "save-btn").click()
            # Verify alert is shown
            alert_element = WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(., 'Passwords do not match!')]"))
            )
            self.assertIsNotNone(alert_element)
            
            # Clear password fields and remove existing alerts
            new_pass_input.clear()
            confirm_pass_input.clear()
            self.driver.execute_script("document.querySelectorAll('.wf-alert').forEach(el => el.remove());")

            # --- Validation 2: Phone number validation error (invalid format) ---
            phone_input = self.driver.find_element(By.NAME, "contact_no")
            phone_input.clear()
            phone_input.send_keys("12345")  # Invalid length/format
            
            self.driver.find_element(By.ID, "save-btn").click()
            alert_element = WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(., 'Phone must be +63 followed by 10 digits.')]"))
            )
            self.assertIsNotNone(alert_element)

            # Restore valid phone number and remove existing alerts
            phone_input.clear()
            phone_input.send_keys(self.donor_phone)
            self.driver.execute_script("document.querySelectorAll('.wf-alert').forEach(el => el.remove());")

            # --- Validation 3: Geofencing validation error (outside Metro Manila) ---
            self.driver.execute_script("document.getElementById('lat').value = '0.0000000';")
            self.driver.execute_script("document.getElementById('lng').value = '0.0000000';")
            
            self.driver.find_element(By.ID, "save-btn").click()
            alert_element = WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(., 'Location must be within Metro Manila (NCR).')]"))
            )
            self.assertIsNotNone(alert_element)

            # Restore NCR coordinates and remove existing alerts
            self.driver.execute_script("document.getElementById('lat').value = '14.6300000';")
            self.driver.execute_script("document.getElementById('lng').value = '121.0500000';")
            self.driver.execute_script("document.querySelectorAll('.wf-alert').forEach(el => el.remove());")

            # --- Validation 4: Invalid 2FA Code validation error ---
            toggle_btn = self.driver.find_element(By.ID, "tgl")
            if "on" not in toggle_btn.get_attribute("class"):
                toggle_btn.click()

            self.driver.find_element(By.ID, "save-btn").click()
            
            WebDriverWait(self.driver, 15).until(EC.visibility_of_element_located((By.ID, "twofa-modal")))
            otp_input = self.driver.find_element(By.ID, "totp-in")
            otp_input.clear()
            otp_input.send_keys("000000")  # Invalid code
            
            self.driver.find_element(By.XPATH, "//button[contains(text(), 'Verify & Save')]").click()
            alert_element = WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(., 'Invalid 2FA code.')]"))
            )
            self.assertIsNotNone(alert_element)
            
            # Click Cancel to exit modal and remove existing alerts
            self.driver.find_element(By.XPATH, "//button[contains(text(), 'Cancel')]").click()
            WebDriverWait(self.driver, 15).until(EC.invisibility_of_element_located((By.ID, "twofa-modal")))
            self.driver.execute_script("document.querySelectorAll('.wf-alert').forEach(el => el.remove());")

            # --- Validation 5: ETag Concurrency Conflict (412 Precondition Failed) ---
            # Inject an outdated ETag inside the form hidden field
            self.driver.execute_script("document.getElementsByName('current_etag')[0].value = 'W/\"stale-etag\"';")
            
            # Make a minor change to trigger a submit request
            last_name_input = self.driver.find_element(By.NAME, "last_name")
            last_name_input.clear()
            last_name_input.send_keys("ConflictTest")

            self.driver.find_element(By.ID, "save-btn").click()
            alert_element = WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(., 'This profile was recently modified. Your changes have been blocked')]"))
            )
            self.assertIsNotNone(alert_element)
        except Exception as e:
            with open("diagnostic_errors.txt", "w", encoding="utf-8") as f:
                f.write(f"URL: {self.driver.current_url}\n")
                f.write(f"CONSOLE LOGS: {self.driver.get_log('browser')}\n")
                f.write(f"PAGE SOURCE:\n{self.driver.page_source}\n")
            raise e
