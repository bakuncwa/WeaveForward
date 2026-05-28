"""
Application Under Test : WeaveForward
Automation Framework   : Selenium WebDriver (Python)
File                   : main.py — entry-point; runs all TUAB test cases.

Usage
─────
    python main.py                   # headed browser
    python main.py --headless        # headless browser

Prerequisites
─────────────
    pip install selenium webdriver-manager requests pyotp
    Chrome + ChromeDriver (auto-managed by webdriver-manager)
"""

import datetime
import io
import sys
import unittest

import test_scripts
from test_scripts import (
    LOG_FILE,
    TC11TUABRegisterAccountTest,
    TC12TUABLoginTest,
    TC13TUABViewIncomingDonationsTest,
    TC14TUABSubscribeForPremiumTest,
    TC15TUABViewMatchRecommendationsTest,
    TC16TUABUpdateIncomingDonationsTest,
    TC17TUABFlagIncomingDonationsTest,
    TC18TUABViewInventoryItemsTest,
    TC19TUABUpdateInventoryItemsTest,
    TC20TUABArchiveInventoryItemsTest,
    TC21TUABUpdateAccountInformationTest,
    logger,
)

# ──────────────────────────────────────────────────────────────────────────────
# Workflow labels (preserve definition order within each class)
# ──────────────────────────────────────────────────────────────────────────────
WORKFLOW_MAP = {
    TC11TUABRegisterAccountTest:        "TUAB Register Account",
    TC12TUABLoginTest:                  "TUAB Login",
    TC13TUABViewIncomingDonationsTest:  "TUAB View Incoming Donations",
    TC14TUABSubscribeForPremiumTest:    "TUAB Subscribe For Premium Features",
    TC15TUABViewMatchRecommendationsTest: "TUAB View Match Donations Recommendations",
    TC16TUABUpdateIncomingDonationsTest: "TUAB Update Incoming Donations",
    TC17TUABFlagIncomingDonationsTest:  "TUAB Flag Incoming Donations",
    TC18TUABViewInventoryItemsTest:     "TUAB View Inventory Items",
    TC19TUABUpdateInventoryItemsTest:   "TUAB Update Inventory Items",
    TC20TUABArchiveInventoryItemsTest:  "TUAB Archive Inventory Items",
    TC21TUABUpdateAccountInformationTest: "TUAB Update Account Information",
}


# ──────────────────────────────────────────────────────────────────────────────
# Custom result collector
# ──────────────────────────────────────────────────────────────────────────────
class _DetailedResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.test_records: list[dict] = []

    def _record(self, test, status, message=""):
        tc_id = test._testMethodName.split("_")[1].replace("tc", "TC").upper()
        # Reconstruct the proper TC ID, e.g. test_tc11_001_... → TC11-001
        parts = test._testMethodName.split("_")
        # Find the module number (e.g. 'tc11') and case number (e.g. '001')
        try:
            idx = next(i for i, p in enumerate(parts) if p.startswith("tc"))
            module_num = parts[idx][2:]  # '11'
            case_num   = parts[idx + 1]  # '001'
            tc_id = f"TC{module_num}-{case_num}"
        except (StopIteration, IndexError):
            tc_id = test._testMethodName

        doc = (getattr(test.__class__, test._testMethodName).__doc__ or "").strip()
        workflow = WORKFLOW_MAP.get(type(test), type(test).__name__)
        self.test_records.append({
            "test_id":    tc_id,
            "description": doc,
            "workflow":   workflow,
            "status":     status,
            "message":    message,
        })
        logger.info("[END]   %s – %s", tc_id, status)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "ERROR", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "SKIP", reason)


