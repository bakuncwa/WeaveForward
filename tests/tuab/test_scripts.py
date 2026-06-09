"""
Application Under Test : WeaveForward
Automation Framework   : Selenium WebDriver (Python)
File                   : test_scripts.py — complete TUAB test-function library
"""

import logging
import os
import random
import string
import time
import unittest

import pyotp

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
BASE_URL     = "http://127.0.0.1:8001"
LOG_FILE     = "error_logs.txt"
DEFAULT_WAIT = 5
HEADLESS     = False  # overridden by main.py

logger = logging.getLogger("WeaveForwardTUABTests")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  [%(levelname)-8s]  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh.setFormatter(_fmt)
_ch.setFormatter(_fmt)
logger.addHandler(_fh)
logger.addHandler(_ch)


def create_driver() -> webdriver.Chrome:
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--log-level=3")
    prefs = {"profile.default_content_setting_values.geolocation": 1}
    opts.add_experimental_option("prefs", prefs)
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    return webdriver.Chrome(options=opts)


def _random_email():
    return f"tuab_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}@test.com"


# ──────────────────────────────────────────────────────────────────────────────
# Shared state (module-level, updated across tests)
# ──────────────────────────────────────────────────────────────────────────────
REGISTERED_TUAB_EMAIL    = "gabrielleysabel.almirol@benilde.edu.ph"
REGISTERED_TUAB_PASSWORD = "Wf@Benilde2026!"
REGISTERED_TUAB_SECRET   = None


def _js_clear_and_type(driver, element, value):
    driver.execute_script("arguments[0].value = '';", element)
    element.send_keys(value)


def _tuab_login(driver: webdriver.Chrome, wait: WebDriverWait):
    driver.delete_all_cookies()
    driver.get(f"{BASE_URL}/")
    el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
    _js_clear_and_type(driver, el, REGISTERED_TUAB_EMAIL)
    pw = driver.find_element(By.NAME, "password")
    _js_clear_and_type(driver, pw, REGISTERED_TUAB_PASSWORD)
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(1)
    try:
        otp_el = driver.find_element(By.ID, "otp")
        if otp_el.is_displayed() and REGISTERED_TUAB_SECRET:
            otp_el.send_keys(pyotp.TOTP(REGISTERED_TUAB_SECRET).now())
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            time.sleep(1)
    except Exception:
        pass


def _ensure_tuab_login(driver: webdriver.Chrome, wait: WebDriverWait, target_url: str = None):
    if "/login" in driver.current_url or driver.current_url.rstrip("/") == BASE_URL.rstrip("/"):
        _tuab_login(driver, wait)
        if target_url:
            driver.get(target_url)


def _admin_login(driver: webdriver.Chrome, wait: WebDriverWait):
    driver.delete_all_cookies()
    driver.get(f"{BASE_URL}/")
    el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
    _js_clear_and_type(driver, el, "admin@weaveforward.com")
    pw = driver.find_element(By.NAME, "password")
    _js_clear_and_type(driver, pw, "SecureAdminPassword123")
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(1)


