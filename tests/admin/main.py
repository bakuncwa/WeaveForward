"""
════════════════════════════════════════════════════════════════════════════════
Application Under Test : WeaveForward  (http://127.0.0.1:8001)
Automation Framework   : Selenium WebDriver (Python)
File                   : main.py — entry-point; runs all admin tests.

Usage
─────
    python main.py                   # headed browser
    python main.py --headless        # headless browser

Prerequisites
─────────────
    pip install selenium webdriver-manager requests
    Chrome + ChromeDriver (auto-managed by webdriver-manager)
════════════════════════════════════════════════════════════════════════════════
"""

import datetime
import sys
import time
from typing import Optional

from test_scripts import (
    LOG_FILE,
    create_driver,
    logger,
    # MODULE 23: System Administrator Login
    test_tc23_001_login_valid,
    test_tc23_002_login_2fa,
    test_tc23_003_login_invalid_credentials,
    test_tc23_004_login_invalid_totp,
    test_tc23_005_password_recovery,
    # MODULE 25: System Administrator Add Donors
    test_tc25_001_add_donor_valid,
    test_tc25_002_add_donor_invalid,
    test_tc25_003_add_donor_duplicate_email,
    # MODULE 24: System Administrator View Donors
    test_tc24_001_view_donor,
    # MODULE 26: System Administrator Edit Donors
    test_tc26_001_update_account_valid,
    test_tc26_002_cancel_update_account,
    test_tc26_003_update_account_location,
    test_tc26_004_disable_2fa,
    test_tc26_005_update_account_invalid,
    # MODULE 27: System Administrator Archive Donors
    test_tc27_002_dismiss_archive,
    test_tc27_001_archive_donor,
    # MODULE 28: System Administrator View TUABs
    test_tc28_001_view_tuab,
    # MODULE 29: System Administrator Add TUABs
    test_tc29_001_approve_tuab,
    test_tc29_002_reject_tuab_valid,
    test_tc29_003_reject_tuab_invalid,
    # MODULE 30: System Administrator Edit TUABs
    test_tc30_001_update_tuab_valid,
    test_tc30_002_cancel_update_tuab,
    test_tc30_003_update_tuab_location,
    test_tc30_004_remove_payment_method,
    test_tc30_005_disable_tuab_2fa,
    test_tc30_006_update_tuab_invalid,
    # MODULE 33: System Administrator Add Donations
    test_tc33_001_add_donation_geolocation_granted,
    test_tc33_002_add_donation_geolocation_denied,
    test_tc33_003_add_donation_invalid,
    # MODULE 32: System Administrator View Donation
    test_tc32_001_view_donation,
    # MODULE 34: System Administrator Edit Donations
    test_tc34_001_edit_donation_valid_no_location,
    test_tc34_002_edit_donation_valid_with_location,
    test_tc34_004_edit_donation_invalid,
    test_tc34_003_edit_donation_delivery_non_critical,
    test_tc34_005_edit_donation_delivery_critical_rejected,
    # MODULE 35: System Administrator Archive Donations
    test_tc35_003_archive_cancellable_delivery,
    test_tc35_004_archive_ongoing_rejected,
    test_tc35_002_archive_abort,
    test_tc35_001_archive_complete,
    # MODULE 31: System Administrator Archive TUABs
    test_tc31_002_archive_tuab_dismiss,
    test_tc31_001_archive_tuab_confirm,
)

