#!/usr/bin/env python3
"""
Playwright verification for ALO Grafana dashboards.

Run with the global Python interpreter (has playwright installed):
    C:\\Programs\\Python\\Python311\\python.exe tests/integration/verify_grafana_dashboards.py \\
        --version v2.0.2

Logs into Grafana, visits each in-scope dashboard, scrolls the full page to
trigger lazy-loaded panels, takes screenshots, checks that every expected
panel title is present in the rendered HTML, counts "No data" and error
indicators, and writes a machine-readable JSON report.

Excluded panels (e.g. Prometheus-backed ones) are noted in the report but
do not affect the pass/fail result.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = os.getenv("GRAFANA_URL", "http://127.0.0.1:3000")
_DEFAULT_USER = os.getenv("GRAFANA_USER", "admin")
_DEFAULT_PASSWORD = os.getenv("GRAFANA_PASSWORD", "admin")
_DEFAULT_TIME_FROM = "now-1h"
_DEFAULT_WAIT_EXTRA_S = 8

SCREENSHOT_BASE = Path(__file__).parent / "screenshots" / "grafana"

# (dashboard_uid, panel_title) -> Grafana panel ID (int) or None.
# These panels are excluded from pass/fail.  The panel ID lets the error
# collector skip error indicators that belong to these panels (e.g. ES CPU
# Usage errors because Prometheus is not running — expected, out of scope).
EXCLUDED_PANELS: dict[tuple[str, str], int | None] = {
    ("alo-main", "ES CPU Usage"): 1,
}

_EXCLUDED_PANEL_IDS: frozenset[int] = frozenset(
    v for v in EXCLUDED_PANELS.values() if v is not None
)

# ---------------------------------------------------------------------------
# Panel inventories (v2.0.x, derived from grafana/_dashboard_builders.py)
# ---------------------------------------------------------------------------

_MAIN_EXPECTED: list[str] = [
    "Total Stress Score",
    "Dashboard Guide",
    "Stress by Application (Selected Period)",
    "Stress by Target (Selected Period)",
    "Stress by Operation (Selected Period)",
    "Stress by Cost Indicator (Selected Period)",
    "Stress by Template (Selected Period)",
    "Top 10 Templates by Stress Score",
    "Top 10 Heaviest Operations",
    "Top 10 Cost Indicators by Stress Score",
    "Stress by Application",
    "Stress by Target",
    "Stress by Operation",
    "Stress by Cost Indicator",
    "Stress by Template",
    "Request Volume",
    "Documents Matched by Queries",
    "Avg Documents Matched per Query",
    "Bulk Write Volume",
    "Avg Documents per Bulk",
    "Request Size",
    "Avg Request Size",
    "ES Latency",
    "Status Code by Operation",
]

_COST_EXPECTED: list[str] = [
    "Flagged Requests",
    "Avg Indicator Count",
    "Avg Stress Multiplier",
    "Max Stress Multiplier",
    "Score Composition by Template",
    "Base vs Final Score by Template",
    "Top Templates by Cost Indicator Count",
    "Score Breakdown by Template",
    "Score Components",
    "Avg Base Score by Template",
    "Avg Multiplier by Template",
    "Avg Cost Indicators by Application",
    "Flagged vs Total Requests",
    "Cost Indicator Types - Frequency",
    "Stress Multiplier by Application",
    "Cost Indicator Count by Target Index",
    "Stress Multiplier by Target Index",
    "Clause Count Trends",
    "Bool Clause Breakdown",
]

_USAGE_EXPECTED: list[str] = [
    "Total Request Rate",
    "Rate by Operation",
    "Rate by Application",
    "Rate by Target Index",
    "Rate by Template",
    "ES Latency",
    "Error Rate",
    "Requests by Status Code",
    "Requests by Application",
    "Read Volume (Total Hits)",
    "Bulk Write Volume",
    "Payload Sizes",
    "Top 10 Applications",
    "Top 10 Indices",
    "Top 10 Users",
]

DASHBOARDS: dict[str, list[str]] = {
    "alo-main":            _MAIN_EXPECTED,
    "alo-cost-indicators": _COST_EXPECTED,
    "alo-usage":           _USAGE_EXPECTED,
}

# Grafana 11 renders panel errors as labelled buttons/icons in the panel header.
# These selectors target the error-state indicator — NOT the plugin metadata.
_GRAFANA_ERROR_SELECTORS: list[str] = [
    '[data-testid="data-testid Panel status error"]',
    'button[aria-label="Error"]',
    '[class*="errorContainer"]',
]

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PanelResult:
    dashboard: str
    title: str
    present: bool
    excluded: bool


@dataclass
class DashboardResult:
    uid: str
    full_screenshot: str
    top_screenshot: str
    panel_results: list[PanelResult] = field(default_factory=list)
    no_data_count: int = 0
    error_snippets: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        relevant = [p for p in self.panel_results if not p.excluded]
        all_present = all(p.present for p in relevant)
        return all_present and self.no_data_count == 0 and not self.error_snippets

    @property
    def missing_panels(self) -> list[str]:
        return [p.title for p in self.panel_results if not p.present and not p.excluded]


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _login(page: Page, base_url: str, username: str, password: str) -> None:
    page.goto(f"{base_url}/login", wait_until="networkidle", timeout=30_000)
    page.fill('input[name="user"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle", timeout=15_000)
    print("  Logged in to Grafana.")


_FIND_SCROLL_CONTAINER_JS = """
() => {
    // Multiple elements carry the 'scrollbar-view' class (e.g. the cheat-sheet
    // text panel has its own).  The dashboard scroll container is always the one
    // with the largest scrollHeight.
    const elements = document.querySelectorAll('.scrollbar-view');
    let best = null;
    for (const el of elements) {
        if (!best || el.scrollHeight > best.scrollHeight) best = el;
    }
    return best ? {scrollHeight: best.scrollHeight, clientHeight: best.clientHeight} : null;
}
"""

_SCROLL_TO_JS = """
(y) => {
    const elements = document.querySelectorAll('.scrollbar-view');
    let best = null;
    for (const el of elements) {
        if (!best || el.scrollHeight > best.scrollHeight) best = el;
    }
    if (best) best.scrollTop = y;
}
"""


def _get_scroll_info(page: Page) -> dict:
    """Return scrollHeight and clientHeight for Grafana's main dashboard scroll container."""
    result = page.evaluate(_FIND_SCROLL_CONTAINER_JS)
    return result or {"scrollHeight": 0, "clientHeight": 1080}