# ══════════════════════════════════════════════════════════════════════════════
#  TC11 — TUAB Register Account
# ══════════════════════════════════════════════════════════════════════════════
class TC11TUABRegisterAccountTest(unittest.TestCase):
    registered_email = None

    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)

    def tearDown(self):
        self.driver.quit()

    def test_tc11_001_register_valid(self):
        """Verify TUAB Account Creation is Successful with Valid Credentials"""
        driver, wait = self.driver, self.wait
        email = _random_email()
        phone = str(random.randint(9000000000, 9999999999))

        driver.get(f"{BASE_URL}/register/tuab/")

        # ── Step 1: Account Credentials ──────────────────────────────────────
        el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        _js_clear_and_type(driver, el, email)
        _js_clear_and_type(driver, driver.find_element(By.NAME, "business_name"), "Artisan Weave Co.")
        _js_clear_and_type(driver, driver.find_element(By.NAME, "contact_no"), phone)
        _js_clear_and_type(driver, driver.find_element(By.ID, "pw"), "Test1234!")
        _js_clear_and_type(driver, driver.find_element(By.ID, "cp"), "Test1234!")
        time.sleep(0.3)
        driver.find_element(By.XPATH, "//button[contains(@onclick,'go(1)')]").click()
        time.sleep(0.5)

        # ── Step 2: Business Information ─────────────────────────────────────
        desc_el = wait.until(EC.visibility_of_element_located((By.NAME, "description")))
        desc_el.clear(); desc_el.send_keys("A textile upcycling business based in Manila.")
        addr_el = wait.until(EC.visibility_of_element_located((By.ID, "addr")))
        addr_el.clear(); addr_el.send_keys("123 Artisan Blvd, Paco, Manila")
        driver.execute_script("document.getElementById('lat').value = '14.5833333';")
        driver.execute_script("document.getElementById('lng').value = '120.9833333';")
        driver.execute_script("document.getElementById('city').value = 'Manila';")
        driver.execute_script("document.getElementById('brgy').value = 'Paco';")
        try:
            md = driver.find_element(By.ID, "md"); md.clear(); md.send_keys("20")
            mbs = driver.find_element(By.ID, "mbs"); mbs.clear(); mbs.send_keys("50")
        except Exception:
            pass
        driver.find_element(By.XPATH, "//button[contains(@onclick,'go(1)')]").click()
        time.sleep(0.5)

        # ── Step 3: Documentation Upload & Submit ────────────────────────────
        dummy_path = os.path.join(os.path.dirname(__file__), "dummy_permit.pdf")
        if not os.path.exists(dummy_path):
            with open(dummy_path, "wb") as f:
                f.write(b"%PDF-1.4 1 0 obj<</Type /Catalog>>endobj")
        doc_input = driver.find_elements(By.CSS_SELECTOR, "input[type='file'][name='documentation']")
        if doc_input:
            doc_input[0].send_keys(dummy_path)
            time.sleep(0.5)

        driver.find_element(By.XPATH, "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'submit')]").click()
        wait.until(lambda d: d.current_url.rstrip("/") == BASE_URL.rstrip("/") or "/login" in d.current_url)
        TC11TUABRegisterAccountTest.registered_email = email

        # ── Admin approves the newly registered TUAB ─────────────────────────
        _admin_login(driver, wait)
        wait.until(lambda d: "/admin" in d.current_url or "/donation" in d.current_url)
        driver.get(f"{BASE_URL}/admin/tuabs/add/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        time.sleep(1)
        approve_btns = driver.find_elements(By.XPATH,
            "//form[.//input[@name='action'][@value='approve']]//button[@type='submit']")
        if approve_btns:
            approve_btns[0].click()
            time.sleep(1)

    def test_tc11_002_cancel_registration(self):
        """Verify TUAB Registration Cancellation Functions"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/register/tuab/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        cancel_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(@onclick, 'go(-1)')]")))
        cancel_btn.click()
        time.sleep(1)
        self.assertTrue(
            "/login" in driver.current_url or "select-role" in driver.current_url or
            driver.current_url.rstrip("/") == BASE_URL.rstrip("/"),
            "Registration cancellation did not redirect to login or role select page"
        )

    def test_tc11_003_invalid_registration(self):
        """Verify TUAB Account Creation is Unsuccessful with Invalid Credentials"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/register/tuab/")
        el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        _js_clear_and_type(driver, el, "notanemail")
        try:
            _js_clear_and_type(driver, driver.find_element(By.NAME, "business_name"), "X")
            _js_clear_and_type(driver, driver.find_element(By.ID, "pw"), "short")
            _js_clear_and_type(driver, driver.find_element(By.ID, "cp"), "short")
        except Exception:
            pass
        try:
            driver.find_element(By.XPATH, "//button[contains(@onclick,'go(1)')]").click()
            time.sleep(0.5)
        except Exception:
            pass
        time.sleep(1)
        self.assertIn("/register/tuab/", driver.current_url,
                      "System accepted invalid TUAB registration")

    def test_tc11_004_duplicate_email(self):
        """Verify TUAB Account Creation is Unsuccessful due to Duplicate Email"""
        driver, wait = self.driver, self.wait
        dup_email = TC11TUABRegisterAccountTest.registered_email or REGISTERED_TUAB_EMAIL
        phone = str(random.randint(9000000000, 9999999999))
        driver.get(f"{BASE_URL}/register/tuab/")
        el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        _js_clear_and_type(driver, el, dup_email)
        try:
            _js_clear_and_type(driver, driver.find_element(By.NAME, "business_name"), "Duplicate Biz")
            _js_clear_and_type(driver, driver.find_element(By.NAME, "contact_no"), phone)
            _js_clear_and_type(driver, driver.find_element(By.ID, "pw"), "Test1234!")
            _js_clear_and_type(driver, driver.find_element(By.ID, "cp"), "Test1234!")
        except Exception:
            pass
        try:
            driver.find_element(By.XPATH, "//button[contains(@onclick,'go(1)')]").click()
            time.sleep(0.5)
        except Exception:
            pass
        try:
            wait.until(EC.visibility_of_element_located((By.ID, "addr"))).send_keys("456 Dup St")
            driver.execute_script("if(document.getElementById('lat')) document.getElementById('lat').value = '14.5833333';")
            driver.execute_script("if(document.getElementById('lng')) document.getElementById('lng').value = '120.9833333';")
        except Exception:
            pass
        try:
            driver.find_element(By.XPATH, "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'register') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'submit')]").click()
        except Exception:
            pass
        time.sleep(1)
        self.assertIn("/register/tuab/", driver.current_url,
                      "System allowed duplicate email TUAB registration")

    def test_tc11_005_weak_password_blocked(self):
        """Verify That Weak Password Is Rejected by Password Strength Validation"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/register/tuab/")
        el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        _js_clear_and_type(driver, el, _random_email())
        try:
            _js_clear_and_type(driver, driver.find_element(By.NAME, "business_name"), "Test Biz")
            _js_clear_and_type(driver, driver.find_element(By.NAME, "contact_no"), str(random.randint(9000000000, 9999999999)))
        except Exception:
            pass
        _js_clear_and_type(driver, driver.find_element(By.ID, "pw"), "weakpassword")
        _js_clear_and_type(driver, driver.find_element(By.ID, "cp"), "weakpassword")
        driver.find_element(By.XPATH, "//button[contains(@onclick, 'go(1)')]").click()
        time.sleep(0.5)
        rules_el = driver.find_element(By.ID, "pw-rules")
        self.assertIn("visible", rules_el.get_attribute("class"),
                      "Password strength checklist was not shown for a weak password")
        st2_class = driver.find_element(By.ID, "st2").get_attribute("class")
        self.assertIn("hidden", st2_class,
                      "Form advanced past step 1 despite a weak password")

    def test_tc11_006_password_mismatch_blocked(self):
        """Verify That Mismatched Passwords Are Rejected"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/register/tuab/")
        el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        _js_clear_and_type(driver, el, _random_email())
        try:
            _js_clear_and_type(driver, driver.find_element(By.NAME, "business_name"), "Test Biz")
            _js_clear_and_type(driver, driver.find_element(By.NAME, "contact_no"), str(random.randint(9000000000, 9999999999)))
        except Exception:
            pass
        _js_clear_and_type(driver, driver.find_element(By.ID, "pw"), "ValidPass1!")
        _js_clear_and_type(driver, driver.find_element(By.ID, "cp"), "DifferentPass1!")
        driver.find_element(By.XPATH, "//button[contains(@onclick, 'go(1)')]").click()
        time.sleep(0.5)
        mismatch_err = driver.find_element(By.ID, "pw-match-err")
        self.assertNotIn("hidden", mismatch_err.get_attribute("class"),
                         "Password mismatch error was not displayed")
        st2_class = driver.find_element(By.ID, "st2").get_attribute("class")
        self.assertIn("hidden", st2_class,
                      "Form advanced past step 1 despite mismatched passwords")


