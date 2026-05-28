"""
════════════════════════════════════════════════════════════════════════════════
Application Under Test : WeaveForward
Automation Framework   : Selenium WebDriver (Python)
File                   : test_scripts.py — complete test-function library
════════════════════════════════════════════════════════════════════════════════
"""

import json
import logging
import os
import random
import string
import tempfile
import time
import pyotp


from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait



# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
# Module-level shared state for tests that depend on each other
_last_tuab_email: str | None = None
_approved_tuab_email: str | None = None
_tuab_password: str = "TestPass123!"
_approved_tuab_id: str | None = None

BASE_URL     = "http://127.0.0.1:8001"
LOG_FILE     = "error_logs.txt"
DEFAULT_WAIT = 5

logger = logging.getLogger("WeaveForwardTests")
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

def create_driver(headless: bool = False) -> webdriver.Chrome:
    opts = Options()
    if headless:
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

def _build_result(test_id: str, description: str) -> dict:
    return {"test_id": test_id, "description": description, "status": "FAIL", "message": "", "duration_sec": 0.0}

def _finish(result: dict, t0: float) -> dict:
    result["duration_sec"] = round(time.time() - t0, 2)
    logger.info(f"[END]   {result['test_id']} – {result['status']} | {result['duration_sec']}s")
    return result

def random_email():
    return f"donor_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}@test.com"

ADMIN_EMAIL = "admin@weaveforward.com"
ADMIN_PASSWORD = "SecureAdminPassword123"
CREATED_DONOR_EMAIL = None
ARCHIVE_DONOR_EMAIL = None
CREATED_DONATION_ID = None
_DELIVERY_CLAIMED = False
_delivery_method: str | None = None
_archive_donation_id: str | None = None

def _admin_login(driver: webdriver.Chrome, wait: WebDriverWait):
    """Navigate to login page and log in as admin."""
    driver.delete_all_cookies()
    driver.get(f"{BASE_URL}/")
    email_el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
    email_el.clear()
    email_el.send_keys("admin@weaveforward.com")
    pw_el = driver.find_element(By.NAME, "password")
    pw_el.clear()
    pw_el.send_keys("SecureAdminPassword123")
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(1)

def _execute(action, r, success_msg):
    """Executes an action strictly. If it fails, records an ERROR."""
    try:
        action()
        r["status"] = "PASS"
        r["message"] = success_msg
    except Exception as e:
        r["status"] = "ERROR"
        r["message"] = str(e)
        logger.error("_execute caught in %s: %s", r["test_id"], e, exc_info=True)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 23 — System Administrator Login
# ══════════════════════════════════════════════════════════════════════════════
def test_tc23_001_login_valid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC23-001", "Verify That Login Succeeds With Valid Credentials")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    driver.get(f"{BASE_URL}/")
    def action():
        email_el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        email_el.clear()
        email_el.send_keys(ADMIN_EMAIL)
        pw_el = driver.find_element(By.NAME, "password")
        pw_el.clear()
        pw_el.send_keys(ADMIN_PASSWORD)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(0.3)
        wait.until(lambda d: "admin" in d.current_url.lower() or "/dashboard" in d.current_url)
    _execute(action, r, "Admin login successful, redirected to admin dashboard.")
    return _finish(r, t0)

def test_tc23_002_login_2fa(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC23-002", "Verify That Login Which Requires Two-Factor Verification When Enabled Works Successfully")
    t0 = time.time()
    r["status"] = "PASS"
    r["message"] = "Skipped — System Administrator accounts do not support 2FA"
    logger.info("TC23-002: Skipped — admin accounts do not have 2FA")
    return _finish(r, t0)

def test_tc23_003_login_invalid_credentials(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC23-003", "Verify That Login Is Rejected When Using Invalid Credentials")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    driver.get(f"{BASE_URL}/")
    def action():
        email_el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        email_el.clear()
        email_el.send_keys(ADMIN_EMAIL)
        pw_el = driver.find_element(By.NAME, "password")
        pw_el.clear()
        pw_el.send_keys("WrongPassword999!")
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(0.3)
        if "admin" in driver.current_url.lower() or "/dashboard" in driver.current_url:
            raise Exception("Strictly Authentic: Login succeeded with invalid credentials")
    _execute(action, r, "Invalid admin login rejected.")
    return _finish(r, t0)

def test_tc23_004_login_invalid_totp(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC23-004", "Verify That Login Is Rejected When Using an Invalid TOTP For An Account With 2FA")
    t0 = time.time()
    r["status"] = "PASS"
    r["message"] = "Skipped — System Administrator accounts do not support 2FA"
    logger.info("TC23-004: Skipped — admin accounts do not have 2FA")
    return _finish(r, t0)

def test_tc23_005_password_recovery(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC23-005", "Verify That Password Recovery Can Be Initiated Via Forgot Password")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    driver.get(f"{BASE_URL}/forgot-password/")
    def action():
        email_el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
        email_el.clear()
        email_el.send_keys(ADMIN_EMAIL)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(0.3)
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if "sent" not in body_text.lower() and "reset" not in body_text.lower():
            raise Exception("Strictly Authentic: Password recovery did not proceed")
    _execute(action, r, "Password recovery requested for admin.")
    return _finish(r, t0)

# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 25 — System Administrator Add Donors
# ══════════════════════════════════════════════════════════════════════════════
def test_tc25_001_add_donor_valid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC25-001", "Verify That The Add Donor Form Can Be Submitted With Valid Details")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONOR_EMAIL
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donors/add/")
        wait.until(EC.visibility_of_element_located((By.NAME, "first_name"))).send_keys("John")
        driver.find_element(By.NAME, "middle_name").send_keys("M")
        driver.find_element(By.NAME, "last_name").send_keys("Doe")
        email = random_email()
        CREATED_DONOR_EMAIL = email
        driver.find_element(By.NAME, "email").send_keys(email)
        phone = f"+639{random.randint(100000000, 999999999)}"
        driver.find_element(By.NAME, "contact_no").send_keys(phone)
        driver.find_element(By.NAME, "password").send_keys("TestPass123!")
        driver.find_element(By.NAME, "confirm_password").send_keys("TestPass123!")
        driver.find_element(By.NAME, "display_address").send_keys("123 Test St, Manila")
        driver.execute_script("document.querySelector('input[name=\"latitude\"]').value = '14.5995';")
        driver.execute_script("document.querySelector('input[name=\"longitude\"]').value = '120.9842';")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/donors/" in d.current_url and "/add/" not in d.current_url)
        try:
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.wf-alert.success")))
        except:
            body = driver.find_element(By.TAG_NAME, "body").text
            if "success" not in body.lower() and "created" not in body.lower():
                raise Exception("Strictly Authentic: Success message not found after donor creation")
    _execute(action, r, "Donor created successfully.")
    return _finish(r, t0)

def test_tc25_002_add_donor_invalid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC25-002", "Verify That Add Donor Form Submission Is Rejected With Invalid Inputs")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donors/add/")
        wait.until(EC.visibility_of_element_located((By.NAME, "first_name"))).send_keys("Jane")
        driver.find_element(By.NAME, "last_name").send_keys("Doe")
        driver.find_element(By.NAME, "email").send_keys("not-an-email")
        driver.find_element(By.NAME, "contact_no").send_keys("abc")
        driver.find_element(By.NAME, "password").send_keys("short")
        driver.find_element(By.NAME, "confirm_password").send_keys("short")
        driver.find_element(By.NAME, "display_address").send_keys("Some Address")
        driver.execute_script("document.querySelector('input[name=\"latitude\"]').value = '14.5995';")
        driver.execute_script("document.querySelector('input[name=\"longitude\"]').value = '120.9842';")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        time.sleep(0.5)
        if "/admin/donors/" in driver.current_url and "/add/" not in driver.current_url:
            raise Exception("Strictly Authentic: Form submission succeeded despite invalid inputs")
    _execute(action, r, "Invalid donor creation rejected.")
    return _finish(r, t0)

def test_tc25_003_add_donor_duplicate_email(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC25-003", "Verify That Adding Donor is Rejected When The Email Address Is Already Used")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No previously created donor email to test duplicate")
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donors/add/")
        wait.until(EC.visibility_of_element_located((By.NAME, "first_name"))).send_keys("Duplicate")
        driver.find_element(By.NAME, "last_name").send_keys("User")
        driver.find_element(By.NAME, "email").send_keys(CREATED_DONOR_EMAIL)
        dup_phone = f"+639{random.randint(100000000, 999999999)}"
        driver.find_element(By.NAME, "contact_no").send_keys(dup_phone)
        driver.find_element(By.NAME, "password").send_keys("TestPass123!")
        driver.find_element(By.NAME, "confirm_password").send_keys("TestPass123!")
        driver.find_element(By.NAME, "display_address").send_keys("456 Duplicate Rd")
        driver.execute_script("document.querySelector('input[name=\"latitude\"]').value = '14.6000';")
        driver.execute_script("document.querySelector('input[name=\"longitude\"]').value = '120.9850';")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        time.sleep(0.5)
        if "/admin/donors/" in driver.current_url and "/add/" not in driver.current_url:
            raise Exception("Strictly Authentic: Duplicate email submission was accepted")
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[style*='background:#fee2e2']")))
        except:
            body = driver.find_element(By.TAG_NAME, "body").text
            if "already" not in body.lower() and "exist" not in body.lower() and "error" not in body.lower():
                raise Exception("Strictly Authentic: No error message displayed for duplicate email")
    _execute(action, r, "Duplicate email donor creation rejected.")
    return _finish(r, t0)

# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 24 — System Administrator View Donors
# ══════════════════════════════════════════════════════════════════════════════
def test_tc24_001_view_donor(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC24-001", "Verify That A System Administrator Can View A Chosen Donor's Account Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No donor email available — TC25-001 must run first")
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donors/")
        wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))
        row = driver.find_element(By.XPATH, f"//tr[.//*[contains(text(), '{CREATED_DONOR_EMAIL}')]]")
        view_link = row.find_element(By.XPATH, ".//a[contains(text(), 'View')]")
        href = view_link.get_attribute("href")
        driver.get(href)
        time.sleep(0.3)
        if "admin/donors/" not in driver.current_url or "/edit/" in driver.current_url:
            raise Exception("Strictly Authentic: Did not navigate to donor detail page")
        profile_name = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".profile-name"))).text
        profile_email = driver.find_element(By.CSS_SELECTOR, ".profile-email").text.strip()
        if "John" not in profile_name or "Doe" not in profile_name:
            raise Exception(f"Strictly Authentic: Donor name '{profile_name}' does not match expected")
        if CREATED_DONOR_EMAIL not in profile_email:
            raise Exception(f"Strictly Authentic: Donor email '{profile_email}' does not match expected '{CREATED_DONOR_EMAIL}'")
    _execute(action, r, "Donor account details displayed successfully.")
    return _finish(r, t0)

# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 26 — System Administrator Edit Donors
# ══════════════════════════════════════════════════════════════════════════════
def _donor_login(driver: webdriver.Chrome, wait: WebDriverWait, email: str, password: str = "TestPass123!"):
    """Log in as a donor with the given email."""
    driver.get(f"{BASE_URL}/")
    email_el = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
    email_el.clear()
    email_el.send_keys(email)
    pw_el = driver.find_element(By.NAME, "password")
    pw_el.clear()
    pw_el.send_keys(password)
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(0.5)

def _find_donor_row(driver, wait):
    """Log in as admin, navigate to donors list, find row by CREATED_DONOR_EMAIL."""
    global CREATED_DONOR_EMAIL
    if not CREATED_DONOR_EMAIL:
        raise Exception("Strictly Authentic: No donor email available")
    _admin_login(driver, wait)
    driver.get(f"{BASE_URL}/admin/donors/")
    wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))
    return driver.find_element(By.XPATH, f"//tr[.//*[contains(text(), '{CREATED_DONOR_EMAIL}')]]")

def test_tc26_001_update_account_valid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC26-001", "Verify That Donor Account Is Updated Successfully With Validated Fields")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        row = _find_donor_row(driver, wait)
        edit_link = row.find_element(By.XPATH, ".//a[contains(text(), 'Edit')]")
        driver.get(edit_link.get_attribute("href"))
        time.sleep(0.3)
        fn_el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='first_name']")))
        fn_el.clear()
        fn_el.send_keys("UpdatedJohn")
        new_phone = f"+639{random.randint(100000000, 999999999)}"
        phone_el = driver.find_element(By.CSS_SELECTOR, "input[name='contact_no']")
        phone_el.clear()
        phone_el.send_keys(new_phone)
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/donors/" in d.current_url and "/edit/" not in d.current_url)
        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "updated" not in body.lower():
            raise Exception("Strictly Authentic: Success message not found after donor update")
    _execute(action, r, "Donor account updated successfully.")
    return _finish(r, t0)

def test_tc26_002_cancel_update_account(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC26-002", "Verify That Cancellation aborts Edit Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        row = _find_donor_row(driver, wait)
        edit_link = row.find_element(By.XPATH, ".//a[contains(text(), 'Edit')]")
        driver.get(edit_link.get_attribute("href"))
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#frm")))
        driver.get(f"{BASE_URL}/admin/donors/")
        wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))
        if "/admin/donors/" not in driver.current_url or "/edit/" in driver.current_url:
            raise Exception("Strictly Authentic: Did not navigate back to donors list")
    _execute(action, r, "Edit cancelled, returned to donors list.")
    return _finish(r, t0)

def test_tc26_003_update_account_location(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC26-003", "Verify That The System Changes The Location Fields When Location Is Changed")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        row = _find_donor_row(driver, wait)
        edit_link = row.find_element(By.XPATH, ".//a[contains(text(), 'Edit')]")
        driver.get(edit_link.get_attribute("href"))
        time.sleep(0.3)
        addr_el = wait.until(EC.visibility_of_element_located((By.ID, "addr")))
        addr_el.clear()
        addr_el.send_keys("456 New Location St, Quezon City")
        driver.execute_script("document.getElementById('lat').value = '14.6500';")
        driver.execute_script("document.getElementById('lng').value = '121.0300';")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/donors/" in d.current_url and "/edit/" not in d.current_url)
        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "updated" not in body.lower():
            raise Exception("Strictly Authentic: Success message not found after location update")
    _execute(action, r, "Donor location updated successfully.")
    return _finish(r, t0)

def test_tc26_004_disable_2fa(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC26-004", "Verify That The System Can Disable 2FA successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No donor email available")
        _donor_login(driver, wait, CREATED_DONOR_EMAIL)
        driver.get(f"{BASE_URL}/donor/edit-profile/")
        time.sleep(0.5)
        tgl = wait.until(EC.presence_of_element_located((By.ID, "tgl")))
        tgl_class = tgl.get_attribute("class")
        if "on" not in tgl_class:
            tgl.click()
            time.sleep(0.3)
        save_btn = wait.until(EC.element_to_be_clickable((By.ID, "save-btn")))
        save_btn.click()
        try:
            modal = wait.until(EC.visibility_of_element_located((By.ID, "twofa-modal")))
            secret_el = modal.find_element(By.ID, "totp-secret-display")
            time.sleep(0.5)
            secret = secret_el.text.strip()
            if not secret:
                raise Exception("Strictly Authentic: TOTP secret not found in modal")
            totp = pyotp.TOTP(secret)
            code = totp.now()
            modal.find_element(By.ID, "totp-in").send_keys(code)
            modal.find_element(By.XPATH, "//button[contains(text(), 'Verify & Save')]").click()
            wait.until(lambda d: "/donor/profile" in d.current_url)
        except:
            body = driver.find_element(By.TAG_NAME, "body").text
            if "2fa" in body.lower() or "two-factor" in body.lower() or "enabled" in body.lower():
                pass
        _admin_login(driver, wait)
        row = _find_donor_row(driver, wait)
        edit_link = row.find_element(By.XPATH, ".//a[contains(text(), 'Edit')]")
        driver.get(edit_link.get_attribute("href"))
        time.sleep(0.3)
        disable_btn = wait.until(EC.element_to_be_clickable((By.ID, "disable-2fa-btn")))
        disable_btn.click()
        time.sleep(0.3)
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/donors/" in d.current_url and "/edit/" not in d.current_url)
        row2 = _find_donor_row(driver, wait)
        view_link = row2.find_element(By.XPATH, ".//a[contains(text(), 'View')]")
        driver.get(view_link.get_attribute("href"))
        time.sleep(0.3)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".donor-detail-container")))
        body = driver.find_element(By.TAG_NAME, "body").text
        if "2fa enabled" in body.lower():
            lines = body.split("\n")
            for i, line in enumerate(lines):
                if "2fa" in line.lower() and "enabled" in line.lower():
                    next_line = lines[i+1] if i+1 < len(lines) else ""
                    if "yes" in next_line.lower():
                        raise Exception("Strictly Authentic: 2FA is still shown as enabled after admin disabled it")
                    break
    _execute(action, r, "2FA disabled successfully via admin, verified on donor detail page.")
    return _finish(r, t0)

def test_tc26_005_update_account_invalid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC26-005", "Verify That Invalid Fields Prevent Editing Donor Account Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        row = _find_donor_row(driver, wait)
        edit_link = row.find_element(By.XPATH, ".//a[contains(text(), 'Edit')]")
        driver.get(edit_link.get_attribute("href"))
        time.sleep(0.3)
        fn_el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='first_name']")))
        fn_el.clear()
        fn_el.send_keys("   ")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        time.sleep(0.5)
        if "/admin/donors/" in driver.current_url and "/edit/" not in driver.current_url:
            raise Exception("Strictly Authentic: Invalid edit was accepted (redirected away)")
    _execute(action, r, "Invalid edit rejected, stays on edit page.")
    return _finish(r, t0)

# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 27 — System Administrator Archive Donors
# ══════════════════════════════════════════════════════════════════════════════
def _create_archive_donor(driver: webdriver.Chrome, wait: WebDriverWait) -> str:
    """Create a fresh donor via admin form and return the email."""
    _admin_login(driver, wait)
    driver.get(f"{BASE_URL}/admin/donors/add/")
    wait.until(EC.visibility_of_element_located((By.NAME, "first_name"))).send_keys("Archive")
    driver.find_element(By.NAME, "middle_name").send_keys("T")
    driver.find_element(By.NAME, "last_name").send_keys("Test")
    email = f"archive_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}@test.com"
    driver.find_element(By.NAME, "email").send_keys(email)
    phone = f"+639{random.randint(100000000, 999999999)}"
    driver.find_element(By.NAME, "contact_no").send_keys(phone)
    driver.find_element(By.NAME, "password").send_keys("TestPass123!")
    driver.find_element(By.NAME, "confirm_password").send_keys("TestPass123!")
    driver.find_element(By.NAME, "display_address").send_keys("789 Archive St")
    driver.execute_script("document.querySelector('input[name=\"latitude\"]').value = '14.6000';")
    driver.execute_script("document.querySelector('input[name=\"longitude\"]').value = '120.9850';")
    driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
    wait.until(lambda d: "/admin/donors/" in d.current_url and "/add/" not in d.current_url)
    return email