# ──────────────────────────────────────────────────────────────────────────────
# Test suite registry
# ──────────────────────────────────────────────────────────────────────────────
TEST_SUITE = [
    # ── MODULE 23 ──────────────────────────────────────────────────────────
    {"fn": test_tc23_001_login_valid, "tc_id": "TC23-001", "workflow": "System Administrator Login", "needs_driver": True},
    {"fn": test_tc23_002_login_2fa, "tc_id": "TC23-002", "workflow": "System Administrator Login", "needs_driver": False},
    {"fn": test_tc23_003_login_invalid_credentials, "tc_id": "TC23-003", "workflow": "System Administrator Login", "needs_driver": True},
    {"fn": test_tc23_004_login_invalid_totp, "tc_id": "TC23-004", "workflow": "System Administrator Login", "needs_driver": False},
    {"fn": test_tc23_005_password_recovery, "tc_id": "TC23-005", "workflow": "System Administrator Login", "needs_driver": True},
    # ── MODULE 25 ──────────────────────────────────────────────────────────
    {"fn": test_tc25_001_add_donor_valid, "tc_id": "TC25-001", "workflow": "System Administrator Add Donors", "needs_driver": True},
    {"fn": test_tc25_002_add_donor_invalid, "tc_id": "TC25-002", "workflow": "System Administrator Add Donors", "needs_driver": True},
    {"fn": test_tc25_003_add_donor_duplicate_email, "tc_id": "TC25-003", "workflow": "System Administrator Add Donors", "needs_driver": True},
    # ── MODULE 24 ──────────────────────────────────────────────────────────
    {"fn": test_tc24_001_view_donor, "tc_id": "TC24-001", "workflow": "System Administrator View Donors", "needs_driver": True},
    # ── MODULE 26 ──────────────────────────────────────────────────────────
    {"fn": test_tc26_001_update_account_valid, "tc_id": "TC26-001", "workflow": "System Administrator Edit Donors", "needs_driver": True},
    {"fn": test_tc26_002_cancel_update_account, "tc_id": "TC26-002", "workflow": "System Administrator Edit Donors", "needs_driver": True},
    {"fn": test_tc26_003_update_account_location, "tc_id": "TC26-003", "workflow": "System Administrator Edit Donors", "needs_driver": True},
    {"fn": test_tc26_004_disable_2fa, "tc_id": "TC26-004", "workflow": "System Administrator Edit Donors", "needs_driver": True},
    {"fn": test_tc26_005_update_account_invalid, "tc_id": "TC26-005", "workflow": "System Administrator Edit Donors", "needs_driver": True},
    # ── MODULE 27 ──────────────────────────────────────────────────────────
    {"fn": test_tc27_002_dismiss_archive, "tc_id": "TC27-002", "workflow": "System Administrator Archive Donors", "needs_driver": True},
    {"fn": test_tc27_001_archive_donor, "tc_id": "TC27-001", "workflow": "System Administrator Archive Donors", "needs_driver": True},
    # ── MODULE 28 ──────────────────────────────────────────────────────────
    {"fn": test_tc28_001_view_tuab, "tc_id": "TC28-001", "workflow": "System Administrator View TUABs", "needs_driver": True},
    # ── MODULE 29 ──────────────────────────────────────────────────────────
    # TC29-001: approves the TUAB created by TC28-001
    {"fn": test_tc29_001_approve_tuab, "tc_id": "TC29-001", "workflow": "System Administrator Add TUABs", "needs_driver": True},
    # TC29-003: creates a NEW TUAB, attempts reject with empty reason → blocked
    {"fn": test_tc29_003_reject_tuab_invalid, "tc_id": "TC29-003", "workflow": "System Administrator Add TUABs", "needs_driver": True},
    # TC29-002: rejects the TUAB created by TC29-003 with a valid reason
    {"fn": test_tc29_002_reject_tuab_valid, "tc_id": "TC29-002", "workflow": "System Administrator Add TUABs", "needs_driver": True},
    # ── MODULE 30 ──────────────────────────────────────────────────────────
    {"fn": test_tc30_001_update_tuab_valid, "tc_id": "TC30-001", "workflow": "System Administrator Edit TUABs", "needs_driver": True},
    {"fn": test_tc30_002_cancel_update_tuab, "tc_id": "TC30-002", "workflow": "System Administrator Edit TUABs", "needs_driver": True},
    {"fn": test_tc30_003_update_tuab_location, "tc_id": "TC30-003", "workflow": "System Administrator Edit TUABs", "needs_driver": True},
    {"fn": test_tc30_004_remove_payment_method, "tc_id": "TC30-004", "workflow": "System Administrator Edit TUABs", "needs_driver": True},
    {"fn": test_tc30_005_disable_tuab_2fa, "tc_id": "TC30-005", "workflow": "System Administrator Edit TUABs", "needs_driver": True},
    {"fn": test_tc30_006_update_tuab_invalid, "tc_id": "TC30-006", "workflow": "System Administrator Edit TUABs", "needs_driver": True},
    # ── MODULE 33 ──────────────────────────────────────────────────────────
    {"fn": test_tc33_001_add_donation_geolocation_granted, "tc_id": "TC33-001", "workflow": "System Administrator Add Donations", "needs_driver": True},
    {"fn": test_tc33_002_add_donation_geolocation_denied, "tc_id": "TC33-002", "workflow": "System Administrator Add Donations", "needs_driver": True},
    {"fn": test_tc33_003_add_donation_invalid, "tc_id": "TC33-003", "workflow": "System Administrator Add Donations", "needs_driver": True},
    # ── MODULE 32 ──────────────────────────────────────────────────────────
    {"fn": test_tc32_001_view_donation, "tc_id": "TC32-001", "workflow": "System Administrator View Donation", "needs_driver": True},
    # ── MODULE 34 ──────────────────────────────────────────────────────────
    {"fn": test_tc34_001_edit_donation_valid_no_location, "tc_id": "TC34-001", "workflow": "System Administrator Edit Donations", "needs_driver": True},
    {"fn": test_tc34_002_edit_donation_valid_with_location, "tc_id": "TC34-002", "workflow": "System Administrator Edit Donations", "needs_driver": True},
    {"fn": test_tc34_004_edit_donation_invalid, "tc_id": "TC34-004", "workflow": "System Administrator Edit Donations", "needs_driver": True},
    {"fn": test_tc34_003_edit_donation_delivery_non_critical, "tc_id": "TC34-003", "workflow": "System Administrator Edit Donations", "needs_driver": True},
    {"fn": test_tc34_005_edit_donation_delivery_critical_rejected, "tc_id": "TC34-005", "workflow": "System Administrator Edit Donations", "needs_driver": True},
    # ── MODULE 35 ──────────────────────────────────────────────────────────
    {"fn": test_tc35_003_archive_cancellable_delivery, "tc_id": "TC35-003", "workflow": "System Administrator Archive Donations", "needs_driver": True},
    {"fn": test_tc35_004_archive_ongoing_rejected, "tc_id": "TC35-004", "workflow": "System Administrator Archive Donations", "needs_driver": False},
    {"fn": test_tc35_002_archive_abort, "tc_id": "TC35-002", "workflow": "System Administrator Archive Donations", "needs_driver": True},
    {"fn": test_tc35_001_archive_complete, "tc_id": "TC35-001", "workflow": "System Administrator Archive Donations", "needs_driver": True},
    # ── MODULE 31 ──────────────────────────────────────────────────────────
    {"fn": test_tc31_002_archive_tuab_dismiss, "tc_id": "TC31-002", "workflow": "System Administrator Archive TUABs", "needs_driver": True},
    {"fn": test_tc31_001_archive_tuab_confirm, "tc_id": "TC31-001", "workflow": "System Administrator Archive TUABs", "needs_driver": True},
]