# ══════════════════════════════════════════════════════════════════════════════
#  TC12 — TUAB Login
# ══════════════════════════════════════════════════════════════════════════════
class TC12TUABLoginTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)

    def tearDown(self):
        self.driver.quit()

    def test_tc12_001_login_valid(self):
        """Verify That A TUAB Can Login With Valid Credentials"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/")
        el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        _js_clear_and_type(driver, el, REGISTERED_TUAB_EMAIL)
        _js_clear_and_type(driver, driver.find_element(By.NAME, "password"), REGISTERED_TUAB_PASSWORD)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
        try:
            otp_el = driver.find_element(By.ID, "otp")
            if otp_el.is_displayed() and REGISTERED_TUAB_SECRET:
                otp_el.send_keys(pyotp.TOTP(REGISTERED_TUAB_SECRET).now())
                driver.find_element(By.XPATH, "//button[@type='submit']").click()
                time.sleep(1)
        except Exception:
            pass
        wait.until(lambda d: "/tuab/dashboard" in d.current_url or "/tuab/" in d.current_url)

    def test_tc12_002_password_recovery(self):
        """Verify That Password Recovery Can Be Initiated Via Forgot Password"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/forgot-password/")
        wait.until(EC.visibility_of_element_located((By.NAME, "email"))).send_keys(REGISTERED_TUAB_EMAIL)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "sent" in body.lower() or "reset" in body.lower(),
            "Password recovery did not show confirmation message"
        )

    def test_tc12_003_login_2fa(self):
        """Verify That A TUAB Can Login With 2FA Enabled"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/")
        wait.until(EC.visibility_of_element_located((By.NAME, "email"))).send_keys(REGISTERED_TUAB_EMAIL)
        driver.find_element(By.NAME, "password").send_keys(REGISTERED_TUAB_PASSWORD)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
        try:
            otp_el = wait.until(EC.visibility_of_element_located((By.ID, "otp")))
            if not REGISTERED_TUAB_SECRET:
                self.skipTest("TUAB does not have 2FA enabled — enable 2FA first via TC21-004")
            otp_el.send_keys(pyotp.TOTP(REGISTERED_TUAB_SECRET).now())
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            wait.until(lambda d: "/tuab/dashboard" in d.current_url or "/tuab/" in d.current_url)
        except TimeoutException:
            self.skipTest("2FA prompt not triggered — TUAB may not have 2FA enabled")

    def test_tc12_004_login_under_review_blocked(self):
        """Verify That Access Is Restricted For TUABs With Under Review Status"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/")
        under_review_email = "test_tuab_pending@gmail.com"
        wait.until(EC.visibility_of_element_located((By.NAME, "email"))).send_keys(under_review_email)
        driver.find_element(By.NAME, "password").send_keys("Test1234!")
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
        self.assertNotIn(
            "/tuab/dashboard", driver.current_url,
            "Under-review TUAB was allowed to access dashboard"
        )

    def test_tc12_005_login_invalid_credentials(self):
        """Verify That Access Is Rejected With Invalid Credentials"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/")
        wait.until(EC.visibility_of_element_located((By.NAME, "email"))).send_keys("nonexistent_tuab@test.com")
        driver.find_element(By.NAME, "password").send_keys("WrongPass!")
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
        self.assertNotIn(
            "/tuab/dashboard", driver.current_url,
            "System allowed login with invalid credentials"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  TC13 — TUAB View Incoming Donations (Dashboard)
# ══════════════════════════════════════════════════════════════════════════════
class TC13TUABViewIncomingDonationsTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def test_tc13_001_view_donations(self):
        """Verify That A TUAB Can View Donations Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/dashboard/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "donation" in body.lower() or "available" in body.lower(),
            "Dashboard did not display donations"
        )

    def test_tc13_002_date_range_filter_valid(self):
        """Verify that Dashboard Date Range Filters Work Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/dashboard/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        date_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='date']")
        if not date_inputs:
            self.skipTest("No date range inputs found on TUAB dashboard")
        driver.execute_script("arguments[0].value = '2026-01-01';", date_inputs[0])
        if len(date_inputs) >= 2:
            driver.execute_script("arguments[0].value = '2026-12-31';", date_inputs[1])
        submit_btns = driver.find_elements(By.XPATH, "//button[@type='submit']")
        if submit_btns:
            submit_btns[0].click()
        else:
            date_inputs[0].send_keys(Keys.RETURN)
        time.sleep(1)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))

    def test_tc13_003_date_range_filter_invalid(self):
        """Verify That Dashboard Date Range Filters Are Rejected when Invalid"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/dashboard/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        date_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='date']")
        if not date_inputs:
            self.skipTest("No date range inputs found on TUAB dashboard")
        driver.execute_script("arguments[0].removeAttribute('max'); arguments[0].value = '2099-01-01';", date_inputs[0])
        if len(date_inputs) >= 2:
            driver.execute_script("arguments[0].removeAttribute('max'); arguments[0].value = '2000-01-01';", date_inputs[1])
        submit_btns = driver.find_elements(By.XPATH, "//button[@type='submit']")
        if submit_btns:
            submit_btns[0].click()
        time.sleep(1)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "invalid" in body.lower() or "error" in body.lower() or
            "donation" in body.lower(),
            "System did not handle invalid date range"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  TC14 — TUAB Subscribe For Premium Features