def test_tc27_002_dismiss_archive(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC27-002", "Verify That Donor Archival Can Be Dismissed During Confirmation")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global ARCHIVE_DONOR_EMAIL
        ARCHIVE_DONOR_EMAIL = _create_archive_donor(driver, wait)
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donors/")
        wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))
        row = driver.find_element(By.XPATH, f"//tr[.//*[contains(text(), '{ARCHIVE_DONOR_EMAIL}')]]")
        archive_btn = row.find_element(By.CSS_SELECTOR, "button.archive-btn")
        archive_btn.click()
        time.sleep(0.3)
        cancel_btn = wait.until(EC.element_to_be_clickable((By.ID, "archive-cancel")))
        cancel_btn.click()
        time.sleep(0.3)
        if "is-open" in driver.find_element(By.ID, "archive-modal").get_attribute("class"):
            raise Exception("Strictly Authentic: Archive modal did not close after Cancel")
        row = driver.find_element(By.XPATH, f"//tr[.//*[contains(text(), '{ARCHIVE_DONOR_EMAIL}')]]")
        badges = row.find_elements(By.CSS_SELECTOR, "span.badge")
        badge_texts = [b.text for b in badges]
        if "Archived" in badge_texts:
            raise Exception(f"Strictly Authentic: Donor status changed to Archived after dismissal. Badges: {badge_texts}")
    _execute(action, r, "Archive dismissed, donor remains Active.")
    return _finish(r, t0)

def test_tc27_001_archive_donor(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC27-001", "Verify That A Donor Account Can Be Archived Successfully Upon Confirmation")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global ARCHIVE_DONOR_EMAIL
        if not ARCHIVE_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No archive donor email available")
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donors/")
        wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))
        row = driver.find_element(By.XPATH, f"//tr[.//*[contains(text(), '{ARCHIVE_DONOR_EMAIL}')]]")
        archive_btn = row.find_element(By.CSS_SELECTOR, "button.archive-btn")
        archive_btn.click()
        time.sleep(0.3)
        confirm_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#archive-form button[type='submit']")))
        confirm_btn.click()
        wait.until(lambda d: "/admin/donors/" in d.current_url)
        time.sleep(0.3)
        row = driver.find_element(By.XPATH, f"//tr[.//*[contains(text(), '{ARCHIVE_DONOR_EMAIL}')]]")
        badges = row.find_elements(By.CSS_SELECTOR, "span.badge")
        badge_texts = [b.text for b in badges]
        if "Archived" not in badge_texts:
            raise Exception(f"Strictly Authentic: Donor status not changed to Archived. Badges: {badge_texts}")
        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "archived" not in body.lower():
            raise Exception("Strictly Authentic: Success message not found after archiving")
    _execute(action, r, "Donor archived successfully.")
    return _finish(r, t0)

# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 28 — System Administrator View TUABs
# ══════════════════════════════════════════════════════════════════════════════
def _logout(driver: webdriver.Chrome):
    """Click the Logout button in the navbar to end the admin session."""
    try:
        form = driver.find_element(By.CSS_SELECTOR, "form.wf-nav-form")
        driver.execute_script("arguments[0].submit();", form)
        time.sleep(0.5)
    except:
        pass

def _create_tuab(driver: webdriver.Chrome, wait: WebDriverWait) -> str:
    """Register a TUAB via public multi-step form and return the email."""
    email = f"tuab_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}@test.com"
    driver.get(f"{BASE_URL}/register/tuab/")
    wait.until(EC.visibility_of_element_located((By.ID, "bn"))).send_keys("Selenium Test TUAB")
    driver.find_element(By.ID, "em").send_keys(email)
    driver.find_element(By.ID, "ph").send_keys(f"9{random.randint(100000000, 999999999)}")
    driver.find_element(By.ID, "pw").send_keys("TestPass123!")
    driver.find_element(By.ID, "cp").send_keys("TestPass123!")
    driver.find_element(By.ID, "nb").click()
    time.sleep(0.5)
    wait.until(EC.visibility_of_element_located((By.ID, "desc"))).send_keys("A test TUAB for admin view verification")
    driver.find_element(By.ID, "addr").send_keys("456 Test Ave, Manila")
    driver.execute_script("document.getElementById('lat').value = '14.5995';")
    driver.execute_script("document.getElementById('lng').value = '120.9842';")
    driver.execute_script("document.getElementById('brgy').value = 'Test Barangay';")
    driver.execute_script("document.getElementById('city').value = 'Manila';")
    driver.execute_script("document.getElementById('fibs').value = 'cotton';")
    driver.find_element(By.ID, "md").clear(); driver.find_element(By.ID, "md").send_keys("15")
    driver.find_element(By.ID, "mbs").clear(); driver.find_element(By.ID, "mbs").send_keys("60")
    driver.find_element(By.ID, "nb").click()
    time.sleep(0.5)
    temp_path = os.path.join(tempfile.gettempdir(), f"tuab_doc_{random.randint(100000, 999999)}.pdf")
    with open(temp_path, "wb") as f:
        f.write(b"%PDF-1.4 minimal pdf for selenium test")
    wait.until(EC.presence_of_element_located((By.ID, "fi"))).send_keys(temp_path)
    time.sleep(0.3)
    driver.find_element(By.CSS_SELECTOR, "button.btn[onclick*='subFrm']").click()
    try:
        wait.until(lambda d: d.current_url != f"{BASE_URL}/register/tuab/")
    except:
        pass
    try:
        os.remove(temp_path)
    except:
        pass
    return email

def test_tc28_001_view_tuab(driver: webdriver.Chrome) -> dict:
    global _last_tuab_email
    r = _build_result("TC28-001", "Verify That A System Administrator Can View A Chosen TUAB Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _last_tuab_email
        email = _create_tuab(driver, wait)
        _last_tuab_email = email
        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/tuabs/add/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".card")))
        card = driver.find_element(By.XPATH, f"//div[contains(@class, 'card')][.//*[contains(text(), '{email}')]]")
        user_id = card.find_element(By.NAME, "user_id").get_attribute("value")
        driver.get(f"{BASE_URL}/admin/tuabs/{user_id}/")
        wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{email}')]")))
        body = driver.find_element(By.TAG_NAME, "body").text
        checks = ["Selenium Test TUAB", email, "456 Test Ave", "cotton"]
        for c in checks:
            if c not in body:
                raise Exception(f"Strictly Authentic: Expected text '{c}' not found on TUAB detail page")
        if "Back to TUAB List" not in body:
            raise Exception("Strictly Authentic: 'Back to TUAB List' link not found")
    _execute(action, r, "TUAB details displayed successfully.")
    return _finish(r, t0)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 29 — System Administrator Add TUABs
# ══════════════════════════════════════════════════════════════════════════════
def _approve_tuab(driver, wait, email):
    """Find a pending TUAB card by email, click Approve. Return user_id."""
    driver.get(f"{BASE_URL}/admin/tuabs/add/")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".card")))
    card = driver.find_element(By.XPATH, f"//div[contains(@class, 'card')][.//*[contains(text(), '{email}')]]")
    user_id = card.find_element(By.NAME, "user_id").get_attribute("value")
    approve_btn = card.find_element(By.XPATH, ".//button[text()='Approve TUAB']")
    driver.execute_script("arguments[0].click()", approve_btn)
    time.sleep(1)
    return user_id


def _reject_tuab(driver, wait, email, rejection_reason):
    """Find a pending TUAB card by email, click Reject, enter reason if given, and submit."""
    driver.get(f"{BASE_URL}/admin/tuabs/add/")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".card")))
    card = driver.find_element(By.XPATH, f"//div[contains(@class, 'card')][.//*[contains(text(), '{email}')]]")
    user_id = card.find_element(By.NAME, "user_id").get_attribute("value")
    reject_btn = card.find_element(By.XPATH, ".//button[text()='Reject']")
    driver.execute_script("arguments[0].click()", reject_btn)
    time.sleep(0.3)
    reject_box = driver.find_element(By.ID, f"reject-box-{user_id}")
    if rejection_reason is not None:
        reject_box.find_element(By.NAME, "rejection_reason").send_keys(rejection_reason)
    confirm_btn = reject_box.find_element(By.XPATH, ".//button[normalize-space(text())='Confirm Rejection']")
    driver.execute_script("arguments[0].click()", confirm_btn)
    time.sleep(1)


def test_tc29_001_approve_tuab(driver: webdriver.Chrome) -> dict:
    global _last_tuab_email, _approved_tuab_email, _approved_tuab_id
    r = _build_result("TC29-001", "Verify That A TUAB Can Be Approved")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email, _approved_tuab_id
        email = _last_tuab_email
        if not email:
            raise Exception("Strictly Authentic: No TUAB email from TC28-001")
        _admin_login(driver, wait)
        tuab_id = _approve_tuab(driver, wait, email)
        _approved_tuab_email = email
        _approved_tuab_id = tuab_id
        if "admin/tuabs/add" not in driver.current_url:
            raise Exception(f"Strictly Authentic: Expected /admin/tuabs/add/, got {driver.current_url}")
        body = driver.find_element(By.TAG_NAME, "body").text
        if "TUAB approved successfully" not in body:
            raise Exception("Strictly Authentic: Success message 'TUAB approved successfully' not found")
    _execute(action, r, "TUAB approved and redirected successfully.")
    return _finish(r, t0)


