"""
════════════════════════════════════════════════════════════════════════════════
DE LA SALLE-COLLEGE OF SAINT BENILDE
Application Under Test : WeaveForward  (http://localhost:3000)
Automation Framework   : Selenium WebDriver (Python)
File                   : main.py — entry-point; runs all 33 tests.

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
    # MODULE 1: Donor Register Account
    test_tc1_001_register_valid,
    test_tc1_002_cancel_registration,
    test_tc1_003_invalid_registration,
    test_tc1_004_duplicate_email,
    # MODULE 10: Update Account Information
    test_tc10_001_update_account_valid,
    test_tc10_002_cancel_update_account,
    test_tc10_003_update_account_location,
    test_tc10_004_disable_2fa,
    test_tc10_005_enable_2fa,
    test_tc10_006_update_account_invalid,
    test_tc10_007_update_account_invalid_totp,
    # MODULE 2: Donor Login
    test_tc2_001_login_valid,
    test_tc2_002_login_2fa,
    test_tc2_003_login_invalid_credentials,
    test_tc2_004_login_invalid_totp,
    test_tc2_005_password_recovery,
    # MODULE 3: Donor Browse TUABs
    test_tc3_001_browse_tuabs_proximity,
    test_tc3_002_browse_tuabs_no_location,
    test_tc3_003_browse_tuabs_no_filters,
    test_tc3_004_browse_tuabs_location_filter,
    test_tc3_005_browse_tuabs_invalid_filters,
    # MODULE 4: Donor View TUAB
    test_tc4_001_view_tuab_profile,
    # MODULE 5: Donor Submit Donation
    test_tc5_001_submit_donation_location,
    test_tc5_002_submit_donation_no_location,
    test_tc5_003_submit_donation_invalid,
    # MODULE 6: Donor View Donation
    test_tc6_001_view_donation,
    # MODULE 7: Donor Edit Donation
    test_tc7_001_edit_donation_no_location,
    test_tc7_002_edit_donation_location,
    test_tc7_003_edit_donation_invalid,
    test_tc7_004_edit_donation_uneditable_state,
    # MODULE 8: Donor Cancel Donation
    test_tc8_002_abort_cancel_donation,
    test_tc8_001_cancel_donation,
    test_tc8_003_cancel_donation_invalid_state,
    # MODULE 9: View Donation Impact Dashboard
    test_tc9_001_view_dashboard_filters,
    test_tc9_002_view_dashboard_no_filters,
    test_tc9_003_view_dashboard_invalid_filters,
)

# ──────────────────────────────────────────────────────────────────────────────
# Test suite registry
# ──────────────────────────────────────────────────────────────────────────────
TEST_SUITE = [
    # ── MODULE 1 ────────────────────────────────────────────────────────────
    {"fn": test_tc1_001_register_valid, "tc_id": "TC1-001", "workflow": "Donor Register Account", "needs_driver": True},
    {"fn": test_tc1_002_cancel_registration, "tc_id": "TC1-002", "workflow": "Donor Register Account", "needs_driver": True},
    {"fn": test_tc1_003_invalid_registration, "tc_id": "TC1-003", "workflow": "Donor Register Account", "needs_driver": True},
    {"fn": test_tc1_004_duplicate_email, "tc_id": "TC1-004", "workflow": "Donor Register Account", "needs_driver": True},
    # ── MODULE 10 ───────────────────────────────────────────────────────────
    {"fn": test_tc10_001_update_account_valid, "tc_id": "TC10-001", "workflow": "Donor Update Account Information", "needs_driver": True},
    {"fn": test_tc10_002_cancel_update_account, "tc_id": "TC10-002", "workflow": "Donor Update Account Information", "needs_driver": True},
    {"fn": test_tc10_003_update_account_location, "tc_id": "TC10-003", "workflow": "Donor Update Account Information", "needs_driver": True},
    {"fn": test_tc10_004_disable_2fa, "tc_id": "TC10-004", "workflow": "Donor Update Account Information", "needs_driver": True},
    {"fn": test_tc10_005_enable_2fa, "tc_id": "TC10-005", "workflow": "Donor Update Account Information", "needs_driver": True},
    {"fn": test_tc10_006_update_account_invalid, "tc_id": "TC10-006", "workflow": "Donor Update Account Information", "needs_driver": True},
    {"fn": test_tc10_007_update_account_invalid_totp, "tc_id": "TC10-007", "workflow": "Donor Update Account Information", "needs_driver": True},
    # ── MODULE 2 ────────────────────────────────────────────────────────────
    {"fn": test_tc2_001_login_valid, "tc_id": "TC2-001", "workflow": "Donor Login", "needs_driver": True},
    {"fn": test_tc2_002_login_2fa, "tc_id": "TC2-002", "workflow": "Donor Login", "needs_driver": True},
    {"fn": test_tc2_003_login_invalid_credentials, "tc_id": "TC2-003", "workflow": "Donor Login", "needs_driver": True},
    {"fn": test_tc2_004_login_invalid_totp, "tc_id": "TC2-004", "workflow": "Donor Login", "needs_driver": True},
    {"fn": test_tc2_005_password_recovery, "tc_id": "TC2-005", "workflow": "Donor Login", "needs_driver": True},
    # ── MODULE 3 ────────────────────────────────────────────────────────────
    {"fn": test_tc3_001_browse_tuabs_proximity, "tc_id": "TC3-001", "workflow": "Donor Browse TUABs", "needs_driver": True},
    {"fn": test_tc3_002_browse_tuabs_no_location, "tc_id": "TC3-002", "workflow": "Donor Browse TUABs", "needs_driver": True},
    {"fn": test_tc3_003_browse_tuabs_no_filters, "tc_id": "TC3-003", "workflow": "Donor Browse TUABs", "needs_driver": True},
    {"fn": test_tc3_004_browse_tuabs_location_filter, "tc_id": "TC3-004", "workflow": "Donor Browse TUABs", "needs_driver": True},
    {"fn": test_tc3_005_browse_tuabs_invalid_filters, "tc_id": "TC3-005", "workflow": "Donor Browse TUABs", "needs_driver": True},
    # ── MODULE 4 ────────────────────────────────────────────────────────────
    {"fn": test_tc4_001_view_tuab_profile, "tc_id": "TC4-001", "workflow": "Donor View TUAB", "needs_driver": True},
    # ── MODULE 5 ────────────────────────────────────────────────────────────
    {"fn": test_tc5_001_submit_donation_location, "tc_id": "TC5-001", "workflow": "Donor Submit Donation", "needs_driver": True},
    {"fn": test_tc5_002_submit_donation_no_location, "tc_id": "TC5-002", "workflow": "Donor Submit Donation", "needs_driver": True},
    {"fn": test_tc5_003_submit_donation_invalid, "tc_id": "TC5-003", "workflow": "Donor Submit Donation", "needs_driver": True},
    # ── MODULE 6 ────────────────────────────────────────────────────────────
    {"fn": test_tc6_001_view_donation, "tc_id": "TC6-001", "workflow": "Donor View Donation", "needs_driver": True},
    # ── MODULE 7 ────────────────────────────────────────────────────────────
    {"fn": test_tc7_001_edit_donation_no_location, "tc_id": "TC7-001", "workflow": "Donor Edit Donation", "needs_driver": True},
    {"fn": test_tc7_002_edit_donation_location, "tc_id": "TC7-002", "workflow": "Donor Edit Donation", "needs_driver": True},
    {"fn": test_tc7_003_edit_donation_invalid, "tc_id": "TC7-003", "workflow": "Donor Edit Donation", "needs_driver": True},
    {"fn": test_tc7_004_edit_donation_uneditable_state, "tc_id": "TC7-004", "workflow": "Donor Edit Donation", "needs_driver": True},
    # ── MODULE 8 ────────────────────────────────────────────────────────────
    {"fn": test_tc8_002_abort_cancel_donation, "tc_id": "TC8-002", "workflow": "Donor Cancel Donation", "needs_driver": True},
    {"fn": test_tc8_001_cancel_donation, "tc_id": "TC8-001", "workflow": "Donor Cancel Donation", "needs_driver": True},
    {"fn": test_tc8_003_cancel_donation_invalid_state, "tc_id": "TC8-003", "workflow": "Donor Cancel Donation", "needs_driver": True},
    # ── MODULE 9 ────────────────────────────────────────────────────────────
    {"fn": test_tc9_001_view_dashboard_filters, "tc_id": "TC9-001", "workflow": "Donor View Donation Impact Dashboard", "needs_driver": True},
    {"fn": test_tc9_002_view_dashboard_no_filters, "tc_id": "TC9-002", "workflow": "Donor View Donation Impact Dashboard", "needs_driver": True},
    {"fn": test_tc9_003_view_dashboard_invalid_filters, "tc_id": "TC9-003", "workflow": "Donor View Donation Impact Dashboard", "needs_driver": True},
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

    for entry in TEST_SUITE:
        test_fn      = entry["fn"]
        tc_id        = entry["tc_id"]
        workflow     = entry["workflow"]
        needs_driver = entry["needs_driver"]
        driver       = None

        try:
            if needs_driver:
                logger.info(f"  Launching browser for {tc_id} …")
                driver = create_driver(headless=headless)

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
            if driver:
                driver.quit()
                logger.info(f"  Browser closed after {tc_id}.")

    total_time = (datetime.datetime.now() - suite_start).total_seconds()
    _write_summary(selenium_results, total_time)
    _write_simple_summary(selenium_results, total_time)

    failures = [r for r in selenium_results if r["status"] != "PASS"]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