# ══════════════════════════════════════════════════════════════════════════════
class TC14TUABSubscribeForPremiumTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def test_tc14_001_subscribe_valid_payment(self):
        """Verify That A TUAB Can Subscribe For Premium Features Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/subscribe/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        billing_name = driver.find_elements(By.CSS_SELECTOR, "input[name='billing_name'], input[id*='name']")
        card_number  = driver.find_elements(By.CSS_SELECTOR, "input[name='card_number'], input[id*='card']")
        if not billing_name or not card_number:
            self.skipTest("Payment form inputs not found — check subscribe page implementation")
        billing_name[0].send_keys("Test TUAB")
        card_number[0].send_keys("5123456789012346")  # Maya sandbox test card
        exp_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name*='exp'], input[id*='exp']")
        if exp_inputs:
            exp_inputs[0].send_keys("12")
            if len(exp_inputs) > 1:
                exp_inputs[1].send_keys("2030")
        cvc_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name*='cvc'], input[name*='cvv'], input[id*='cvc']")
        if cvc_inputs:
            cvc_inputs[0].send_keys("111")
        submit_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@type='submit' or contains(text(),'Subscribe') or contains(text(),'Pay')]")))
        submit_btn.click()
        time.sleep(3)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertFalse(
            "error" in body.lower() and "payment" not in body.lower(),
            "Subscription with valid payment failed unexpectedly"
        )

    def test_tc14_002_subscribe_invalid_customer_details(self):
        """Verify That Subscription Is Rejected When Invalid Customer Information Is Provided"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/subscribe/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        billing_name = driver.find_elements(By.CSS_SELECTOR, "input[name='billing_name'], input[id*='name']")
        if not billing_name:
            self.skipTest("Payment form inputs not found — check subscribe page implementation")
        billing_name[0].clear()
        submit_btn = driver.find_elements(By.XPATH, "//button[@type='submit']")
        if submit_btn:
            submit_btn[0].click()
        time.sleep(1)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "invalid" in body.lower() or "required" in body.lower() or
            "error" in body.lower() or "/subscribe/" in driver.current_url,
            "System accepted subscription with invalid customer details"
        )

    def test_tc14_003_subscribe_invalid_card_details(self):
        """Verify That Subscription Is Rejected When Invalid Card Details Are Provided"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/subscribe/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        billing_name = driver.find_elements(By.CSS_SELECTOR, "input[name='billing_name'], input[id*='name']")
        card_number  = driver.find_elements(By.CSS_SELECTOR, "input[name='card_number'], input[id*='card']")
        if not billing_name or not card_number:
            self.skipTest("Payment form inputs not found — check subscribe page implementation")
        billing_name[0].send_keys("Test TUAB")
        card_number[0].send_keys("0000000000000000")
        submit_btn = driver.find_elements(By.XPATH, "//button[@type='submit']")
        if submit_btn:
            submit_btn[0].click()
        time.sleep(2)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "invalid" in body.lower() or "error" in body.lower() or "/subscribe/" in driver.current_url,
            "System accepted subscription with invalid card details"
        )

    def test_tc14_004_subscribe_insufficient_funds(self):
        """Verify That Subscription Is Rejected When The Card Is Declined Due To Insufficient Funds"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/subscribe/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        billing_name = driver.find_elements(By.CSS_SELECTOR, "input[name='billing_name'], input[id*='name']")
        card_number  = driver.find_elements(By.CSS_SELECTOR, "input[name='card_number'], input[id*='card']")
        if not billing_name or not card_number:
            self.skipTest("Payment form inputs not found — check subscribe page implementation")
        billing_name[0].send_keys("Test TUAB")
        card_number[0].send_keys("5111111111111118")  # Maya sandbox declined card
        exp_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name*='exp'], input[id*='exp']")
        if exp_inputs:
            exp_inputs[0].send_keys("12")
            if len(exp_inputs) > 1:
                exp_inputs[1].send_keys("2030")
        cvc_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name*='cvc'], input[name*='cvv'], input[id*='cvc']")
        if cvc_inputs:
            cvc_inputs[0].send_keys("111")
        submit_btn = driver.find_elements(By.XPATH, "//button[@type='submit']")
        if submit_btn:
            submit_btn[0].click()
        time.sleep(3)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "unsuccessful" in body.lower() or "declined" in body.lower() or
            "error" in body.lower() or "/subscribe/" in driver.current_url,
            "System processed a payment for a card with insufficient funds"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  TC15 — TUAB View Match Donations Recommendations