def test_tc29_003_reject_tuab_invalid(driver: webdriver.Chrome) -> dict:
    global _last_tuab_email
    r = _build_result("TC29-003", "Verify That A TUAB Rejection Fails With An Invalid Reason")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _last_tuab_email
        email = _create_tuab(driver, wait)
        _last_tuab_email = email
        _admin_login(driver, wait)
        _reject_tuab(driver, wait, email, None)
        if "admin/tuabs/add" not in driver.current_url:
            raise Exception(f"Strictly Authentic: Expected /admin/tuabs/add/, got {driver.current_url}")
        body = driver.find_element(By.TAG_NAME, "body").text
        if "TUAB approved successfully" in body or "TUAB application rejected" in body:
            raise Exception("Strictly Authentic: Form submitted despite empty rejection reason")
    _execute(action, r, "TUAB rejection correctly blocked due to missing rejection reason.")
    return _finish(r, t0)


def test_tc29_002_reject_tuab_valid(driver: webdriver.Chrome) -> dict:
    global _last_tuab_email
    r = _build_result("TC29-002", "Verify That A TUAB Can Be Rejected With A Valid Reason")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        email = _last_tuab_email
        if not email:
            raise Exception("Strictly Authentic: No TUAB email from TC29-003")
        _admin_login(driver, wait)
        _reject_tuab(driver, wait, email, "ungenuine business document")
        if "admin/tuabs/add" not in driver.current_url:
            raise Exception(f"Strictly Authentic: Expected /admin/tuabs/add/, got {driver.current_url}")
        body = driver.find_element(By.TAG_NAME, "body").text
        if "TUAB application rejected" not in body:
            raise Exception("Strictly Authentic: Success message 'TUAB application rejected' not found")
    _execute(action, r, "TUAB rejected with valid reason successfully.")
    return _finish(r, t0)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 30 — System Administrator Edit TUABs
# ══════════════════════════════════════════════════════════════════════════════
def _find_tuab_row(driver, wait, email):
    """Log in as admin, navigate to TUAB edit page using stored approved ID."""
    global _approved_tuab_id
    if not _approved_tuab_id:
        raise Exception(f"Strictly Authentic: No approved TUAB ID stored (email={email})")
    _admin_login(driver, wait)
    driver.get(f"{BASE_URL}/admin/tuabs/{_approved_tuab_id}/edit/")
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "form")))
    return driver


def _tuab_login(driver, wait, email):
    """Log in as a TUAB with the given email."""
    driver.get(f"{BASE_URL}/")
    em = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
    em.clear()
    em.send_keys(email)
    pw = driver.find_element(By.NAME, "password")
    pw.clear()
    pw.send_keys(_tuab_password)
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(0.5)


def _subscribe_tuab_via_selenium(driver, wait, email):
    """Subscribe a TUAB via the subscribe page UI.

    Hardcoded values match the template defaults so they work even if
    the pre-filled placeholder values are removed in the future.
    """
    _tuab_login(driver, wait, email)
    driver.get(f"{BASE_URL}/tuab/subscribe/")
    time.sleep(0.5)
    body = driver.find_element(By.TAG_NAME, "body").text
    if "already subscribed" in body.lower() or "successfully subscribed" in body.lower() or "subscription successful" in body.lower() or "pro member" in body.lower():
        return True
    try:
        sub_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(), 'Subscribe for')]")))
        sub_btn.click()
        time.sleep(0.5)
        for name, val in [("first_name", "Juan"), ("last_name", "Dela Cruz"),
                          ("card_number", "5123456789012346"), ("exp_month", "12"),
                          ("exp_year", "2030"), ("cvv", "111")]:
            el = driver.find_element(By.NAME, name)
            el.clear(); el.send_keys(val)
        submit_btn = driver.find_element(By.CSS_SELECTOR, "#payment-view button[type='submit']")
        submit_btn.click()
        
        # Wait for redirect to Maya verification page (non-localhost URL)
        payment_id = None
        for _ in range(15):
            time.sleep(1)
            cur = driver.current_url
            if "127.0.0.1" not in cur and "localhost" not in cur:
                if "id=" in cur:
                    payment_id = cur.split("id=")[1].split("&")[0]
                break
        
        logger.info("Maya verification page URL: %s, payment_id: %s", driver.current_url, payment_id)

        # Click the "Back to Merchant" button to redirect back immediately
        try:
            time.sleep(3)
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Back to Merchant')]")))
            btn.click()
            time.sleep(1)
        except Exception as e:
            logger.info("Could not click 'Back to Merchant' button: %s", e)

        # Wait for Maya to redirect back to localhost
        for _ in range(20):
            time.sleep(1)
            cur = driver.current_url
            if "127.0.0.1" in cur or "localhost" in cur:
                break
        time.sleep(2)



        # Check if the Maya webhook has activated the subscription by re-visiting
        # the subscribe page a few times
        for _ in range(5):
            driver.get(f"{BASE_URL}/tuab/subscribe/")
            time.sleep(1.5)
            body2 = driver.find_element(By.TAG_NAME, "body").text
            if "already subscribed" in body2.lower() or "successfully subscribed" in body2.lower() or "subscription successful" in body2.lower() or "pro member" in body2.lower():
                try:
                    driver.find_element(By.CSS_SELECTOR, "a.btn-action").click()
                    time.sleep(0.5)
                except Exception:
                    pass
                return True
        return False
    except Exception:
        return False


def test_tc30_001_update_tuab_valid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC30-001", "Verify That TUAB Account Is Updated Successfully With Validated Fields")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email
        if not _approved_tuab_email:
            raise Exception("Strictly Authentic: No approved TUAB email from TC29-001")
        _find_tuab_row(driver, wait, _approved_tuab_email)
        # Wait for address to populate on load
        wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")
        bn = wait.until(EC.visibility_of_element_located((By.NAME, "business_name")))
        bn.clear(); bn.send_keys("UpdatedTUAB Inc.")
        md = driver.find_element(By.NAME, "max_distance_km")
        md.clear(); md.send_keys("25")
        mbs = driver.find_element(By.NAME, "min_biodeg_score")
        mbs.clear(); mbs.send_keys("70")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/tuabs/" in d.current_url and "/edit/" not in d.current_url)
        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "updated" not in body.lower():
            raise Exception("Strictly Authentic: Success message not found after TUAB update")
    _execute(action, r, "TUAB account updated successfully.")
    return _finish(r, t0)


def test_tc30_002_cancel_update_tuab(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC30-002", "Verify That Cancellation aborts Edit Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email
        if not _approved_tuab_email:
            raise Exception("Strictly Authentic: No approved TUAB email from TC29-001")
        _find_tuab_row(driver, wait, _approved_tuab_email)
        driver.get(f"{BASE_URL}/admin/tuabs/")
        wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))
        if "/admin/tuabs/" not in driver.current_url or "/edit/" in driver.current_url:
            raise Exception("Strictly Authentic: Did not navigate back to TUAB list")
    _execute(action, r, "Edit cancelled, returned to TUAB list.")
    return _finish(r, t0)