# ──────────────────────────────────────────────────────────────────────────────
# Summary writer
# ──────────────────────────────────────────────────────────────────────────────
def _write_summary(
    selenium_results: list,
    total_seconds: float,
) -> None:
    passed  = [r for r in selenium_results if r["status"] == "PASS"]
    failed  = [r for r in selenium_results if r["status"] == "FAIL"]
    errored = [r for r in selenium_results if r["status"] == "ERROR"]
    pass_rt = (len(passed) / len(selenium_results) * 100) if selenium_results else 0.0

    sep  = "=" * 72
    dash = "─" * 72

    # Group results by workflow
    workflow_map: dict[str, list] = {}
    for r in selenium_results:
        wf = r.get("workflow", "Unknown")
        workflow_map.setdefault(wf, []).append(r)

    lines = [
        "",
        sep,
        "  WEAVEFORWARD AUTOMATION SUITE | COMPLETE TEST EXECUTION SUMMARY",
        sep,
        f"  Timestamp              : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"  AUT                    : WeaveForward",
        f"  Automation Framework   : Selenium WebDriver (Python)",
        dash,
        f"  Selenium Tests Run     : {len(selenium_results)}",
        f"  PASSED                 : {len(passed)}",
        f"  FAILED                 : {len(failed)}",
        f"  ERRORS                 : {len(errored)}",
        f"  Pass Rate              : {pass_rt:.1f}%",
        f"  Total Execution Time   : {total_seconds:.2f} s",
    ]

    lines += [dash, "  DETAILED RESULTS BY WORKFLOW", dash]

    for wf, results in workflow_map.items():
        wf_pass = sum(1 for r in results if r["status"] == "PASS")
        lines.append(f"  ▸ {wf}  ({wf_pass}/{len(results)} passed)")
        for r in results:
            icon = "✓" if r["status"] == "PASS" else ("✗" if r["status"] == "FAIL" else "!")
            lines.append(
                f"    [{icon}] {r['test_id']:8s} | {r['status']:5s} | "
                f"{r['duration_sec']:5.2f}s | {r['description']}"
            )
            if r["status"] != "PASS":
                for i, seg in enumerate(r["message"].split("\n")):
                    prefix = "           └─ " if i == 0 else "              "
                    lines.append(f"{prefix}{seg}")

    verdict = (
        "ALL SELENIUM TESTS PASSED"
        if not failed and not errored
        else f"{len(failed)} FAILED  |  {len(errored)} ERROR(S)"
    )
    lines += [dash, f"  VERDICT  :  {verdict}", sep, ""]

    block = "\n".join(lines)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(block)
    
    # Safe print for Windows consoles
    try:
        print(block)
    except UnicodeEncodeError:
        print(block.encode('ascii', 'replace').decode('ascii'))