def _scroll_container_to(page: Page, y: int) -> None:
    page.evaluate(_SCROLL_TO_JS, y)


def _collect_panel_titles_and_issues(
    page: Page,
    wait_per_step_s: float = 2.5,
    excluded_panel_ids: frozenset[int] = _EXCLUDED_PANEL_IDS,
) -> tuple[set[str], int, list[str]]:
    """Scroll Grafana's internal container, accumulating panel titles and issues.

    Grafana 11 uses a '.scrollbar-view' scroll container and an IntersectionObserver
    that lazy-loads panel content (including the h6 title) only when the panel
    enters the viewport. React also unmounts panels that scroll out of view, so
    a single page.content() call after one scroll misses most panels.

    This function scrolls in viewport-height steps, collecting h6 titles and
    "No data" / error counts at each position, then returns the union.

    Returns: (all_titles, total_no_data_count, error_labels)
    """
    info = _get_scroll_info(page)
    scroll_height = info["scrollHeight"]
    client_height = info["clientHeight"] or 1000
    step = max(client_height - 100, 800)  # slight overlap between steps

    all_titles: set[str] = set()
    total_no_data = 0
    all_errors: list[str] = []

    y = 0
    while True:
        _scroll_container_to(page, y)
        page.wait_for_timeout(int(wait_per_step_s * 1_000))

        # Panel titles
        titles = page.locator("h6").all_inner_texts()
        all_titles.update(t.strip() for t in titles if t.strip())

        # "No data" indicators
        total_no_data += page.get_by_text("No data", exact=True).count()

        # Error state panels (check once per scroll cycle, deduplicate).
        # Walk up to the nearest [data-panelid] ancestor and skip excluded IDs.
        if not all_errors:
            for selector in _GRAFANA_ERROR_SELECTORS:
                elements = page.locator(selector).all()
                if not elements:
                    continue
                for el in elements:
                    panel_id = el.evaluate("""
                        el => {
                            const ancestor = el.closest('[data-panelid]');
                            return ancestor ? ancestor.getAttribute('data-panelid') : null;
                        }
                    """)
                    if panel_id and int(panel_id) in excluded_panel_ids:
                        continue
                    label = el.get_attribute("aria-label") or el.inner_text() or selector
                    label = label.strip()
                    if label and label not in all_errors:
                        all_errors.append(label)
                break

        if y >= scroll_height:
            break
        y = min(y + step, scroll_height)

    # Reset to top for screenshots
    _scroll_container_to(page, 0)
    page.wait_for_timeout(1_000)

    return all_titles, total_no_data, all_errors


