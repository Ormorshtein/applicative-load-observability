"""Dashboard constants and layout functions.

Panel builders live in _viz_builders.py. This module contains:
- Dashboard-level constants (SECTIONS, PANEL_DESCRIPTIONS, CHEAT_SHEET)
- Layout functions that arrange panels on each dashboard's grid
"""

from pathlib import Path

# Re-export builders so existing imports from _visualizations still work.
from _viz_builders import (  # noqa: F401
    mk_ci_metric,
    mk_datatable,
    mk_horizontal_bar,
    mk_markdown,
    mk_metric,
    mk_pie,
    mk_pie_filters,
    mk_ts,
    mk_ts_multi,
    mk_ts_response,
)

# Ordered per dashboard layout: Application -> Target -> Operation -> Cost Indicator -> Template
SECTIONS = [
    ("identity.applicative_provider", "Application"),
    ("request.target",                "Target"),
    ("request.operation",             "Operation"),
    ("stress.cost_indicator_names",   "Cost Indicator"),
    ("request.template",              "Template"),
]

# Panel descriptions for hover notes
PANEL_DESCRIPTIONS = {
    "pie": {
        "Application": "Shows stress distribution across applicative providers. "
                       "Hover slices to see request count and avg requests/sec.",
        "Target": "Shows stress distribution across target indices/databases. "
                  "Hover slices to see request count and avg requests/sec.",
        "Operation": "Shows stress distribution across operation types (search, index, bulk, etc.). "
                     "Hover slices to see request count and avg requests/sec.",
        "Template": "Shows stress distribution across request templates. "
                    "Hover slices to see request count and avg requests/sec.",
    },
    "ts": {
        "Application": "Average stress score over time, broken down by applicative provider.",
        "Target": "Average stress score over time, broken down by target index/database.",
        "Operation": "Average stress score over time, broken down by operation type.",
        "Cost Indicator": "Average stress score over time, broken down by cost indicator.",
        "Template": "Average stress score over time, broken down by request template.",
    },
    "resp_es": {
        "Cost Indicator": "Average Elasticsearch response time over time by cost indicator, with request count.",
        "Operation": "Average Elasticsearch response time over time by operation type, with request count.",
        "Template": "Average Elasticsearch response time over time by request template, with request count.",
    },
    "resp_gw": {
        "Cost Indicator": "Average gateway response time over time by cost indicator, with request count.",
        "Operation": "Average gateway response time over time by operation type, with request count.",
        "Template": "Average gateway response time over time by request template, with request count.",
    },
}

_CHEAT_SHEET_PATH = Path(__file__).resolve().parent / "cheat_sheet.md"
CHEAT_SHEET_MARKDOWN = _CHEAT_SHEET_PATH.read_text(encoding="utf-8")


GRID_WIDTH = 48

# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _add_panel(panels: list[dict], refs: list[dict], vid: str,
               x: int, y: int, w: int, h: int,
               panel_type: str = "lens") -> None:
    panels.append({"panelIndex": vid,
                   "gridData": {"x": x, "y": y, "w": w, "h": h, "i": vid},
                   "type": panel_type, "panelRefName": f"panel_{vid}"})
    refs.append({"type": panel_type, "id": vid, "name": f"panel_{vid}"})


# ---------------------------------------------------------------------------
# Main dashboard layout
# ---------------------------------------------------------------------------