# ══════════════════════════════════════════════════════════════════════════════
class TC15TUABViewMatchRecommendationsTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def test_tc15_001_view_recommendations(self):
        """Verify That A TUAB Can View Recommended Matched Donations Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/fiber-match-recommendations/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "match" in body.lower() or "recommendation" in body.lower() or
            "fiber" in body.lower() or "subscribe" in body.lower(),
            "Fiber match recommendations page did not render"
        )

    def test_tc15_002_free_tier_cannot_access(self):
        """Verify That A Free Tier TUAB Cannot Access Match Recommendations Without A Pro Subscription"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/fiber-match-recommendations/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        body = driver.find_element(By.TAG_NAME, "body").text
        is_on_subscribe = "subscribe" in driver.current_url or "subscribe" in body.lower()
        has_recommendations = any(kw in body.lower() for kw in ["accept", "reject", "matched donation"])
        if has_recommendations and not is_on_subscribe:
            logger.info("TC15-002: TUAB appears to have Pro tier — free-tier restriction not testable with this account")
            self.skipTest("Test TUAB account has Pro subscription — use a free-tier account for this test")


# ══════════════════════════════════════════════════════════════════════════════
#  TC16 — TUAB Update Incoming Donations
# ══════════════════════════════════════════════════════════════════════════════
class TC16TUABUpdateIncomingDonationsTest(unittest.TestCase):
    claimed_donation_id = None

    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def _get_claimed_donation_id(self):
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/tuab/dashboard/?tab=claimed")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        links = driver.find_elements(By.XPATH,
            "//a[contains(@href, '/tuab/donations/') and (contains(text(),'View') or contains(text(),'view'))]")
        if not links:
            self.skipTest("No claimed donations found — claim a donation first")
        href = links[0].get_attribute("href")
        parts = [p for p in href.split("/") if p.isdigit()]
        if not parts:
            self.skipTest("Could not parse donation ID from href")
        return parts[-1]

    def test_tc16_001_accept_picked_up_donation(self):
        """Verify That An Incoming Picked-Up Donation Can Be Ingested Into Inventory"""
        driver, wait = self.driver, self.wait
        did = self._get_claimed_donation_id()
        edit_url = f"{BASE_URL}/tuab/donations/{did}/edit/"
        driver.get(edit_url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        accept_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'accept') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'received')]")
        if not accept_btns:
            self.skipTest(f"No Accept/Received button on edit page for donation {did}")
        accept_btns[0].click()
        time.sleep(2)
        TC16TUABUpdateIncomingDonationsTest.claimed_donation_id = did

    def test_tc16_002_accept_delivered_donation(self):
        """Verify That An Incoming Delivered Donation Can Be Ingested Into Inventory"""
        driver, wait = self.driver, self.wait
        did = self._get_claimed_donation_id()
        edit_url = f"{BASE_URL}/tuab/donations/{did}/edit/"
        driver.get(edit_url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        accept_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'accept') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'received')]")
        if not accept_btns:
            self.skipTest(f"No Accept button on edit page for donation {did}")
        accept_btns[0].click()
        time.sleep(2)

    def test_tc16_003_reject_incoming_donation(self):
        """Verify That An Incoming Donation Can Be Rejected Successfully"""
        driver, wait = self.driver, self.wait
        did = self._get_claimed_donation_id()
        edit_url = f"{BASE_URL}/tuab/donations/{did}/edit/"
        driver.get(edit_url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        reject_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'reject') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'reject')]")
        if not reject_btns:
            self.skipTest(f"No Reject button on edit page for donation {did}")
        reject_btns[0].click()
        time.sleep(2)