# ──────────────────────────────────────────────────────────────────────────────
# Summary writers
# ──────────────────────────────────────────────────────────────────────────────
def _write_summary(records: list, total_seconds: float) -> None:
    passed  = [r for r in records if r["status"] == "PASS"]
    failed  = [r for r in records if r["status"] == "FAIL"]
    errored = [r for r in records if r["status"] == "ERROR"]
    skipped = [r for r in records if r["status"] == "SKIP"]
    total   = len(records)
    pass_rt = (len(passed) / total * 100) if total else 0.0

    sep  = "=" * 72
    dash = "─" * 72

    workflow_map: dict[str, list] = {}
    for r in records:
        workflow_map.setdefault(r["workflow"], []).append(r)

    lines = [
        "",
        sep,
        "  WEAVEFORWARD AUTOMATION SUITE | COMPLETE TEST EXECUTION SUMMARY",
        sep,
        f"  Timestamp              : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"  AUT                    : WeaveForward",
        f"  Automation Framework   : Selenium WebDriver (Python)",
        dash,
        f"  Selenium Tests Run     : {total}",
        f"  PASSED                 : {len(passed)}",
        f"  FAILED                 : {len(failed)}",
        f"  ERRORS                 : {len(errored)}",
        f"  SKIPPED                : {len(skipped)}",
        f"  Pass Rate              : {pass_rt:.1f}%",
        f"  Total Execution Time   : {total_seconds:.2f} s",
        dash, "  DETAILED RESULTS BY WORKFLOW", dash,
    ]

    for wf, results in workflow_map.items():
        wf_pass = sum(1 for r in results if r["status"] == "PASS")
        lines.append(f"  ▸ {wf}  ({wf_pass}/{len(results)} passed)")
        for r in results:
            icon = "✓" if r["status"] == "PASS" else ("✗" if r["status"] == "FAIL" else ("!" if r["status"] == "ERROR" else "~"))
            lines.append(f"    [{icon}] {r['test_id']:8s} | {r['status']:5s} | {r['description']}")
            if r["status"] not in ("PASS", "SKIP") and r["message"]:
                for i, seg in enumerate(r["message"].split("\n")[:5]):
                    prefix = "           └─ " if i == 0 else "              "
                    lines.append(f"{prefix}{seg}")

    not_passed = len(failed) + len(errored)
    verdict = "ALL SELENIUM TESTS PASSED" if not_passed == 0 else f"{len(failed)} FAILED  |  {len(errored)} ERROR(S)"
    lines += [dash, f"  VERDICT  :  {verdict}", sep, ""]

    block = "\n".join(lines)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(block)
    try:
        print(block)
    except UnicodeEncodeError:
        print(block.encode("ascii", "replace").decode("ascii"))


def _write_simple_summary(records: list, total_seconds: float) -> None:
    """Write a plain pass/fail summary to summary.txt (overwritten each run)."""
    passed = [r for r in records if r["status"] == "PASS"]
    failed = [r for r in records if r["status"] != "PASS"]
    total  = len(records)
    rate   = (len(passed) / total * 100) if total else 0.0

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
    for r in records:
        icon = "PASS" if r["status"] == "PASS" else ("SKIP" if r["status"] == "SKIP" else "FAIL")
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
    msg = f"\n[summary.txt written -> {summary_path}]"
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    headless = "--headless" in sys.argv
    test_scripts.HEADLESS = headless

    logger.info("=" * 72)
    logger.info("  WEAVEFORWARD | TUAB Automated Test Run Starting")
    logger.info(f"  Date/Time   : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    logger.info(f"  AUT         : WeaveForward")
    logger.info(f"  Browser     : Google Chrome ({'headless' if headless else 'headed'})")
    logger.info("=" * 72)

    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # preserve definition order

    suite = unittest.TestSuite()
    for cls in WORKFLOW_MAP:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    result_collector = _DetailedResult()
    suite_start = datetime.datetime.now()
    suite.run(result_collector)
    total_time = (datetime.datetime.now() - suite_start).total_seconds()

    _write_summary(result_collector.test_records, total_time)
    _write_simple_summary(result_collector.test_records, total_time)

    not_passed = [r for r in result_collector.test_records if r["status"] not in ("PASS", "SKIP")]
    sys.exit(1 if not_passed else 0)


if __name__ == "__main__":
    main()