# ---------------------------------------------------------------------------
# Per-dashboard verification
# ---------------------------------------------------------------------------

def _verify_dashboard(
    page: Page,
    uid: str,
    expected_panels: list[str],
    screenshot_dir: Path,
    base_url: str,
    time_from: str,
    wait_extra_s: int,
) -> DashboardResult:
    url = f"{base_url}/d/{uid}?from={time_from}&to=now&refresh=&orgId=1"
    print(f"\n  [{uid}] Loading: {url}")

    page.goto(url, wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(wait_extra_s * 1_000)

    # Scroll through the full dashboard, collecting panel titles at each
    # viewport position (Grafana 11 lazy-loads and unmounts panels off-screen).
    wait_per_step = max(2.0, wait_extra_s / 4)
    panel_titles, no_data_count, error_snippets = _collect_panel_titles_and_issues(
        page, wait_per_step_s=wait_per_step,
    )

    # Take screenshots with the container scrolled back to top.
    top_path  = screenshot_dir / f"{uid}_top.png"
    page.screenshot(path=str(top_path),
                    clip={"x": 0, "y": 0, "width": 1920, "height": 1080})

    # Scroll to roughly halfway for a mid-dashboard screenshot.
    info = _get_scroll_info(page)
    mid_y = info["scrollHeight"] // 2
    _scroll_container_to(page, mid_y)
    page.wait_for_timeout(1_500)
    mid_path = screenshot_dir / f"{uid}_mid.png"
    page.screenshot(path=str(mid_path),
                    clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
    _scroll_container_to(page, info["scrollHeight"])
    page.wait_for_timeout(1_500)
    bot_path = screenshot_dir / f"{uid}_bottom.png"
    page.screenshot(path=str(bot_path),
                    clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
    _scroll_container_to(page, 0)

    full_path = top_path  # alias: report references "full_screenshot" as the top
    print(f"  [{uid}] Screenshots saved (top / mid / bottom).")

    panel_results: list[PanelResult] = []
    for title in expected_panels:
        is_excluded = (uid, title) in EXCLUDED_PANELS  # dict key membership check
        is_present = title in panel_titles
        panel_results.append(PanelResult(
            dashboard=uid,
            title=title,
            present=is_present,
            excluded=is_excluded,
        ))

    return DashboardResult(
        uid=uid,
        full_screenshot=str(full_path),
        top_screenshot=str(top_path),
        panel_results=panel_results,
        no_data_count=no_data_count,
        error_snippets=error_snippets,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _run_verification(
    base_url: str,
    username: str,
    password: str,
    version: str,
    dashboard_uids: list[str],
    time_from: str,
    wait_extra_s: int,
) -> list[DashboardResult]:
    screenshot_dir = SCREENSHOT_BASE / version
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    results: list[DashboardResult] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        _login(page, base_url, username, password)

        for uid in dashboard_uids:
            expected = DASHBOARDS.get(uid, [])
            result = _verify_dashboard(
                page, uid, expected, screenshot_dir,
                base_url, time_from, wait_extra_s,
            )
            results.append(result)
            _print_dashboard_summary(result)

        browser.close()

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_dashboard_summary(result: DashboardResult) -> None:
    relevant = [p for p in result.panel_results if not p.excluded]
    present_count = sum(1 for p in relevant if p.present)
    total_count = len(relevant)
    status = "PASS" if result.passed else "FAIL"
    print(f"  [{result.uid}] {status} — panels {present_count}/{total_count}, "
          f"no-data: {result.no_data_count}, errors: {len(result.error_snippets)}")
    if result.missing_panels:
        for title in result.missing_panels:
            print(f"    MISSING: {title}")
    if result.error_snippets:
        for snippet in result.error_snippets:
            print(f"    ERROR: {snippet}")
    if result.no_data_count > 0:
        print(f"    WARNING: {result.no_data_count} 'No data' text(s) found on page")


def _write_report(results: list[DashboardResult], version: str) -> Path:
    report_path = SCREENSHOT_BASE / version / "report.json"

    serialisable = []
    for r in results:
        d = asdict(r)
        d["passed"] = r.passed
        d["missing_panels"] = r.missing_panels
        serialisable.append(d)

    report_path.write_text(json.dumps(serialisable, indent=2), encoding="utf-8")
    print(f"\n  Report written: {report_path}")
    return report_path


def _overall_passed(results: list[DashboardResult]) -> bool:
    return all(r.passed for r in results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify ALO Grafana dashboards with Playwright")
    parser.add_argument(
        "--version", default="dev",
        help="Label for this run — controls the screenshot subdirectory (e.g. v2.0.2)")
    parser.add_argument(
        "--base-url", default=_DEFAULT_BASE_URL,
        help=f"Grafana base URL (default: {_DEFAULT_BASE_URL})")
    parser.add_argument(
        "--user", default=_DEFAULT_USER,
        help="Grafana admin username (default: %(default)s)")
    parser.add_argument(
        "--password", default=_DEFAULT_PASSWORD,
        help="Grafana admin password (default: %(default)s)")
    parser.add_argument(
        "--dashboards",
        default=",".join(DASHBOARDS.keys()),
        help="Comma-separated dashboard UIDs to verify (default: all three)")
    parser.add_argument(
        "--time-from", default=_DEFAULT_TIME_FROM,
        help=f"Grafana time-range start (default: {_DEFAULT_TIME_FROM})")
    parser.add_argument(
        "--wait-extra", type=int, default=_DEFAULT_WAIT_EXTRA_S,
        help=f"Extra seconds to wait after networkidle (default: {_DEFAULT_WAIT_EXTRA_S})")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    dashboard_uids = [u.strip() for u in args.dashboards.split(",") if u.strip()]

    print(f"\n  ALO Grafana Verifier — {args.version}")
    print(f"  Target: {args.base_url}")
    print(f"  Dashboards: {', '.join(dashboard_uids)}")
    print(f"  Time range: {args.time_from} to now\n")

    results = _run_verification(
        base_url=args.base_url,
        username=args.user,
        password=args.password,
        version=args.version,
        dashboard_uids=dashboard_uids,
        time_from=args.time_from,
        wait_extra_s=args.wait_extra,
    )

    _write_report(results, args.version)

    passed = _overall_passed(results)
    print(f"\n  Overall: {'ALL CHECKS PASSED' if passed else 'SOME CHECKS FAILED'}\n")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
