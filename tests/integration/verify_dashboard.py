#!/usr/bin/env python3
"""
Playwright verification script for the Applicative Load Observability dashboard.

Takes screenshots and validates that all expected panels are present,
including the cheat sheet, total stress score, pie charts with tooltips,
and panel descriptions.

Usage:
    python tests/integration/verify_dashboard.py
    python tests/integration/verify_dashboard.py --kibana http://host:5601
"""

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

DASHBOARD_URL_PATH = "/app/dashboards#/view/alo-dashboard"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")

EXPECTED_PANELS = [
    "Dashboard Guide",
    "Total Stress Score",
    "Stress by Application (Selected Period)",
    "Stress by Target (Selected Period)",
    "Stress by Operation (Selected Period)",
    "Stress by Cost Indicator (Selected Period)",
    "Stress by Template (Selected Period)",
    "Stress Over Time by Application",
    "Stress Over Time by Target",
    "Stress Over Time by Operation",
    "Stress Over Time by Cost Indicator",
    "Stress Over Time by Template",
    "Top 10 Templates by Stress Score",
    "Avg ES Response Time by Cost Indicator",
    "Avg ES Response Time by Operation",
    "Avg ES Response Time by Template",
    "Avg Gateway Response Time by Cost Indicator",
    "Avg Gateway Response Time by Operation",
    "Avg Gateway Response Time by Template",
    "Top 10 Most Recurring Templates",
    "Top 10 Templates with Most Cost Indicators",
]


def verify_dashboard(kibana_url: str) -> bool:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    dashboard_url = f"{kibana_url}{DASHBOARD_URL_PATH}"
    is_success = True

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        print(f"  Opening dashboard: {dashboard_url}")
        page.goto(dashboard_url, wait_until="networkidle", timeout=60000)

        # Wait for dashboard panels to render
        page.wait_for_timeout(5000)

        # Take full-page screenshot
        full_path = os.path.join(SCREENSHOT_DIR, "dashboard_full.png")
        page.screenshot(path=full_path, full_page=True)
        print(f"  Full dashboard screenshot: {full_path}")

        # Check for expected panel titles
        page_content = page.content()
        missing_panels = []
        found_panels = []
        for panel_title in EXPECTED_PANELS:
            if panel_title in page_content:
                found_panels.append(panel_title)
            else:
                missing_panels.append(panel_title)

        print(f"\n  Panels found: {len(found_panels)}/{len(EXPECTED_PANELS)}")

        if missing_panels:
            print("  MISSING panels:")
            for title in missing_panels:
                print(f"    - {title}")
            is_success = False

        # Verify cheat sheet content
        cheat_sheet_keywords = [
            "Dashboard Cheat Sheet",
            "pie charts",
            "time series",
            "optimization targets",
        ]
        missing_keywords = [
            kw for kw in cheat_sheet_keywords if kw not in page_content
        ]
        if missing_keywords:
            print(f"\n  MISSING cheat sheet content: {missing_keywords}")
            is_success = False
        else:
            print("  Cheat sheet content: OK")

        # Take screenshot of just the top section (cheat sheet + stress score)
        top_path = os.path.join(SCREENSHOT_DIR, "dashboard_top.png")
        page.screenshot(
            path=top_path,
            clip={"x": 0, "y": 0, "width": 1920, "height": 600},
        )
        print(f"  Top section screenshot: {top_path}")

        browser.close()

    return is_success


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify ALO dashboard with Playwright",
    )
    parser.add_argument(
        "--kibana",
        default=os.getenv("KIBANA_URL", "http://127.0.0.1:5601"),
        help="Kibana URL (default: %(default)s)",
    )
    args = parser.parse_args()

    print(f"\n  Verifying dashboard at {args.kibana}\n")
    is_ok = verify_dashboard(args.kibana)

    if is_ok:
        print("\n  All checks PASSED")
    else:
        print("\n  Some checks FAILED")
    sys.exit(0 if is_ok else 1)


if __name__ == "__main__":
    main()