def _write_simple_summary(
    selenium_results: list,
    total_seconds: float,
) -> None:
    """Write a plain pass/fail summary to summary.txt (overwritten each run)."""
    passed  = [r for r in selenium_results if r["status"] == "PASS"]
    failed  = [r for r in selenium_results if r["status"] != "PASS"]
    total   = len(selenium_results)
    rate    = (len(passed) / total * 100) if total else 0.0

    W = 62
    lines = [
        "=" * W,
        "  WEAVEFORWARD AUTOMATION SUITE | Test Summary",
        "=" * W,
        f"  Run         : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"  AUT         : WeaveForward",
        f"  Total TCs   : {total}",
        f"  Passed      : {len(passed)}",
        f"  Failed      : {len(failed)}",
        f"  Pass Rate   : {rate:.1f}%",
        f"  Duration    : {total_seconds:.1f}s",
        "-" * W,
        f"  {'TC':<8}  {'Result':<6}  Description",
        "-" * W,
    ]
    for r in selenium_results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        lines.append(f"  {r['test_id']:<8}  {icon:<6}  {r['description']}")
    lines += [
        "=" * W,
        f"  SELENIUM VERDICT: {len(passed)} PASSED  |  {len(failed)} FAILED",
        "=" * W,
        "",
    ]

    summary_path = "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    # Safe print for Windows consoles
    msg = f"\n[summary.txt written -> {summary_path}]"
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', 'replace').decode('ascii'))


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    headless = "--headless" in sys.argv

    logger.info("=" * 72)
    logger.info("  WEAVEFORWARD | Automated Test Run Starting")
    logger.info(f"  Date/Time   : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    logger.info(f"  AUT         : WeaveForward")
    logger.info(f"  Browser     : Google Chrome ({'headless' if headless else 'headed'})")
    logger.info(f"  Selenium TC : {len(TEST_SUITE)}")
    logger.info("=" * 72)

    selenium_results: list = []
    suite_start = datetime.datetime.now()

    driver = create_driver(headless=headless) if any(e["needs_driver"] for e in TEST_SUITE) else None

    for entry in TEST_SUITE:
        test_fn      = entry["fn"]
        tc_id        = entry["tc_id"]
        workflow     = entry["workflow"]
        needs_driver = entry["needs_driver"]

        try:
            result = test_fn(driver)
            result["workflow"] = workflow
            selenium_results.append(result)

        except Exception as exc:
            logger.exception(f"Fatal error running {tc_id}: {exc}")
            selenium_results.append({
                "test_id":      tc_id,
                "description":  tc_id,
                "workflow":     workflow,
                "status":       "ERROR",
                "message":      str(exc),
                "duration_sec": 0.0,
            })
        finally:
            if needs_driver:
                driver.delete_all_cookies()

    if driver:
        driver.quit()

    total_time = (datetime.datetime.now() - suite_start).total_seconds()
    _write_summary(selenium_results, total_time)
    _write_simple_summary(selenium_results, total_time)

    failures = [r for r in selenium_results if r["status"] != "PASS"]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
