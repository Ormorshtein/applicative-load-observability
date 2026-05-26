"""Dashboard assembly for Grafana provisioning.

Each builder creates a complete dashboard dict ready for JSON export.
Panel helpers (mk_*) are imported from _dashboards.
"""

from ._dashboards import (
    CHEAT_SHEET,
    PANEL_DESCRIPTIONS,
    SECTIONS,
    _reset_ids,
    _wrap_dashboard,
    mk_bar,
    mk_cpu_panel,
    mk_pie,
    mk_raw_docs_table,
    mk_stacked_bar,
    mk_stat,
    mk_table,
    mk_text,
    mk_timeseries,
    mk_timeseries_multi,
)

_FULL_W = 24
_HALF_W = 12
_THIRD_W = 8
_QUARTER_W = 6
_PANEL_H = 8
_PIE_H = 10
_BAR_H = 10
_KPI_H = 5
_HDR_H = 2


def _row(title, y, collapsed=False):
    """Collapsible row panel."""
    return {"type": "row", "title": title, "collapsed": collapsed,
            "gridPos": {"h": 1, "w": _FULL_W, "x": 0, "y": y}}

_ROW_H = 1


def _section_header(title, y):
    """Thin markdown panel used as a visual section divider."""
    return mk_text(title, f"### {title}",
                   {"x": 0, "y": y, "w": _FULL_W, "h": _HDR_H})


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