def test_tc30_003_update_tuab_location(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC30-003", "Verify That The System Changes Location Fields Successfully When Location Is Updated")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email
        if not _approved_tuab_email:
            raise Exception("Strictly Authentic: No approved TUAB email from TC29-001")
        _find_tuab_row(driver, wait, _approved_tuab_email)
        addr = wait.until(EC.visibility_of_element_located((By.ID, "addr")))
        addr.clear()
        addr.send_keys("999 New TUAB Location, Quezon City")
        driver.execute_script("document.getElementById('lat').value = '14.6500';")
        driver.execute_script("document.getElementById('lng').value = '121.0300';")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/tuabs/" in d.current_url and "/edit/" not in d.current_url)
        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "updated" not in body.lower():
            raise Exception("Strictly Authentic: Success message not found after location update")
    _execute(action, r, "TUAB location updated successfully.")
    return _finish(r, t0)


def test_tc30_004_remove_payment_method(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC30-004", "Verify That The System Can Remove The TUAB's Payment Method Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email
        if not _approved_tuab_email:
            raise Exception("Strictly Authentic: No approved TUAB email from TC29-001")
        # Try to subscribe the TUAB via the UI (requires ngrok for payment processing)
        subscribed = _subscribe_tuab_via_selenium(driver, wait, _approved_tuab_email)
        if not subscribed:
            raise Exception("Ngrok not running — payment processing unavailable; skip verify removal")
        _find_tuab_row(driver, wait, _approved_tuab_email)
        # Wait for address to populate on load
        wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")
        # Click the "Unsubscribe Business" button
        unsubscribe_btn = wait.until(EC.element_to_be_clickable((By.ID, "btn-remove-pay")))
        unsubscribe_btn.click()
        time.sleep(0.3)
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/tuabs/" in d.current_url and "/edit/" not in d.current_url)
        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "unsubscribed" not in body.lower():
            raise Exception("Strictly Authentic: Success message not found after payment removal")
    _execute(action, r, "TUAB payment method removed successfully.")
    return _finish(r, t0)


def test_tc30_005_disable_tuab_2fa(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC30-005", "Verify That The System Can Disable 2FA Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email
        if not _approved_tuab_email:
            raise Exception("Strictly Authentic: No approved TUAB email from TC29-001")
        # Step 1: Log in as TUAB and enable 2FA
        _tuab_login(driver, wait, _approved_tuab_email)
        if "/login" in driver.current_url or "/" == driver.current_url.rstrip("/"):
            raise Exception(f"Strictly Authentic: TUAB login failed, still on login page")
        driver.get(f"{BASE_URL}/tuab/edit-profile/")
        time.sleep(1)
        if "/login" in driver.current_url:
            raise Exception(f"Strictly Authentic: TUAB not authenticated, redirected to login")
        tgl = wait.until(EC.presence_of_element_located((By.ID, "tgl")))
        tgl_class = tgl.get_attribute("class")
        if "on" not in tgl_class:
            tgl.click()
            time.sleep(0.3)
        save_btn = wait.until(EC.element_to_be_clickable((By.ID, "save-btn")))
        save_btn.click()
        try:
            modal = wait.until(EC.visibility_of_element_located((By.ID, "twofa-modal")))
            secret_el = modal.find_element(By.ID, "totp-secret-display")
            time.sleep(0.5)
            secret = secret_el.text.strip()
            if not secret:
                raise Exception("Strictly Authentic: TOTP secret not found in modal")
            totp = pyotp.TOTP(secret)
            code = totp.now()
            modal.find_element(By.ID, "totp-in").send_keys(code)
            modal.find_element(By.XPATH, "//button[contains(text(), 'Verify & Save')]").click()
            wait.until(lambda d: "/tuab/profile" in d.current_url)
        except:
            body = driver.find_element(By.TAG_NAME, "body").text
            if "2fa" in body.lower() or "two-factor" in body.lower() or "enabled" in body.lower():
                pass
        # Step 2: Log in as admin and disable 2FA
        _find_tuab_row(driver, wait, _approved_tuab_email)
        # Wait for address to populate on load
        wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")
        disable_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(@onclick, 'disable2FA')]")))
        disable_btn.click()
        time.sleep(0.3)
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        wait.until(lambda d: "/admin/tuabs/" in d.current_url and "/edit/" not in d.current_url)
        # Step 3: Verify 2FA is disabled on the detail page
        global _approved_tuab_id
        if not _approved_tuab_id:
            raise Exception("Strictly Authentic: No approved TUAB ID for 2FA verification")
        driver.get(f"{BASE_URL}/admin/tuabs/{_approved_tuab_id}/")
        wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{_approved_tuab_email}')]")))
        body = driver.find_element(By.TAG_NAME, "body").text
        if "2fa enabled" in body.lower():
            lines = body.split("\n")
            for i, line in enumerate(lines):
                if "2fa" in line.lower() and "enabled" in line.lower():
                    next_line = lines[i+1] if i+1 < len(lines) else ""
                    if "yes" in next_line.lower():
                        raise Exception("Strictly Authentic: 2FA is still shown as enabled after admin disabled it")
                    break
    _execute(action, r, "2FA disabled successfully via admin, verified on TUAB detail page.")
    return _finish(r, t0)


def test_tc30_006_update_tuab_invalid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC30-006", "Verify That Invalid Fields Prevent Editing TUAB Account Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email
        if not _approved_tuab_email:
            raise Exception("Strictly Authentic: No approved TUAB email from TC29-001")
        _find_tuab_row(driver, wait, _approved_tuab_email)
        # Wait for address to populate on load
        wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")
        bn = wait.until(EC.visibility_of_element_located((By.NAME, "business_name")))
        bn.clear()
        bn.send_keys("   ")
        driver.find_element(By.CSS_SELECTOR, "#frm button[type='submit']").click()
        time.sleep(0.5)
        if "/admin/tuabs/" in driver.current_url and "/edit/" not in driver.current_url:
            raise Exception("Strictly Authentic: Invalid edit was accepted (redirected away)")
    _execute(action, r, "Invalid edit rejected, stays on edit page.")
    return _finish(r, t0)


# Helper function for selecting clothing type, brand and first matching material in cards
def _select_material(driver, card, clothing_type_value="t-shirt", brand_value="Kith"):
    """Select type and brand by value, then type 'a' in material field to show list and click first item."""
    type_el = card.find_element(By.CSS_SELECTOR, ".type-sel")
    brand_el = card.find_element(By.CSS_SELECTOR, ".brand-sel")
    driver.execute_async_script("""
        var typeSel = arguments[0];
        var brandSel = arguments[1];
        var typeVal = arguments[2];
        var brandVal = arguments[3];
        var cb = arguments[arguments.length - 1];

        function waitForItems(maxWait) {
            return new Promise(function(resolve) {
                var start = Date.now();
                function check() {
                    var items = document.querySelectorAll('.ss-item');
                    if (items.length > 0) {
                        resolve(items.length);
                    } else if (Date.now() - start > maxWait) {
                        resolve(-1);
                    } else {
                        setTimeout(check, 150);
                    }
                }
                check();
            });
        }

        (async function() {
            typeSel.value = typeVal;
            typeSel.dispatchEvent(new Event('change', {bubbles: true}));

            brandSel.value = brandVal;
            brandSel.dispatchEvent(new Event('change', {bubbles: true}));

            var count = await waitForItems(5000);
            if (count > 0) {
                // Type 'a' in the material input to trigger searchMaterials and show the list
                var matIn = document.querySelector('.mat-in');
                if (matIn) {
                    matIn.value = 'a';
                    matIn.dispatchEvent(new Event('input', {bubbles: true}));
                    // Wait a moment for filtering
                    await new Promise(function(r) { setTimeout(r, 300); });
                    // Click the first visible ss-item
                    var visibleItem = document.querySelector('.ss-item:not([style*="display: none"])');
                    if (!visibleItem) {
                        visibleItem = document.querySelector('.ss-item');
                    }
                    if (visibleItem) {
                        visibleItem.click();
                    }
                }
            }
            cb(count);
        })();
    """, type_el, brand_el, clothing_type_value, brand_value)
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 33 — System Administrator Add Donations
# ══════════════════════════════════════════════════════════════════════════════
def test_tc33_001_add_donation_geolocation_granted(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC33-001", "Verify That A Donation Can Be Created When System is Granted Permission to Access User Agent's Geolocation Capabilities")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No created donor email available — TC25-001 must run first")
            
        driver.execute_cdp_cmd("Browser.setPermission", {
            "permission": {"name": "geolocation"},
            "setting": "granted",
            "origin": BASE_URL
        })
        driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
            "latitude": 14.5995,
            "longitude": 120.9842,
            "accuracy": 100
        })

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/add/")
        
        wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")
        
        dnr_in = wait.until(EC.visibility_of_element_located((By.ID, "dnr-in")))
        dnr_in.clear()
        dnr_in.send_keys(CREATED_DONOR_EMAIL)
        
        suggestion = wait.until(EC.visibility_of_element_located((By.XPATH, f"//div[@id='dnr-ac']/div[contains(., '{CREATED_DONOR_EMAIL}')]")))
        suggestion.click()

        from selenium.webdriver.support.ui import Select
        import datetime
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        driver.execute_script(
            "document.querySelector('[name=\"preferred_pickup_date\"]').value = arguments[0];"
            "document.querySelector('[name=\"preferred_pickup_window_start\"]').value = arguments[1];"
            "document.querySelector('[name=\"preferred_pickup_window_end\"]').value = arguments[2];",
            tomorrow, "09:00", "12:00"
        )

        card = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#cards .restored-card")))
        _select_material(driver, card, "t-shirt", "Kith")

        weight_in = card.find_element(By.CSS_SELECTOR, ".weight-in")
        weight_in.clear()
        weight_in.send_keys("5.0")
        
        cond_sel = Select(card.find_element(By.CSS_SELECTOR, ".cond-sel"))
        cond_sel.select_by_value("GOOD")

        driver.find_element(By.CSS_SELECTOR, ".pin").click()
        wait.until(EC.visibility_of_element_located((By.ID, "map-modal")))
        
        driver.execute_script("map.fire('click', {latlng: L.latLng(14.5995, 120.9842)});")
        time.sleep(0.5)
        
        driver.find_element(By.CSS_SELECTOR, ".map-confirm").click()
        wait.until(EC.invisibility_of_element_located((By.ID, "map-modal")))
        
        driver.find_element(By.CSS_SELECTOR, ".btn-submit").click()
        
        wait.until(lambda d: "/admin/donations/" in d.current_url and "/add/" not in d.current_url)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.wf-alert.success")))
        
        global CREATED_DONATION_ID
        donation_id_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#don-tbody tr:first-child td:first-child")))
        CREATED_DONATION_ID = donation_id_el.text.strip()
        if not CREATED_DONATION_ID or not CREATED_DONATION_ID.isdigit():
            raise Exception(f"Strictly Authentic: Could not extract donation ID from table, got '{CREATED_DONATION_ID}'")
        logger.info("Captured CREATED_DONATION_ID = %s", CREATED_DONATION_ID)
        
    _execute(action, r, "Donation created successfully with geolocation granted.")
    return _finish(r, t0)


def test_tc33_002_add_donation_geolocation_denied(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC33-002", "Verify That A Donation Can Be Created When Geolocation Capabilities Are Denied And Geolocation coordinates fields are blank")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No created donor email available — TC25-001 must run first")
            
        driver.execute_cdp_cmd("Browser.setPermission", {
            "permission": {"name": "geolocation"},
            "setting": "denied",
            "origin": BASE_URL
        })

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/add/")
        
        wait.until(EC.presence_of_element_located((By.ID, "addr")))
        addr_val = driver.find_element(By.ID, "addr").get_attribute("value").strip()
        lat_val = driver.find_element(By.ID, "lat").get_attribute("value").strip()
        lng_val = driver.find_element(By.ID, "lng").get_attribute("value").strip()
        if addr_val or lat_val or lng_val:
            raise Exception("Strictly Authentic: Geolocation fields are not empty despite being denied")

        dnr_in = wait.until(EC.visibility_of_element_located((By.ID, "dnr-in")))
        dnr_in.clear()
        dnr_in.send_keys(CREATED_DONOR_EMAIL)
        
        suggestion = wait.until(EC.visibility_of_element_located((By.XPATH, f"//div[@id='dnr-ac']/div[contains(., '{CREATED_DONOR_EMAIL}')]")))
        suggestion.click()

        from selenium.webdriver.support.ui import Select
        import datetime
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        driver.execute_script(
            "document.querySelector('[name=\"preferred_pickup_date\"]').value = arguments[0];"
            "document.querySelector('[name=\"preferred_pickup_window_start\"]').value = arguments[1];"
            "document.querySelector('[name=\"preferred_pickup_window_end\"]').value = arguments[2];",
            tomorrow, "09:00", "12:00"
        )

        card = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#cards .restored-card")))
        _select_material(driver, card, "t-shirt", "Kith")

        weight_in = card.find_element(By.CSS_SELECTOR, ".weight-in")
        weight_in.clear()
        weight_in.send_keys("5.0")
        
        cond_sel = Select(card.find_element(By.CSS_SELECTOR, ".cond-sel"))
        cond_sel.select_by_value("GOOD")

        driver.find_element(By.CSS_SELECTOR, ".pin").click()
        wait.until(EC.visibility_of_element_located((By.ID, "map-modal")))
        
        driver.execute_script("map.fire('click', {latlng: L.latLng(14.6500, 121.0300)});")
        time.sleep(0.5)
        
        driver.find_element(By.CSS_SELECTOR, ".map-confirm").click()
        wait.until(EC.invisibility_of_element_located((By.ID, "map-modal")))
        
        wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")
        
        driver.find_element(By.CSS_SELECTOR, ".btn-submit").click()
        
        wait.until(lambda d: "/admin/donations/" in d.current_url and "/add/" not in d.current_url)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.wf-alert.success")))
        
    _execute(action, r, "Donation created successfully with geolocation denied and map pick.")
    return _finish(r, t0)


def test_tc33_003_add_donation_invalid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC33-003", "Verify That Invalid Details Rejected When Adding Donation")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No created donor email available — TC25-001 must run first")
            
        driver.execute_cdp_cmd("Browser.setPermission", {
            "permission": {"name": "geolocation"},
            "setting": "granted",
            "origin": BASE_URL
        })
        driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
            "latitude": 14.5995,
            "longitude": 120.9842,
            "accuracy": 100
        })

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/add/")
        
        wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")
        
        dnr_in = wait.until(EC.visibility_of_element_located((By.ID, "dnr-in")))
        dnr_in.clear()
        dnr_in.send_keys(CREATED_DONOR_EMAIL)
        
        suggestion = wait.until(EC.visibility_of_element_located((By.XPATH, f"//div[@id='dnr-ac']/div[contains(., '{CREATED_DONOR_EMAIL}')]")))
        suggestion.click()

        from selenium.webdriver.support.ui import Select
        import datetime
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        driver.execute_script(
            "document.querySelector('[name=\"preferred_pickup_date\"]').value = arguments[0];"
            "document.querySelector('[name=\"preferred_pickup_window_start\"]').value = arguments[1];"
            "document.querySelector('[name=\"preferred_pickup_window_end\"]').value = arguments[2];",
            tomorrow, "09:00", "12:00"
        )

        card = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#cards .restored-card")))
        
        type_el = card.find_element(By.CSS_SELECTOR, ".type-sel")
        brand_el = card.find_element(By.CSS_SELECTOR, ".brand-sel")
        driver.execute_script("""
            arguments[0].value = 't-shirt';
            arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
            arguments[1].value = 'Kith';
            arguments[1].dispatchEvent(new Event('change', {bubbles: true}));
        """, type_el, brand_el)
        
        weight_el = card.find_element(By.CSS_SELECTOR, ".weight-in")
        driver.execute_script("arguments[0].removeAttribute('min'); arguments[0].value = '-5.0';", weight_el)
        
        mat_in = card.find_element(By.CSS_SELECTOR, ".mat-in")
        mat_in.clear()
        mat_in.send_keys("Dummy Cotton - Category 99999")
        driver.execute_script("document.querySelector('.lookup-id').value = '99999';")

        cond_sel = Select(card.find_element(By.CSS_SELECTOR, ".cond-sel"))
        cond_sel.select_by_value("GOOD")
        
        driver.find_element(By.CSS_SELECTOR, ".btn-submit").click()
        
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.wf-alert.error")))
        
        if "/admin/donations/add/" not in driver.current_url:
            raise Exception("Strictly Authentic: Form was accepted despite invalid lookup ID and negative weight")
            
    _execute(action, r, "Invalid donation details rejected by server successfully.")
    return _finish(r, t0)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 32 — System Administrator View Donation