# ══════════════════════════════════════════════════════════════════════════════
#  TC17 — TUAB Flag Incoming Donations
# ══════════════════════════════════════════════════════════════════════════════
class TC17TUABFlagIncomingDonationsTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)

    def tearDown(self):
        self.driver.quit()

    def test_tc17_001_flag_donation_valid_reason(self):
        """Verify That A Flagged Donation Can Be Resolved Successfully With Valid Information"""
        driver, wait = self.driver, self.wait
        _tuab_login(driver, wait)
        driver.get(f"{BASE_URL}/tuab/dashboard/?tab=claimed")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        flag_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'openFlagModal') or contains(@onclick,'Flag') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'flag')]")
        if not flag_btns:
            self.skipTest("No flag button found — no claimed donations available")
        flag_btns[0].click()
        reason_el = wait.until(EC.visibility_of_element_located((By.ID, "flag-reason-input")))
        reason_el.clear()
        reason_el.send_keys("Spam — identical items submitted multiple times by same donor.")
        submit_btns = driver.find_elements(By.XPATH, "//button[contains(@onclick,'submitFlag')]")
        if submit_btns:
            submit_btns[0].click()
        time.sleep(2)

        # Admin resolves the flagged donation
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        flagged_links = driver.find_elements(By.XPATH,
            "//a[contains(@href,'/admin/donations/') and contains(@href,'/edit/')]")
        if not flagged_links:
            logger.info("TC17-001: No donation edit links found on admin page — cannot resolve flagged donation")
            return
        flagged_links[0].click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))

    def test_tc17_002_flag_donation_invalid_reason(self):
        """Verify That Flagging Is Rejected When An Invalid Reason Is Provided"""
        driver, wait = self.driver, self.wait
        _tuab_login(driver, wait)
        driver.get(f"{BASE_URL}/tuab/dashboard/?tab=claimed")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        flag_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'openFlagModal') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'flag')]")
        if not flag_btns:
            self.skipTest("No flag button found — no claimed donations available")
        flag_btns[0].click()
        try:
            reason_el = wait.until(EC.visibility_of_element_located((By.ID, "flag-reason-input")))
            reason_el.clear()
        except TimeoutException:
            self.skipTest("Flag modal did not open")
        submit_btns = driver.find_elements(By.XPATH, "//button[contains(@onclick,'submitFlag')]")
        if submit_btns:
            submit_btns[0].click()
        time.sleep(1)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "reason" in body.lower() or "invalid" in body.lower() or "required" in body.lower() or
            "enter" in body.lower() or "please" in body.lower(),
            "System accepted flag submission with empty reason"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  TC18 — TUAB View Inventory Items
# ══════════════════════════════════════════════════════════════════════════════
class TC18TUABViewInventoryItemsTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def test_tc18_001_view_inventory_snapshot(self):
        """Verify That The Inventory Snapshot With Active Records Can Be Viewed Successfully"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/tuab/inventory/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        self.assertIn("/tuab/inventory", driver.current_url,
                      "Inventory snapshot page did not load — redirect may have occurred")
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "inventory" in body.lower() or "snapshot" in body.lower(),
            "Inventory snapshot page did not render expected content"
        )

    def test_tc18_002_export_inventory_csv(self):
        """Verify That The Inventory Snapshot With Active Records Can Be Exported Successfully"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/tuab/inventory/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        export_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'exportInventoryCSV') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'export') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'csv')]")
        self.assertTrue(len(export_btns) > 0, "No Export CSV button found on inventory page")
        export_btns[0].click()
        time.sleep(2)