def layout_main(vis_ids: list[str], panels: list[dict],
                refs: list[dict]) -> None:
    """
    Layout (reorganized for investigation flow):

    Section 1 — Overview:
      Cheat sheet + Total Stress Score, 5 pie charts
    Section 2 — Highest Impact:
      Header, Top Templates table, Heaviest Ops, Top Cost Indicators table
    Section 3 — Stress Trends:
      Header, 5x Stress Over Time
    Section 4 — Volume & Throughput:
      Header, Volume by Op + Template, Total Hits, Docs Affected + Request Size
    Section 5 — Response Times:
      Header, 3x ES resp, 3x Gateway resp
    Section 6 — Sanity Checks:
      Header, Recurring Templates + Most Cost Indicators

    Vis indices:
      0=cheat, 1=metric, 2-6=pies,
      7=hdr-offenders, 8=top-templates, 9=top-indicators,
      10=hdr-trends, 11-15=stress-ts,
      16=hdr-volume, 17=vol-op, 18=vol-template, 19=hits, 20=docs, 21=reqsize,
      22=hdr-latency, 23-25=es-resp, 26-28=gw-resp,
      29=hdr-sanity, 30=recurring, 31=cost-ind-table,
      saved-search=32
    """
    HDR_H = 3
    y = 0

    # ── Section 1: Overview ────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[0], 0, y, 36, 10, panel_type="visualization")
    _add_panel(panels, refs, vis_ids[1], 36, y, 12, 10)
    y += 10

    pie_w = GRID_WIDTH // 5
    for i in range(5):
        vid = vis_ids[2 + i]
        w = pie_w if i < 4 else GRID_WIDTH - pie_w * 4
        _add_panel(panels, refs, vid, i * pie_w, y, w, 10)
    y += 10

    # ── Section 2: Highest Impact ──────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[7], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[8], 0, y, GRID_WIDTH, 14)
    y += 14

    _add_panel(panels, refs, vis_ids[32], 0, y, GRID_WIDTH, 16, panel_type="search")
    y += 16

    _add_panel(panels, refs, vis_ids[9], 0, y, GRID_WIDTH, 14)
    y += 14

    # ── Section 3: Stress Trends ───────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[10], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    for i in range(5):
        _add_panel(panels, refs, vis_ids[11 + i], 0, y, GRID_WIDTH, 12)
        y += 12

    # ── Section 4: Volume & Throughput ─────────────────────────────────────
    _add_panel(panels, refs, vis_ids[16], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[17], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[18], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[19], 0, y, GRID_WIDTH, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[20], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[21], 24, y, 24, 12)
    y += 12

    # ── Section 5: Response Times ──────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[22], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    for row_start in (23, 26):
        for j in range(3):
            _add_panel(panels, refs, vis_ids[row_start + j], j * 16, y, 16, 12)
        y += 12

    # ── Section 6: Sanity Checks ───────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[29], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    for j in range(2):
        _add_panel(panels, refs, vis_ids[30 + j], j * 24, y, 24, 12)


# ---------------------------------------------------------------------------
# Cost Indicators dashboard layout
# ---------------------------------------------------------------------------

def layout_cost_indicators(vis_ids: list[str], panels: list[dict],
                           refs: list[dict]) -> None:
    HDR_H = 3
    y = 0

    # KPIs (4 metrics)
    for j in range(4):
        _add_panel(panels, refs, vis_ids[j], j * 12, y, 12, 6)
    y += 6

    # Score Breakdown header + table
    _add_panel(panels, refs, vis_ids[4], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[5], 0, y, GRID_WIDTH, 14)
    y += 14

    # Trends header + components + flagged
    _add_panel(panels, refs, vis_ids[6], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[7], 0, y, GRID_WIDTH, 14)
    y += 14
    _add_panel(panels, refs, vis_ids[8], 0, y, GRID_WIDTH, 14)
    y += 14

    # Cost Indicator Deep Dive header + bar + table + bars
    _add_panel(panels, refs, vis_ids[9], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[10], 0, y, GRID_WIDTH, 14)
    y += 14
    _add_panel(panels, refs, vis_ids[11], 0, y, GRID_WIDTH, 12)
    y += 12
    _add_panel(panels, refs, vis_ids[12], 0, y, 24, 14)
    _add_panel(panels, refs, vis_ids[13], 24, y, 24, 14)
    y += 14

    # Clause Patterns header + trends + bool
    _add_panel(panels, refs, vis_ids[14], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[15], 0, y, 28, 14)
    _add_panel(panels, refs, vis_ids[16], 28, y, 20, 14)


# ---------------------------------------------------------------------------
# Cluster Usage dashboard layout
# ---------------------------------------------------------------------------

def layout_usage(vis_ids: list[str], panels: list[dict],
                 refs: list[dict]) -> None:
    """
    Vis indices:
      0=hdr-rates, 1=total-rate, 2=rate-by-op, 3=rate-by-app, 4=rate-by-index,
      5=hdr-latency, 6=es-latency, 7=gw-latency, 8=latency-by-op,
      9=hdr-errors, 10=error-rate, 11=status-bar, 12=errors-by-app,
      13=hdr-volume, 14=hits, 15=docs, 16=payload,
      17=hdr-activity, 18=top-apps, 19=top-indices, 20=top-users
    """
    HDR_H = 3
    y = 0

    # ── Rates ──────────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[0], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[1], 0, y, GRID_WIDTH, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[2], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[3], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[4], 0, y, GRID_WIDTH, 12)
    y += 12

    # ── Latency ────────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[5], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[6], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[7], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[8], 0, y, GRID_WIDTH, 12)
    y += 12

    # ── Errors ─────────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[9], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[10], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[11], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[12], 0, y, GRID_WIDTH, 12)
    y += 12

    # ── Data Volume ────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[13], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[14], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[15], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[16], 0, y, GRID_WIDTH, 12)
    y += 12

    # ── Activity ───────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[17], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[18], 0, y, 16, 12)
    _add_panel(panels, refs, vis_ids[19], 16, y, 16, 12)
    _add_panel(panels, refs, vis_ids[20], 32, y, 16, 12)