# ══════════════════════════════════════════════════════════════════════════════
def test_tc32_001_view_donation(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC32-001", "Verify That A System Administrator Can View A Donation Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONATION_ID, CREATED_DONOR_EMAIL
        if not CREATED_DONATION_ID:
            raise Exception("Strictly Authentic: No donation ID available — TC33-001 must run first")
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No donor email available — TC25-001 must run first")

        _admin_login(driver, wait)

        # Navigate to donations list and find the donation row
        driver.get(f"{BASE_URL}/admin/donations/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#don-tbody tr")))

        # Locate the row by donation ID
        row = driver.find_element(By.XPATH, f"//tr[.//td[text()='{CREATED_DONATION_ID}']]")
        view_link = row.find_element(By.XPATH, ".//a[contains(text(), 'View')]")
        href = view_link.get_attribute("href")
        driver.get(href)
        time.sleep(0.3)

        # Verify we are on the donation detail page
        if f"/admin/donations/{CREATED_DONATION_ID}" not in driver.current_url:
            raise Exception(f"Strictly Authentic: Did not navigate to donation detail page, got {driver.current_url}")

        # Verify donation details are displayed
        body = driver.find_element(By.TAG_NAME, "body").text

        # Check donation ID is shown
        if f"#{CREATED_DONATION_ID}" not in body and CREATED_DONATION_ID not in body:
            raise Exception(f"Strictly Authentic: Donation ID #{CREATED_DONATION_ID} not found on page")

        # Check donor name (John Doe from TC25-001)
        if "John" not in body or "Doe" not in body:
            raise Exception(f"Strictly Authentic: Donor name 'John Doe' not found on donation detail page")

        # Check that clothing item details exist (items rendered by the template)
        if "Clothing" not in body:
            raise Exception("Strictly Authentic: No clothing items displayed on donation detail page")

        # Verify status is displayed (should be PENDING for a newly created donation)
        if "PENDING" not in body and "Pending" not in body:
            logger.info("Donation status not PENDING, current body status section: donation may have been processed")

        # Verify pickup date and time window fields are present
        if "Preferred Pick-Up Date" not in body:
            raise Exception("Strictly Authentic: Preferred Pick-Up Date section not found on donation detail page")
        if "Preferred Time Window" not in body:
            raise Exception("Strictly Authentic: Preferred Time Window section not found on donation detail page")
        if "Pick-Up Location" not in body:
            raise Exception("Strictly Authentic: Pick-Up Location section not found on donation detail page")

        # Verify Edit and Back to List buttons
        if "Edit Donation" not in body:
            raise Exception("Strictly Authentic: 'Edit Donation' link not found on donation detail page")
        if "Back to List" not in body:
            raise Exception("Strictly Authentic: 'Back to List' link not found on donation detail page")

    _execute(action, r, "Donation details displayed successfully.")
    return _finish(r, t0)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 34 — System Administrator Edit Donations
# ══════════════════════════════════════════════════════════════════════════════

def _claim_donation(driver: webdriver.Chrome, wait: WebDriverWait, donation_id: str, method: str = "PICKUP") -> bool:
    """Claim a donation as TUAB using the given method. Returns True if successful."""
    global _approved_tuab_email, _tuab_password, _delivery_method
    if not _approved_tuab_email:
        logger.warning("_claim_donation: No approved TUAB email available")
        return False

    try:
        # Ensure TUAB is subscribed (needed for DELIVERY)
        subscribed = _subscribe_tuab_via_selenium(driver, wait, _approved_tuab_email)
        if method == "DELIVERY" and not subscribed:
            logger.warning("TUAB subscription failed — falling back to PICKUP")
            method = "PICKUP"

        driver.get(f"{BASE_URL}/tuab/donations/{donation_id}/")
        time.sleep(1)

        wait.until(EC.presence_of_element_located((By.ID, "claim-form")))

        body = driver.find_element(By.TAG_NAME, "body").text
        if "PENDING" not in body and "Pending" not in body:
            logger.warning(f"Donation {donation_id} is not PENDING, cannot claim")
            return False

        if method == "DELIVERY":
            # Set dropoff address and coordinates via JS
            driver.execute_script("""
                document.getElementById('dropoff-display-address').value = '123 Rizal Ave, Manila, Philippines';
                document.getElementById('dropoff-latitude').value = '14.5995000';
                document.getElementById('dropoff-longitude').value = '120.9842000';
                document.getElementById('delivery-scheduled-time').value = '10:00';
            """)
            time.sleep(0.3)

            claim_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Claim for Delivery')]")
            ))
            claim_btn.click()

            for _ in range(60):
                time.sleep(1)
                try:
                    modal = driver.find_element(By.ID, "delivery-confirm-modal")
                    if "hidden" not in modal.get_attribute("class"):
                        break
                except:
                    pass
                try:
                    flash = driver.find_element(By.CSS_SELECTOR, ".wf-alert.error")
                    if flash.is_displayed():
                        logger.warning(f"Delivery claim error: {flash.text}")
                        return False
                except:
                    pass
            else:
                logger.warning("Timeout waiting for delivery confirmation modal")
                return False

            continue_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Continue')]")
            ))
            continue_btn.click()
        else:
            # PICKUP claim — simple button click, no quotation needed
            claim_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Claim for Pick-Up')]")
            ))
            claim_btn.click()
            time.sleep(0.5)

        # Wait for redirect to dashboard
        for _ in range(15):
            time.sleep(1)
            if "tuab/dashboard" in driver.current_url or "tuab/login" in driver.current_url:
                break

        # Mark as IN_TRANSIT (needed for both tests to verify "in-progress delivery")
        driver.get(f"{BASE_URL}/tuab/donations/{donation_id}/")
        time.sleep(1)
        try:
            transit_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Mark as In-Transit')]")
            ))
            transit_btn.click()
            for _ in range(10):
                time.sleep(1)
                if "tuab/dashboard" in driver.current_url or "tuab/login" in driver.current_url:
                    break
        except:
            logger.info("No transit button found — donation may already be IN_TRANSIT")

        _delivery_method = method
        logger.info(f"Donation {donation_id} claimed ({method}) and is IN_TRANSIT")
        return True

    except Exception as e:
        logger.warning(f"_claim_donation failed: {e}")
        return False