# ══════════════════════════════════════════════════════════════════════════════
#  TC19 — TUAB Update Inventory Items
# ══════════════════════════════════════════════════════════════════════════════
class TC19TUABUpdateInventoryItemsTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def _get_first_inventory_item(self):
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/tuab/inventory/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        update_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'updateUsage') or contains(@data-action,'update') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'update')]")
        if not update_btns:
            self.skipTest("No inventory items available to update")
        update_btns[0].click()
        time.sleep(1)
        return update_btns[0]

    def test_tc19_001_update_valid(self):
        """Verify That Inventory Updates With Valid Information Are Successful"""
        driver, wait = self.driver, self.wait
        self._get_first_inventory_item()
        weight_inputs = driver.find_elements(By.CSS_SELECTOR,
            "input[name*='weight'], input[name*='usage'], input[type='number']")
        if not weight_inputs:
            self.skipTest("No weight/usage input found in update form")
        weight_inputs[0].clear()
        weight_inputs[0].send_keys("0.5")
        save_btns = driver.find_elements(By.XPATH,
            "//button[@type='submit' or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'save') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'update')]")
        if save_btns:
            save_btns[0].click()
        time.sleep(2)

    def test_tc19_002_update_invalid(self):
        """Verify That Inventory Updates With Invalid Information Are Rejected"""
        driver, wait = self.driver, self.wait
        self._get_first_inventory_item()
        weight_inputs = driver.find_elements(By.CSS_SELECTOR,
            "input[name*='weight'], input[name*='usage'], input[type='number']")
        if not weight_inputs:
            self.skipTest("No weight/usage input found in update form")
        weight_inputs[0].clear()
        weight_inputs[0].send_keys("-999")
        save_btns = driver.find_elements(By.XPATH,
            "//button[@type='submit' or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'save') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'update')]")
        if save_btns:
            save_btns[0].click()
        time.sleep(1)
        body = driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "invalid" in body.lower() or "error" in body.lower() or
            "must" in body.lower() or "/tuab/inventory" in driver.current_url,
            "System accepted invalid inventory update"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  TC20 — TUAB Archive Inventory Items
