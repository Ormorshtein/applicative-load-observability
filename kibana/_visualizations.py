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
    """Layout for main dashboard (23 vis + optional saved search at end).

    Vis indices:
      0=cheat, 1=metric, 2-6=pies,
      7=hdr-offenders, 8=top-templates, 9=top-indicators,
      10=hdr-trends, 11-15=stress-ts,
      16=hdr-volume, 17=vol-template, 18=hits, 19=docs, 20=reqsize,
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


def layout_historical(vis_ids: list[str], panels: list[dict],
                      refs: list[dict]) -> None:
    """Layout for the historical trends dashboard (17 vis).

    vis_ids order matches build_historical_visualizations():
      0=hdr-stress, 1=score-template, 2=score-app, 3=score-target,
      4=hdr-composition, 5=base, 6=mult, 7=ci-count,
      8=hdr-volume, 9=volume-op, 10=volume-app, 11=latency-es, 12=latency-gw,
      13=hdr-top, 14=table-templates, 15=table-apps
    """
    HDR_H = 3
    y = 0

    # Stress Trends
    _add_panel(panels, refs, vis_ids[0], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[1], 0, y, GRID_WIDTH, 12)
    y += 12
    _add_panel(panels, refs, vis_ids[2], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[3], 24, y, 24, 12)
    y += 12

    # Score Composition
    _add_panel(panels, refs, vis_ids[4], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[5], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[6], 24, y, 24, 12)
    y += 12
    _add_panel(panels, refs, vis_ids[7], 0, y, GRID_WIDTH, 12)
    y += 12

    # Volume & Latency
    _add_panel(panels, refs, vis_ids[8], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[9], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[10], 24, y, 24, 12)
    y += 12
    _add_panel(panels, refs, vis_ids[11], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[12], 24, y, 24, 12)
    y += 12

    # Top Offenders
    _add_panel(panels, refs, vis_ids[13], 0, y, GRID_WIDTH, HDR_H,
               panel_type="visualization")
    y += HDR_H
    _add_panel(panels, refs, vis_ids[14], 0, y, GRID_WIDTH, 14)
    y += 14
    _add_panel(panels, refs, vis_ids[15], 0, y, GRID_WIDTH, 14)