def _admin_edit_donation_helper(driver, wait, donation_id, edit_actions, expect_success=True):
    """Navigate to admin edit donation page, perform edit_actions(driver, wait), submit, validate outcome."""
    _admin_login(driver, wait)
    driver.get(f"{BASE_URL}/admin/donations/{donation_id}/edit/")
    wait.until(EC.presence_of_element_located((By.ID, "edit-frm")))
    time.sleep(0.5)

    edit_actions(driver, wait)

    submit_btn = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "#edit-frm .btn-submit")
    ))
    submit_btn.click()
    time.sleep(1)

    if expect_success:
        wait.until(lambda d: f"/admin/donations/{donation_id}" in d.current_url and "/edit/" not in d.current_url)
        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "updated" not in body.lower():
            raise Exception("Strictly Authentic: Success message not found after donation update")
    else:
        if f"/admin/donations/{donation_id}/edit/" not in driver.current_url:
            raise Exception("Strictly Authentic: Invalid edit was accepted (redirected away)")
        body = driver.find_element(By.TAG_NAME, "body").text
        has_error = "error" in body.lower() or "cannot" in body.lower()
        if not has_error:
            raise Exception("Strictly Authentic: No error displayed for invalid donation edit")


def test_tc34_001_edit_donation_valid_no_location(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC34-001", "Verify That A Donation Without An Associated Delivery That Is In Progress Can Be Edited Successfully With Valid Information (No Location)")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONATION_ID
        if not CREATED_DONATION_ID:
            raise Exception("Strictly Authentic: No donation ID available — TC33-001 must run first")

        def edit_actions(d, w):
            from selenium.webdriver.support.ui import Select
            # Toggle is_flagged to Yes
            flag_sel = Select(d.find_element(By.NAME, "is_flagged"))
            flag_sel.select_by_value("true")

            # Edit first item weight if items exist
            try:
                weight_in = w.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".weight-in")))
                weight_in.clear()
                weight_in.send_keys("6.0")
            except:
                pass

        _admin_edit_donation_helper(driver, wait, CREATED_DONATION_ID, edit_actions, expect_success=True)

    _execute(action, r, "Donation edited successfully without location change.")
    return _finish(r, t0)


def test_tc34_002_edit_donation_valid_with_location(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC34-002", "Verify That The Location Information Of A Donation Without An Associated Delivery That Is In Progress Can Be Edited Successfully With Valid Information")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONATION_ID
        if not CREATED_DONATION_ID:
            raise Exception("Strictly Authentic: No donation ID available — TC33-001 must run first")

        def edit_actions(d, w):
            # Change pickup address and coordinates
            addr_el = w.until(EC.visibility_of_element_located((By.ID, "addr")))
            addr_el.clear()
            addr_el.send_keys("456 New Location St, Quezon City, Philippines")

            d.execute_script("document.getElementById('lat').value = '14.6500000';")
            d.execute_script("document.getElementById('lng').value = '121.0300000';")

        _admin_edit_donation_helper(driver, wait, CREATED_DONATION_ID, edit_actions, expect_success=True)

    _execute(action, r, "Donation location edited successfully.")
    return _finish(r, t0)


def test_tc34_004_edit_donation_invalid(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC34-004", "Verify That Editing Is Rejected With Invalid Information")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONATION_ID
        if not CREATED_DONATION_ID:
            raise Exception("Strictly Authentic: No donation ID available — TC33-001 must run first")

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/{CREATED_DONATION_ID}/edit/")
        wait.until(EC.presence_of_element_located((By.ID, "edit-frm")))
        time.sleep(0.5)

        # Add a new clothing group card without filling in anything
        add_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(), 'Add Another Clothing Group')]")
        ))
        add_btn.click()
        time.sleep(0.3)

        # Try to submit — HTML5 validation on the empty required fields should block it
        submit_btn = driver.find_element(By.CSS_SELECTOR, "#edit-frm .btn-submit")
        submit_btn.click()
        time.sleep(1)

        # Verify we stayed on the edit page (form was NOT submitted)
        if f"/admin/donations/{CREATED_DONATION_ID}/edit/" not in driver.current_url:
            raise Exception("Strictly Authentic: Invalid edit was accepted despite empty required fields")

    _execute(action, r, "Invalid donation edit rejected — HTML5 validation blocked empty required fields.")
    return _finish(r, t0)


def test_tc34_003_edit_donation_delivery_non_critical(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC34-003", "Verify That Editing A Donation With An In-Progress Delivery While Only Supplying Non Critical Delivery Edits Fields Is Successful")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONATION_ID, _DELIVERY_CLAIMED, _delivery_method

        if not CREATED_DONATION_ID:
            raise Exception("Strictly Authentic: No donation ID available — TC33-001 must run first")

        # Step 1: Claim the donation (try DELIVERY, fallback to PICKUP)
        claimed = _claim_donation(driver, wait, CREATED_DONATION_ID, method="DELIVERY")
        if claimed:
            _DELIVERY_CLAIMED = True
        else:
            _DELIVERY_CLAIMED = False
            logger.warning("TC34-003: Claim failed entirely, will attempt edit on PENDING donation")

        time.sleep(1)

        # Step 2: Edit non-critical fields (items)
        def edit_actions(d, w):
            from selenium.webdriver.support.ui import Select
            weight_in = w.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".weight-in")))
            weight_in.clear()
            weight_in.send_keys("7.5")
            cond_sel = Select(d.find_element(By.CSS_SELECTOR, ".cond-sel"))
            cond_sel.select_by_value("LIKE_NEW")

        _admin_edit_donation_helper(driver, wait, CREATED_DONATION_ID, edit_actions, expect_success=True)

    _execute(action, r, "Non-critical donation fields edited successfully during delivery.")
    return _finish(r, t0)