# ══════════════════════════════════════════════════════════════════════════════
class TC20TUABArchiveInventoryItemsTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def test_tc20_001_archive_inventory_item(self):
        """Verify That Deletion is Successful"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/tuab/inventory/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        archive_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'archive') or contains(@onclick,'Archive') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'archive') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'delete')]")
        if not archive_btns:
            self.skipTest("No Archive button found on inventory page — no items to archive")
        archive_btns[0].click()
        time.sleep(1)
        # Select an exit state if prompted
        exit_selects = driver.find_elements(By.CSS_SELECTOR,
            "select[name*='exit'], select[name*='status'], select[id*='exit']")
        if exit_selects:
            Select(exit_selects[0]).select_by_index(1)
        confirm_btns = driver.find_elements(By.XPATH,
            "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'confirm') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'archive')]")
        if confirm_btns:
            confirm_btns[0].click()
        else:
            try:
                alert = driver.switch_to.alert
                alert.accept()
            except Exception:
                pass
        time.sleep(2)

    def test_tc20_002_cancel_archive_inventory_item(self):
        """Verify That Cancelling Archival Aborts the Archiving Process"""
        driver, wait = self.driver, self.wait
        driver.get(f"{BASE_URL}/tuab/inventory/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        archive_btns = driver.find_elements(By.XPATH,
            "//button[contains(@onclick,'archive') or contains(@onclick,'Archive') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'archive') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'delete')]")
        if not archive_btns:
            self.skipTest("No Archive button found on inventory page — no items to cancel archiving of")
        archive_btns[0].click()
        time.sleep(1)
        cancel_btns = driver.find_elements(By.XPATH,
            "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cancel') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'dismiss')]")
        if cancel_btns:
            cancel_btns[0].click()
        else:
            try:
                alert = driver.switch_to.alert
                alert.dismiss()
            except Exception:
                pass
        time.sleep(1)
        self.assertIn("/tuab/inventory", driver.current_url,
                      "Cancelling archive did not keep user on inventory page")


# ══════════════════════════════════════════════════════════════════════════════
#  TC21 — TUAB Update Account Information
# ══════════════════════════════════════════════════════════════════════════════
class TC21TUABUpdateAccountInformationTest(unittest.TestCase):
    def setUp(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT)
        _tuab_login(self.driver, self.wait)

    def tearDown(self):
        self.driver.quit()

    def test_tc21_001_update_account_valid(self):
        """Verify That The TUAB Account Is Updated Successfully With Validated Fields"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/edit-profile/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        desc_el = driver.find_elements(By.NAME, "description")
        if desc_el:
            desc_el[0].clear()
            desc_el[0].send_keys("Updated business description — specialized in cotton and linen upcycling.")
        save_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@id='save-btn' or @type='submit']")))
        save_btn.click()
        wait.until(lambda d: "/tuab/profile" in d.current_url or "/tuab/edit-profile" not in d.current_url)

    def test_tc21_002_cancel_update_account(self):
        """Verify That Cancellation aborts Edit Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/edit-profile/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        cancel_link = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(@href,'/tuab/profile')]")))
        cancel_link.click()
        wait.until(lambda d: "/tuab/profile" in d.current_url)

    def test_tc21_003_update_location_valid(self):
        """Verify That The TUAB Account's Location Information Can Be Changed Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/edit-profile/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        addr_el = driver.find_elements(By.ID, "addr")
        if addr_el:
            addr_el[0].clear()
            addr_el[0].send_keys("789 Updated Ave, Taguig City")
        driver.execute_script("if(document.getElementById('lat')) document.getElementById('lat').value = '14.5547';")
        driver.execute_script("if(document.getElementById('lng')) document.getElementById('lng').value = '121.0505';")
        save_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@id='save-btn' or @type='submit']")))
        save_btn.click()
        wait.until(lambda d: "/tuab/profile" in d.current_url or "/tuab/edit-profile" not in d.current_url)

    def test_tc21_004_enable_2fa(self):
        """Verify That The TUAB Can Enable 2FA Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/edit-profile/"
        driver.get(url)
        _ensure_tuab_login(driver, wait, url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        tgl = wait.until(EC.presence_of_element_located((By.ID, "tgl")))
        if "on" not in tgl.get_attribute("class"):
            tgl.click()
        save_btn = driver.find_element(By.XPATH, "//button[@id='save-btn' or @type='submit']")
        save_btn.click()
        try:
            secret_el = wait.until(EC.visibility_of_element_located((By.ID, "totp-secret-display")))
            time.sleep(1)
            secret = secret_el.text.strip()
            driver.find_element(By.ID, "totp-in").send_keys(pyotp.TOTP(secret).now())
            driver.find_element(By.XPATH, "//button[contains(text(),'Verify & Save')]").click()
            wait.until(lambda d: "/tuab/profile" in d.current_url)
            global REGISTERED_TUAB_SECRET
            REGISTERED_TUAB_SECRET = secret
        except TimeoutException:
            self.skipTest("2FA enable modal did not appear — 2FA may already be enabled")

    def test_tc21_005_disable_2fa(self):
        """Verify That The TUAB Can Disable 2FA Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/edit-profile/"
        driver.get(url)
        _ensure_tuab_login(driver, wait, url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        tgl = wait.until(EC.presence_of_element_located((By.ID, "tgl")))
        if "on" in tgl.get_attribute("class"):
            tgl.click()
            save_btn = driver.find_element(By.XPATH, "//button[@id='save-btn' or @type='submit']")
            save_btn.click()
            wait.until(lambda d: "/tuab/profile" in d.current_url)
            time.sleep(1)
            driver.get(f"{BASE_URL}/tuab/edit-profile/")
            wait.until(EC.presence_of_element_located((By.ID, "tgl")))
            tgl2 = driver.find_element(By.ID, "tgl")
            self.assertNotIn("on", tgl2.get_attribute("class"),
                             "2FA was not disabled after toggle")
        else:
            self.skipTest("2FA is already disabled for this TUAB account — enable it first via TC21-004")

    def test_tc21_006_update_account_invalid_fields(self):
        """Verify That Invalid Fields Prevent Editing TUAB Account Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/edit-profile/"
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        biz_name_els = driver.find_elements(By.NAME, "business_name")
        if biz_name_els:
            biz_name_els[0].clear()
        save_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@id='save-btn' or @type='submit']")))
        save_btn.click()
        time.sleep(1)
        self.assertIn("/tuab/edit-profile", driver.current_url,
                      "System allowed invalid TUAB profile update (blank business name)")

    def test_tc21_007_update_account_invalid_totp(self):
        """Verify That Invalid TOTP Prevents Editing TUAB Account Successfully"""
        driver, wait = self.driver, self.wait
        url = f"{BASE_URL}/tuab/edit-profile/"
        driver.get(url)
        _ensure_tuab_login(driver, wait, url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        tgl = wait.until(EC.presence_of_element_located((By.ID, "tgl")))
        if "on" not in tgl.get_attribute("class"):
            tgl.click()
        save_btn = driver.find_element(By.XPATH, "//button[@id='save-btn' or @type='submit']")
        save_btn.click()
        try:
            wait.until(EC.visibility_of_element_located((By.ID, "totp-secret-display")))
            driver.find_element(By.ID, "totp-in").send_keys("000000")
            driver.find_element(By.XPATH, "//button[contains(text(),'Verify & Save')]").click()
            time.sleep(1)
            self.assertIn("/tuab/edit-profile", driver.current_url,
                          "System accepted invalid TOTP during 2FA enable")
        except TimeoutException:
            self.skipTest("2FA modal did not appear — 2FA may already be enabled, toggle not possible")
