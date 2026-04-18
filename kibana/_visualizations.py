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
    mk_ts,
    mk_ts_multi,
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
    """Layout for main dashboard (23 vis + optional saved search at end).

    Vis indices:
      0=cheat, 1=metric, 2-6=pies,
      7=hdr-offenders, 8=top-templates, 9=top-indicators,
      10=hdr-trends, 11-15=stress-ts,
      16=hdr-volume, 17=vol, 18=hits, 19=docs, 20=reqsize,
      21=hdr-latency, 22=es-latency
    """
    HDR_H = 3
    y = 0

    # Overview: cheat sheet + metric + 5 pies
    _add_panel(panels, refs, vis_ids[0], 0, y, 36, 10, panel_type="visualization")
    _add_panel(panels, refs, vis_ids[1], 36, y, 12, 10)
    y += 10

    pie_w = GRID_WIDTH // 5
    for i in range(5):
        vid = vis_ids[2 + i]
        w = pie_w if i < 4 else GRID_WIDTH - pie_w * 4
        _add_panel(panels, refs, vid, i * pie_w, y, w, 10)
    y += 10

    # Highest Impact
    _add_panel(panels, refs, vis_ids[7], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[8], 0, y, GRID_WIDTH, 14)
    y += 14
    # Heaviest Ops saved search (appended after vis_ids by do_rebuild)
    if len(vis_ids) > 23:
        _add_panel(panels, refs, vis_ids[23], 0, y, GRID_WIDTH, 16,
                   panel_type="search")
        y += 16
    _add_panel(panels, refs, vis_ids[9], 0, y, GRID_WIDTH, 14)
    y += 14

    # Stress Trends
    _add_panel(panels, refs, vis_ids[10], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    for i in range(5):
        _add_panel(panels, refs, vis_ids[11 + i], 0, y, GRID_WIDTH, 12)
        y += 12

    # Volume & Throughput
    _add_panel(panels, refs, vis_ids[16], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[17], 0, y, GRID_WIDTH, 12)
    y += 12
    _add_panel(panels, refs, vis_ids[18], 0, y, GRID_WIDTH, 12)
    y += 12
    _add_panel(panels, refs, vis_ids[19], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[20], 24, y, 24, 12)
    y += 12

    # Response Times
    _add_panel(panels, refs, vis_ids[21], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[22], 0, y, GRID_WIDTH, 12)


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
      0=hdr-rates, 1=total-rate, 2=rate-by-op, 3=rate-by-app,
      4=rate-by-index, 5=rate-by-template,
      6=hdr-latency, 7=latency-by-op,
      8=hdr-errors, 9=error-rate, 10=status-bar, 11=reqs-by-app,
      12=hdr-volume, 13=hits, 14=docs, 15=payload,
      16=hdr-activity, 17=top-apps, 18=top-indices, 19=top-users
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

    _add_panel(panels, refs, vis_ids[4], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[5], 24, y, 24, 12)
    y += 12

    # ── Latency ────────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[6], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[7], 0, y, GRID_WIDTH, 12)
    y += 12

    # ── Errors ─────────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[8], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[9], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[10], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[11], 0, y, GRID_WIDTH, 12)
    y += 12

    # ── Data Volume ────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[12], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[13], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[14], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[15], 0, y, GRID_WIDTH, 12)
    y += 12

    # ── Activity ───────────────────────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[16], 0, y, GRID_WIDTH, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[17], 0, y, 16, 12)
    _add_panel(panels, refs, vis_ids[18], 16, y, 16, 12)
    _add_panel(panels, refs, vis_ids[19], 32, y, 16, 12)


