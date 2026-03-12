#!/usr/bin/env python3
"""
Playwright verification for both ALO Kibana dashboards.

Opens each dashboard in a headless browser, checks that every expected panel
is present, validates cheat-sheet content, and saves screenshots.

Usage:
    python tests/integration/verify_kibana_dashboard_integrity.py
    python tests/integration/verify_kibana_dashboard_integrity.py --kibana http://host:5601
"""

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

MAIN_DASHBOARD_PATH = "/app/dashboards#/view/alo-dashboard"
CI_DASHBOARD_PATH = "/app/dashboards#/view/alo-ci-dashboard"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")

# ── Main dashboard panels (must match _dashboards.py do_rebuild) ──────────

MAIN_PANELS = [
    # Row 1: cheat sheet + total stress
    "Dashboard Guide",
    "Total Stress Score",
    # Row 2: pie charts (4) + overall trend (1) — Cost Indicator pie
    # was replaced by Stress Trend (Overall)
    "Stress by Application (Selected Period)",
    "Stress by Target (Selected Period)",
    "Stress by Operation (Selected Period)",
    "Stress Trend (Overall)",
    "Stress by Template (Selected Period)",
    # Row 3-7: time series
    "Stress Over Time by Application",
    "Stress Over Time by Target",
    "Stress Over Time by Operation",
    "Stress Over Time by Cost Indicator",
    "Stress Over Time by Template",
    # Row 8: top templates table
    "Top 10 Templates by Stress Score",
    # Rows 9-10: ES response time
    "Avg ES Response Time by Cost Indicator",
    "Avg ES Response Time by Operation",
    "Avg ES Response Time by Template",
    # Rows 11-12: gateway response time
    "Avg Gateway Response Time by Cost Indicator",
    "Avg Gateway Response Time by Operation",
    "Avg Gateway Response Time by Template",
    # Row 13: sanity check tables
    "Top 10 Most Recurring Templates",
    "Top 10 Templates with Most Cost Indicators",
]

# ── Cost Indicators dashboard panels ──────────────────────────────────────

CI_PANELS = [
    "Flagged Requests",
    "Avg Indicator Count",
    "Avg Stress Multiplier",
    "Max Stress Multiplier",
    "Cost Indicator Types — Frequency",
    "Flagged vs Total Requests Over Time",
    "Clause Count Trends",
    "Bool Clause Breakdown Over Time",
    "Top Templates by Cost Indicator Count",
    "Stress Multiplier by Application",
    "Cost Indicator Count by Target Index",
]

CHEAT_SHEET_KEYWORDS = [
    "Dashboard Cheat Sheet",
    "pie charts",
    "time series",
    "optimization targets",
]


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------

def _check_panels(page_content: str, expected: list[str],
                  label: str) -> list[str]:
    missing = [p for p in expected if p not in page_content]
    found = len(expected) - len(missing)
    print(f"  [{label}] Panels found: {found}/{len(expected)}")
    if missing:
        print(f"  [{label}] MISSING panels:")
        for title in missing:
            print(f"    - {title}")
    return missing


def _verify_dashboard(page, url: str, panels: list[str], label: str,
                      screenshot_name: str) -> bool:
    print(f"  Opening {label}: {url}")
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(5000)

    path = os.path.join(SCREENSHOT_DIR, screenshot_name)
    page.screenshot(path=path, full_page=True)
    print(f"  Screenshot: {path}")

    content = page.content()
    missing = _check_panels(content, panels, label)
    return len(missing) == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def verify_all(kibana_url: str) -> bool:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    ok = True

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Main dashboard
        main_url = f"{kibana_url}{MAIN_DASHBOARD_PATH}"
        if not _verify_dashboard(page, main_url, MAIN_PANELS,
                                 "Main", "dashboard_main.png"):
            ok = False

        # Cheat sheet content check (main dashboard is still loaded)
        content = page.content()
        missing_kw = [kw for kw in CHEAT_SHEET_KEYWORDS if kw not in content]
        if missing_kw:
            print(f"  [Main] MISSING cheat sheet content: {missing_kw}")
            ok = False
        else:
            print("  [Main] Cheat sheet content: OK")

        # Top-section screenshot
        top_path = os.path.join(SCREENSHOT_DIR, "dashboard_main_top.png")
        page.screenshot(
            path=top_path,
            clip={"x": 0, "y": 0, "width": 1920, "height": 600},
        )
        print(f"  Top section screenshot: {top_path}")

        # Cost Indicators dashboard
        print()
        ci_url = f"{kibana_url}{CI_DASHBOARD_PATH}"
        if not _verify_dashboard(page, ci_url, CI_PANELS,
                                 "Cost Indicators", "dashboard_ci.png"):
            ok = False

        browser.close()

    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify ALO Kibana dashboards with Playwright")
    parser.add_argument(
        "--kibana",
        default=os.getenv("KIBANA_URL", "http://127.0.0.1:5601"),
        help="Kibana URL (default: %(default)s)",
    )
    args = parser.parse_args()

    print(f"\n  Verifying dashboards at {args.kibana}\n")
    is_ok = verify_all(args.kibana)

    if is_ok:
        print("\n  All checks PASSED")
    else:
        print("\n  Some checks FAILED")
    sys.exit(0 if is_ok else 1)


if __name__ == "__main__":
    main()