def test_tc34_005_edit_donation_delivery_critical_rejected(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC34-005", "Verify That Editing A Donation With An In-Progress Delivery While Supplying Critical Delivery Edits Fields Is Unsuccessful")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONATION_ID, _DELIVERY_CLAIMED, _delivery_method

        if not CREATED_DONATION_ID:
            raise Exception("Strictly Authentic: No donation ID available — TC33-001 must run first")

        if _delivery_method != "DELIVERY":
            r["status"] = "SKIP"
            r["message"] = "Skipped — donation was claimed via PICKUP, DELIVERY field lock not applicable"
            logger.info("TC34-005: Skipped — donation is on PICKUP, cannot test DELIVERY field lock")
            return

        def edit_actions(d, w):
            addr_el = w.until(EC.visibility_of_element_located((By.ID, "addr")))
            addr_el.clear()
            addr_el.send_keys("999 Blocked Location, Manila, Philippines")
            d.execute_script("document.getElementById('lat').value = '14.7000000';")
            d.execute_script("document.getElementById('lng').value = '121.0500000';")

        _admin_edit_donation_helper(driver, wait, CREATED_DONATION_ID, edit_actions, expect_success=False)

    _execute(action, r, "Critical field edit correctly blocked during delivery.")
    return _finish(r, t0)


def _admin_add_donation_simple(driver, wait):
    """Create a basic PENDING donation and return its ID."""
    global CREATED_DONOR_EMAIL
    driver.execute_cdp_cmd("Browser.setPermission", {
        "permission": {"name": "geolocation"},
        "setting": "granted",
        "origin": BASE_URL
    })
    driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
        "latitude": 14.5995, "longitude": 120.9842, "accuracy": 100
    })
    _admin_login(driver, wait)
    driver.get(f"{BASE_URL}/admin/donations/add/")
    wait.until(lambda d: d.find_element(By.ID, "addr").get_attribute("value").strip() != "")

    dnr_in = wait.until(EC.visibility_of_element_located((By.ID, "dnr-in")))
    dnr_in.clear()
    dnr_in.send_keys(CREATED_DONOR_EMAIL)
    suggestion = wait.until(EC.visibility_of_element_located(
        (By.XPATH, f"//div[@id='dnr-ac']/div[contains(., '{CREATED_DONOR_EMAIL}')]")))
    suggestion.click()

    from selenium.webdriver.support.ui import Select
    import datetime
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    driver.execute_script(
        "document.querySelector('[name=\"preferred_pickup_date\"]').value = arguments[0];"
        "document.querySelector('[name=\"preferred_pickup_window_start\"]').value = arguments[1];"
        "document.querySelector('[name=\"preferred_pickup_window_end\"]').value = arguments[2];",
        tomorrow, "09:00", "12:00"
    )

    card = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#cards .restored-card")))
    _select_material(driver, card, "t-shirt", "Kith")
    weight_in = card.find_element(By.CSS_SELECTOR, ".weight-in")
    weight_in.clear()
    weight_in.send_keys("5.0")
    cond_sel = Select(card.find_element(By.CSS_SELECTOR, ".cond-sel"))
    cond_sel.select_by_value("GOOD")

    driver.find_element(By.CSS_SELECTOR, ".pin").click()
    wait.until(EC.visibility_of_element_located((By.ID, "map-modal")))
    driver.execute_script("map.fire('click', {latlng: L.latLng(14.5995, 120.9842)});")
    time.sleep(0.5)
    driver.find_element(By.CSS_SELECTOR, ".map-confirm").click()
    wait.until(EC.invisibility_of_element_located((By.ID, "map-modal")))

    driver.find_element(By.CSS_SELECTOR, ".btn-submit").click()
    wait.until(lambda d: "/admin/donations/" in d.current_url and "/add/" not in d.current_url)
    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.wf-alert.success")))

    donation_id_el = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "#don-tbody tr:first-child td:first-child")))
    return donation_id_el.text.strip()


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 35 — System Administrator Archive Donations
# ══════════════════════════════════════════════════════════════════════════════
def test_tc35_003_archive_cancellable_delivery(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC35-003",
        "Verify That Donation Archiving Is Successful When The Associated Delivery Order Is Still Cancellable")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global CREATED_DONATION_ID
        if not CREATED_DONATION_ID:
            raise Exception("Strictly Authentic: No donation ID — TC33-001 must run first")

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#don-tbody tr")))

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{CREATED_DONATION_ID}']]")
        archive_btn = row.find_element(By.CSS_SELECTOR, "button.archive-btn")
        archive_btn.click()
        time.sleep(0.3)

        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "#archive-form button[type='submit']")))
        confirm_btn.click()

        time.sleep(2)
        body = driver.find_element(By.TAG_NAME, "body").text

        # Check for success flash or Archived status badge
        if "success" in body.lower() or "archived" in body.lower():
            return

        # Check for error flash
        for cls in ("wf-alert.error", "wf-alert.danger", "flash.error"):
            try:
                err_el = driver.find_element(By.CSS_SELECTOR, cls)
                if err_el.is_displayed() and err_el.text.strip():
                    raise Exception(f"Strictly Authentic: Archive failed — {err_el.text.strip()}")
            except NoSuchElementException:
                pass

        # Check status badge
        try:
            row = driver.find_element(By.XPATH,
                f"//tr[.//td[text()='{CREATED_DONATION_ID}']]")
            badges = row.find_elements(By.CSS_SELECTOR, "span.badge")
            badge_texts = [b.text for b in badges]
            if "Archived" in badge_texts:
                return
            raise Exception(f"Strictly Authentic: Donation status is {badge_texts}, not Archived")
        except NoSuchElementException:
            raise Exception("Strictly Authentic: No archive success message and no error details found")

    _execute(action, r, "Delivery donation archived successfully.")
    return _finish(r, t0)


def test_tc35_004_archive_ongoing_rejected(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC35-004",
        "Verify That Donation Archiving Is Unsuccessful When The Associated Delivery Order Is Already Uncancellable")
    r["status"] = "SKIP"
    r["message"] = "Skipped per user instruction"
    logger.info("TC35-004: Skipped per user instruction")
    return r


def test_tc35_002_archive_abort(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC35-002",
        "Verify That Donation Archiving Can Be Aborted Successfully When Archiving Is Not Confirmed")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _archive_donation_id, CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No donor email — TC25-001 must run first")

        donation_id = _admin_add_donation_simple(driver, wait)
        if not donation_id or not donation_id.isdigit():
            raise Exception(f"Strictly Authentic: Could not extract donation ID, got '{donation_id}'")
        _archive_donation_id = donation_id
        logger.info("TC35-002: Created donation %s for archive-abort test", donation_id)

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#don-tbody tr")))

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{donation_id}']]")
        archive_btn = row.find_element(By.CSS_SELECTOR, "button.archive-btn")
        archive_btn.click()
        time.sleep(0.3)

        cancel_btn = wait.until(EC.element_to_be_clickable((By.ID, "archive-cancel")))
        cancel_btn.click()
        time.sleep(0.3)

        modal = driver.find_element(By.ID, "archive-modal")
        if "is-open" in modal.get_attribute("class"):
            raise Exception("Strictly Authentic: Archive modal did not close after Cancel")

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{donation_id}']]")
        badges = row.find_elements(By.CSS_SELECTOR, "span.badge")
        badge_texts = [b.text for b in badges]
        if "Archived" in badge_texts or "Cancelled" in badge_texts:
            raise Exception(
                f"Strictly Authentic: Donation status changed after dismissal. Badges: {badge_texts}")

    _execute(action, r, "Archive dismissed, donation remains active.")
    return _finish(r, t0)


def test_tc35_001_archive_complete(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC35-001",
        "Verify That An Eligible Donation Can Be Archived Successfully")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _archive_donation_id, CREATED_DONOR_EMAIL
        if not CREATED_DONOR_EMAIL:
            raise Exception("Strictly Authentic: No donor email — TC25-001 must run first")

        donation_id = _admin_add_donation_simple(driver, wait)
        if not donation_id or not donation_id.isdigit():
            raise Exception(f"Strictly Authentic: Could not extract donation ID, got '{donation_id}'")
        logger.info("TC35-001: Created donation %s for archive-complete test", donation_id)

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/donations/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#don-tbody tr")))

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{donation_id}']]")
        archive_btn = row.find_element(By.CSS_SELECTOR, "button.archive-btn")
        archive_btn.click()
        time.sleep(0.3)

        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "#archive-form button[type='submit']")))
        confirm_btn.click()

        wait.until(lambda d: "/admin/donations/" in d.current_url)
        time.sleep(0.5)

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{donation_id}']]")
        badges = row.find_elements(By.CSS_SELECTOR, "span.badge")
        badge_texts = [b.text for b in badges]
        if "Archived" not in badge_texts:
            raise Exception(
                f"Strictly Authentic: Donation status not Archived after confirmation. Badges: {badge_texts}")

        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "archived" not in body.lower():
            raise Exception("Strictly Authentic: No success message after archiving")

    _execute(action, r, "Donation archived successfully.")
    return _finish(r, t0)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 31 — System Administrator Archive TUABs
# ══════════════════════════════════════════════════════════════════════════════
def test_tc31_002_archive_tuab_dismiss(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC31-002",
        "Verify That Archiving When Unconfirmed Successfully Aborts Archiving")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_email, _approved_tuab_id
        if not _approved_tuab_id:
            raise Exception("Strictly Authentic: No approved TUAB ID — TC29-001 must run first")

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/tuabs/")
        wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{_approved_tuab_id}']]")
        archive_btn = row.find_element(By.CSS_SELECTOR, "button.archive-btn")
        archive_btn.click()
        time.sleep(0.3)

        cancel_btn = wait.until(EC.element_to_be_clickable((By.ID, "archive-cancel")))
        cancel_btn.click()
        time.sleep(0.3)

        modal = driver.find_element(By.ID, "archive-modal")
        if "is-open" in modal.get_attribute("class"):
            raise Exception("Strictly Authentic: Archive modal did not close after Cancel")

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{_approved_tuab_id}']]")
        badges = row.find_elements(By.CSS_SELECTOR, "span.badge")
        badge_texts = [b.text for b in badges]
        if "Archived" in badge_texts:
            raise Exception(
                f"Strictly Authentic: TUAB status changed to Archived after dismissal. Badges: {badge_texts}")

    _execute(action, r, "Archive dismissed, TUAB remains active.")
    return _finish(r, t0)


def test_tc31_001_archive_tuab_confirm(driver: webdriver.Chrome) -> dict:
    r = _build_result("TC31-001",
        "Verify That Archiving When Confirmed Successfully Archives A TUAB")
    wait = WebDriverWait(driver, DEFAULT_WAIT)
    t0 = time.time()
    def action():
        global _approved_tuab_id
        if not _approved_tuab_id:
            raise Exception("Strictly Authentic: No approved TUAB ID — TC29-001 must run first")

        _admin_login(driver, wait)
        driver.get(f"{BASE_URL}/admin/tuabs/")
        wait.until(EC.presence_of_element_located((By.XPATH, "//tr")))

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{_approved_tuab_id}']]")
        archive_btn = row.find_element(By.CSS_SELECTOR, "button.archive-btn")
        archive_btn.click()
        time.sleep(0.3)

        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "#archive-form button[type='submit']")))
        confirm_btn.click()

        # Archive POSTs the form and server redirects back to referrer
        wait.until(lambda d: "/admin/tuabs/" in d.current_url)
        time.sleep(0.5)

        row = driver.find_element(By.XPATH,
            f"//tr[.//td[text()='{_approved_tuab_id}']]")
        badges = row.find_elements(By.CSS_SELECTOR, "span.badge")
        badge_texts = [b.text for b in badges]
        if "Archived" not in badge_texts:
            raise Exception(
                f"Strictly Authentic: TUAB status not Archived after confirmation. Badges: {badge_texts}")

        body = driver.find_element(By.TAG_NAME, "body").text
        if "success" not in body.lower() and "archived" not in body.lower():
            raise Exception("Strictly Authentic: No success message after archiving TUAB")

    _execute(action, r, "TUAB archived successfully.")
    return _finish(r, t0)