def build_main_dashboard() -> dict:
    _reset_ids()
    panels = []
    y = 0

    # ΓöÇΓöÇ ES CPU + KPI ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(mk_cpu_panel({"x": 0, "y": y, "w": 18, "h": 6}))
    panels.append(mk_stat("Total Stress Score", "stress_score", "sum",
                          {"x": 18, "y": y, "w": _QUARTER_W, "h": 6},
                          description="Sum of all stress scores in the selected time period."))
    y += 6

    # ΓöÇΓöÇ Overview ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(mk_text("Dashboard Guide", CHEAT_SHEET,
                          {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
                          description="Quick reference guide for examining this dashboard."))
    y += _PANEL_H

    # 5 pie charts ΓÇö Cost Indicator pie uses raw (needs indicator names)
    for i, (field, label) in enumerate(SECTIONS[:3]):
        panels.append(mk_pie(f"Stress by {label} (Selected Period)", field,
                             {"x": i * _THIRD_W, "y": y, "w": _THIRD_W, "h": _PIE_H},
                             size=8,
                             description=PANEL_DESCRIPTIONS["pie"][label]))
    y += _PIE_H
    panels.append(mk_pie("Stress by Cost Indicator (Selected Period)",
                         "stress_cost_indicator_names",
                         {"x": 0, "y": y, "w": _HALF_W, "h": _PIE_H}, size=10,
                         description=PANEL_DESCRIPTIONS["pie"]["Cost Indicator"]))
    panels.append(mk_pie("Stress by Template (Selected Period)",
                         "request_template",
                         {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PIE_H}, size=10,
                         description=PANEL_DESCRIPTIONS["pie"]["Template"]))
    y += _PIE_H

    # ΓöÇΓöÇ Highest Impact ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Highest Impact", y))
    y += _ROW_H

    panels.append(mk_table(
        "Top 10 Templates by Stress Score", "request_template", "Template", [
            ("Sum Stress Score", "stress_score", "sum"),
            ("Avg Stress Score", "stress_score", "avg"),
            ("P50 ES Latency (ms)", "response_es_took_ms", "percentile_50"),
            ("P95 ES Latency (ms)", "response_es_took_ms", "percentile_95"),
            ("P99 ES Latency (ms)", "response_es_took_ms", "percentile_99"),
            ("Avg Cost Indicators", "stress_cost_indicator_count", "avg"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10,
        description="Top 10 request templates ranked by total stress score, with "
                    "latency percentiles and cost-indicator averages."))
    y += _PANEL_H

    panels.append(mk_raw_docs_table(
        "Top 10 Heaviest Operations", [
            ("timestamp", "Time"),
            ("request_body", "Request Body"),
            ("request_operation", "Operation"),
            ("request_target", "Target"),
            ("request_path", "Path"),
            ("stress_score", "Stress"),
            ("response_es_took_ms", "ES Latency (ms)"),
            ("stress_cost_indicator_names", "Cost Indicators"),
        ],
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H + 2},
        size=50, sort_field="stress_score",
        description="Individual requests with the highest stress scores in the "
                    "selected time range. Click column headers to re-sort."))
    y += _PANEL_H + 2

    # Uses raw ΓÇö needs cost_indicator_names as bucket
    panels.append(mk_table(
        "Top 10 Cost Indicators by Stress Score",
        "stress_cost_indicator_names", "Cost Indicator", [
            ("Sum Stress", "stress_score", "sum"),
            ("Avg Stress", "stress_score", "avg"),
            ("P50 ES Latency (ms)", "response_es_took_ms", "percentile_50"),
            ("P95 ES Latency (ms)", "response_es_took_ms", "percentile_95"),
            ("P99 ES Latency (ms)", "response_es_took_ms", "percentile_99"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10,
        description="Cost indicator types ranked by total stress contribution, "
                    "with latency percentiles."))
    y += _PANEL_H

    # ΓöÇΓöÇ Stress Trends ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Stress Trends", y))
    y += _ROW_H

    for field, label in SECTIONS:
        size = 10 if field == "request_template" else 5
        panels.append(mk_timeseries(
            f"Stress by {label}", field,
            {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
            size=size, series_type="line", fill_opacity=20,
            description=PANEL_DESCRIPTIONS["ts"][label]))
        y += _PANEL_H

    # ΓöÇΓöÇ Volume & Throughput ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Volume & Throughput", y))
    y += _ROW_H

    panels.append(mk_timeseries(
        "Request Volume", None,
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field=None, metric_op="count",
        series_type="line", fill_opacity=20, summary_fallback=True,
        description="Total request count over time. Dashed series = hourly "
                    "summary-index fallback (survives raw-data ILM expiry)."))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Documents Matched by Queries", None,
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field="response_hits", metric_op="sum",
        series_type="line", fill_opacity=20,
        description="Total documents matched by queries. Correlates with ES "
                    "CPU under queue saturation."))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Write Volume (Documents)", None,
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response_docs_affected", metric_op="sum",
        series_type="line", fill_opacity=20,
        description="Total documents written (index / bulk / update)."))
    panels.append(mk_timeseries(
        "Request Size", None,
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="request_size_bytes", metric_op="sum",
        series_type="line", fill_opacity=20, unit="decbytes",
        description="Total inbound request payload size."))
    y += _PANEL_H

    # ΓöÇΓöÇ Response Times ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Response Times", y))
    y += _ROW_H

    panels.append(mk_timeseries_multi("ES Latency", [
        ("Avg", "response_es_took_ms", "avg", ""),
        ("P50", "response_es_took_ms", "percentile_50", ""),
        ("P95", "response_es_took_ms", "percentile_95", ""),
        ("P99", "response_es_took_ms", "percentile_99", ""),
    ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", unit="ms",
        description="Elasticsearch response-time trend with Avg / P50 / P95 / "
                    "P99 ΓÇö rising P95/P99 signals tail-latency issues."))
    y += _PANEL_H

    return _wrap_dashboard(
        uid="alo-main",
        title="ALO ΓÇö Stress Analysis",
        description="Stress analysis by application, target, operation, and "
                    "template, with overall trend.",
        panels=panels,
    )


# ---------------------------------------------------------------------------
# Cost Indicators dashboard
# ---------------------------------------------------------------------------

def build_cost_indicators_dashboard() -> dict:
    _reset_ids()
    panels = []
    y = 0

    # Row 0: KPIs
    kpis = [
        ("Flagged Requests", "stress_cost_indicator_count", "count",
         "stress_cost_indicator_count >= 1",
         "Requests with at least one cost indicator firing."),
        ("Avg Indicator Count", "stress_cost_indicator_count", "avg", "",
         "Mean number of cost indicators per request."),
        ("Avg Stress Multiplier", "stress_multiplier", "avg", "",
         "Mean stress multiplier applied to base score."),
        ("Max Stress Multiplier", "stress_multiplier", "max", "",
         "Largest stress multiplier observed in the selected period."),
    ]
    for i, (title, field, op, query, desc) in enumerate(kpis):
        panels.append(mk_stat(title, field, op,
                              {"x": i * _QUARTER_W, "y": y, "w": _QUARTER_W,
                               "h": _KPI_H},
                              query=query, description=desc))
    y += _KPI_H

    # ΓöÇΓöÇ Score Composition ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Score Composition", y))
    y += _ROW_H

    # Stacked bar: what drives the base score per template
    panels.append(mk_stacked_bar(
        "Score Composition by Template", "request_template", [
            ("Took", "stress_components_took", "avg"),
            ("Shards", "stress_components_shards", "avg"),
            ("Hits", "stress_components_hits", "avg"),
            ("Bonus", "stress_components_bonus", "avg"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _BAR_H},
        description="Stacked contribution of each base-score component (Took / "
                    "Shards / Hits / Bonus) per template ΓÇö shows what drives the score."))
    y += _BAR_H

    # Base vs Final score + Multiplier breakdown
    panels.append(mk_table(
        "Base vs Final Score by Template", "request_template", "Template", [
            ("Requests", None, "count"),
            ("Avg Base", "stress_base", "avg"),
            ("Avg Multiplier", "stress_multiplier", "avg"),
            ("Avg Final Score", "stress_score", "avg"),
            ("Avg Indicators", "stress_cost_indicator_count", "avg"),
        ], {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H},
        description="Base score vs multiplier vs final score per template ΓÇö "
                    "reveals whether stress is driven by the base or the multiplier."))
    panels.append(mk_table(
        "Top Templates by Cost Indicator Count",
        "request_template", "Template", [
            ("Avg Indicators", "stress_cost_indicator_count", "avg"),
            ("Avg Multiplier", "stress_multiplier", "avg"),
            ("Avg Stress", "stress_score", "avg"),
            ("Requests", None, "count"),
        ], {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H},
        description="Templates ranked by average cost indicator count ΓÇö "
                    "query optimization candidates."))
    y += _BAR_H

    # ΓöÇΓöÇ Score Breakdown ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Score Breakdown", y))
    y += _ROW_H

    panels.append(mk_table(
        "Score Breakdown by Template", "request_template", "Template", [
            ("Requests", None, "count"),
            ("Avg Score", "stress_score", "avg"),
            ("Multiplier", "stress_multiplier", "avg"),
            ("ES Took (weighted)", "stress_components_took", "avg"),
            ("P50 ES Latency (ms)", "response_es_took_ms", "percentile_50"),
            ("P95 ES Latency (ms)", "response_es_took_ms", "percentile_95"),
            ("P99 ES Latency (ms)", "response_es_took_ms", "percentile_99"),
            ("Shards (weighted)", "stress_components_shards", "avg"),
            ("Shards (raw)", "response_shards_total", "avg"),
            ("Hits (weighted)", "stress_components_hits", "avg"),
            ("Hits (raw)", "response_hits", "avg"),
            ("Bonus", "stress_components_bonus", "avg"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _BAR_H},
        description="Full per-template breakdown: score, multiplier, weighted "
                    "components, and raw ES metrics (latency percentiles, shards, hits)."))
    y += _BAR_H

    # ΓöÇΓöÇ Trends ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Trends", y))
    y += _ROW_H

    panels.append(mk_timeseries_multi(
        "Score Components", [
            ("Avg Took", "stress_components_took", "avg", ""),
            ("Avg Shards", "stress_components_shards", "avg", ""),
            ("Avg Hits", "stress_components_hits", "avg", ""),
            ("Avg Bonus", "stress_components_bonus", "avg", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", stacked=True,
        description="Stacked trend of the four base-score components (Took, "
                    "Shards, Hits, Bonus) over time."))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Avg Base Score by Template", "request_template",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="stress_base", metric_op="avg", size=10,
        description="Average base stress score over time, per template."))
    panels.append(mk_timeseries(
        "Avg Multiplier by Template", "request_template",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="stress_multiplier", metric_op="avg", size=10,
        description="Average stress multiplier over time, per template."))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Avg Cost Indicators by Application",
        "identity_applicative_provider",
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field="stress_cost_indicator_count", metric_op="avg", size=8,
        description="Average number of cost indicators per request over time, "
                    "broken down by applicative provider."))
    y += _PANEL_H

    panels.append(mk_timeseries_multi(
        "Flagged vs Total Requests", [
            ("Flagged Requests", None, "count",
             "stress_cost_indicator_count >= 1"),
            ("Total Requests", None, "count", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line",
        description="Count of flagged (ΓëÑ1 cost indicator) vs total requests ΓÇö "
                    "the ratio indicates how many queries are suboptimal."))
    y += _PANEL_H

    # ΓöÇΓöÇ Cost Indicator Deep Dive ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Cost Indicator Deep Dive", y))
    y += _ROW_H

    panels.append(mk_bar(
        "Cost Indicator Types - Frequency",
        "stress_cost_indicator_names", None, "count", "Count",
        {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H},
        description="How often each cost indicator type fires in the selected period."))
    panels.append(mk_bar(
        "Stress Multiplier by Application",
        "identity_applicative_provider", "stress_multiplier", "avg",
        "Avg Stress Multiplier",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8,
        description="Average stress multiplier per applicative provider."))
    y += _BAR_H

    panels.append(mk_bar(
        "Cost Indicator Count by Target Index",
        "request_target", "stress_cost_indicator_count", "avg",
        "Avg Indicator Count",
        {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8,
        description="Average cost indicators per request, per target index."))
    panels.append(mk_bar(
        "Stress Multiplier by Target Index",
        "request_target", "stress_multiplier", "avg",
        "Avg Multiplier",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8,
        description="Average stress multiplier per target index."))
    y += _BAR_H

    # ΓöÇΓöÇ Clause Patterns ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_row("Clause Patterns", y))
    y += _ROW_H

    panels.append(mk_timeseries_multi(
        "Clause Count Trends", [
            ("Avg terms_values", "clause_counts_terms_values", "avg", ""),
            ("Avg agg", "clause_counts_agg", "avg", ""),
            ("Avg script", "clause_counts_script", "avg", ""),
            ("Avg wildcard", "clause_counts_wildcard", "avg", ""),
        ], {"x": 0, "y": y, "w": _HALF_W + 2, "h": _BAR_H},
        series_type="line",
        description="Average per-request counts of heavy clause types over time."))
    panels.append(mk_timeseries_multi(
        "Bool Clause Breakdown", [
            ("Avg must", "clause_counts_bool_must", "avg", ""),
            ("Avg should", "clause_counts_bool_should", "avg", ""),
            ("Avg filter", "clause_counts_bool_filter", "avg", ""),
            ("Avg must_not", "clause_counts_bool_must_not", "avg", ""),
        ], {"x": _HALF_W + 2, "y": y, "w": _HALF_W - 2, "h": _BAR_H},
        series_type="line", stacked=True,
        description="Stacked trend of bool clause types per request "
                    "(must / should / filter / must_not)."))
    y += _BAR_H

    return _wrap_dashboard(
        uid="alo-cost-indicators",
        title="Cost Indicators & Query Patterns",
        description="Cost indicators, clause counts, and query pattern analysis.",
        panels=panels,
    )


# ---------------------------------------------------------------------------
# Usage dashboard
# ---------------------------------------------------------------------------

def build_usage_dashboard() -> dict:
    _reset_ids()
    panels = []
    y = 0

    # ΓöÇΓöÇ Request Rates ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_section_header("Request Rates", y))
    y += _HDR_H

    panels.append(mk_timeseries_multi(
        "Total Request Rate", [
            ("Requests", None, "count", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line",
        description="Total request count over time across the selected filters."))
    y += _PANEL_H

    for field, label in [
        ("request_operation", "Operation"),
        ("identity_applicative_provider", "Application"),
        ("request_target", "Target Index"),
        ("request_template", "Template"),
    ]:
        panels.append(mk_timeseries(
            f"Rate by {label}", field,
            {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
            metric_field=None, metric_op="count", size=8,
            series_type="line", fill_opacity=20,
            summary_fallback=True,
            description=f"Request rate over time, broken down by {label.lower()}. "
                        "Dashed series = hourly summary-index fallback "
                        "(survives raw-data ILM expiry)."))
        y += _PANEL_H

    # ΓöÇΓöÇ Latency ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_section_header("Latency", y))
    y += _HDR_H

    panels.append(mk_timeseries_multi("ES Latency", [
        ("Avg", "response_es_took_ms", "avg", ""),
        ("P50", "response_es_took_ms", "percentile_50", ""),
        ("P95", "response_es_took_ms", "percentile_95", ""),
        ("P99", "response_es_took_ms", "percentile_99", ""),
    ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", unit="ms",
        description="Elasticsearch response-time trend with Avg / P50 / P95 / "
                    "P99. Rising P95/P99 signals tail-latency issues."))
    y += _PANEL_H

    # ΓöÇΓöÇ Errors ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_section_header("Errors", y))
    y += _HDR_H

    panels.append(mk_timeseries_multi(
        "Error Rate", [
            ("Errors (4xx+5xx)", None, "count",
             "response_status >= 400"),
            ("Total Requests", None, "count", ""),
        ], {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        series_type="line",
        description="Count of error responses (status ΓëÑ 400) vs total requests."))
    panels.append(mk_table(
        "Requests by Status Code",
        "response_status", "Status Code", [
            ("Requests", None, "count"),
        ], {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10,
        description="Top 10 response status codes by request count."))
    y += _PANEL_H

    panels.append(mk_table(
        "Requests by Application",
        "identity_applicative_provider", "Application", [
            ("Requests", None, "count"),
            ("P50 ES Latency (ms)", "response_es_took_ms", "percentile_50"),
            ("P95 ES Latency (ms)", "response_es_took_ms", "percentile_95"),
            ("P99 ES Latency (ms)", "response_es_took_ms", "percentile_99"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10,
        description="Per-application request counts and ES latency percentiles."))
    y += _PANEL_H

    # ΓöÇΓöÇ Data Volume ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_section_header("Data Volume", y))
    y += _HDR_H

    panels.append(mk_timeseries(
        "Read Volume (Total Hits)", "request_operation",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response_hits", metric_op="sum", size=8,
        series_type="line", fill_opacity=20,
        description="Total documents matched by queries, split by operation type."))
    panels.append(mk_timeseries(
        "Write Volume (Docs Affected)", "request_operation",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response_docs_affected", metric_op="sum", size=8,
        series_type="line", fill_opacity=20,
        description="Total documents written (indexed / updated / deleted), "
                    "split by operation type."))
    y += _PANEL_H

    panels.append(mk_timeseries_multi(
        "Payload Sizes", [
            ("Avg Request Size", "request_size_bytes", "avg", ""),
            ("Avg Response Size", "response_size_bytes", "avg", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", unit="decbytes",
        description="Average request and response payload sizes over time."))
    y += _PANEL_H

    # ΓöÇΓöÇ Top Activity ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    panels.append(_section_header("Top Activity", y))
    y += _HDR_H

    panels.append(mk_bar(
        "Top 10 Applications",
        "identity_applicative_provider", None, "count", "Requests",
        {"x": 0, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10,
        description="Top 10 applicative providers by request count."))
    panels.append(mk_bar(
        "Top 10 Indices",
        "request_target", None, "count", "Requests",
        {"x": _THIRD_W, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10,
        description="Top 10 target indices by request count."))
    panels.append(mk_bar(
        "Top 10 Users",
        "identity_username", None, "count", "Requests",
        {"x": 2 * _THIRD_W, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10,
        description="Top 10 users by request count."))

    return _wrap_dashboard(
        uid="alo-usage",
        title="ALO ΓÇö Cluster Usage",
        description="Request rates, latency percentiles, error tracking, "
                    "and data volume analytics.",
        panels=panels,
    )
