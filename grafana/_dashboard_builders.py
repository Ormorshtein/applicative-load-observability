"""Dashboard assembly for Grafana provisioning.

Each builder creates a complete dashboard dict ready for JSON export.
Panel helpers (mk_*) are imported from _dashboards.
"""

from _dashboards import (
    CHEAT_SHEET,
    SECTIONS,
    _reset_ids,
    _wrap_dashboard,
    mk_bar,
    mk_cpu_panel,
    mk_pie,
    mk_stacked_bar,
    mk_stat,
    mk_summary_table,
    mk_summary_timeseries,
    mk_table,
    mk_text,
    mk_timeseries,
    mk_timeseries_multi,
    mk_timeseries_response,
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

    # ── ES CPU + KPI ─────────────────────────────────────────────────────
    panels.append(mk_cpu_panel({"x": 0, "y": y, "w": 18, "h": 6}))
    panels.append(mk_stat("Total Stress Score", "stress.score", "sum",
                          {"x": 18, "y": y, "w": _QUARTER_W, "h": 6}))
    y += 6

    # ── Overview ────────────────────────────────────────────────────────
    panels.append(mk_text("Dashboard Guide", CHEAT_SHEET,
                          {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}))
    y += _PANEL_H

    # 5 pie charts — Cost Indicator pie uses raw (needs indicator names)
    for i, (field, label) in enumerate(SECTIONS[:3]):
        panels.append(mk_pie(f"Stress by {label} (Selected Period)", field,
                             {"x": i * _THIRD_W, "y": y, "w": _THIRD_W, "h": _PIE_H},
                             size=8))
    y += _PIE_H
    panels.append(mk_pie("Stress by Cost Indicator (Selected Period)",
                         "stress.cost_indicator_names",
                         {"x": 0, "y": y, "w": _HALF_W, "h": _PIE_H}, size=10))
    panels.append(mk_pie("Stress by Template (Selected Period)",
                         "request.template",
                         {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PIE_H}, size=10))
    y += _PIE_H

    # ── Highest Impact ──────────────────────────────────────────────────
    panels.append(_row("Highest Impact", y))
    y += _ROW_H

    panels.append(mk_table(
        "Top 10 Templates by Stress Score", "request.template", "Template", [
            ("Sum Stress", "stress.score", "sum"),
            ("Avg Stress", "stress.score", "avg"),
            ("Avg ES Latency (ms)", "response.es_took_ms", "avg"),
            ("Avg Cost Indicators", "stress.cost_indicator_count", "avg"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    # Uses raw — needs cost_indicator_names as bucket
    panels.append(mk_table(
        "Top 10 Cost Indicators by Stress Score",
        "stress.cost_indicator_names", "Cost Indicator", [
            ("Sum Stress", "stress.score", "sum"),
            ("Avg Stress", "stress.score", "avg"),
            ("Avg ES Latency (ms)", "response.es_took_ms", "avg"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    # ── Stress Trends ───────────────────────────────────────────────────
    panels.append(_row("Stress Trends", y))
    y += _ROW_H

    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 5
        panels.append(mk_timeseries(
            f"Stress by {label}", field,
            {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
            size=size, series_type="line", fill_opacity=20))
        y += _PANEL_H

    # ── Volume & Throughput ─────────────────────────────────────────────
    panels.append(_row("Volume & Throughput", y))
    y += _ROW_H

    panels.append(mk_timeseries(
        "Request Volume", None,
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field=None, metric_op="count",
        series_type="line", fill_opacity=20))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Documents Matched by Queries", None,
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field="response.hits", metric_op="sum",
        series_type="line", fill_opacity=20))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Write Volume (Documents)", None,
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response.docs_affected", metric_op="sum",
        series_type="line", fill_opacity=20))
    panels.append(mk_timeseries(
        "Request Size (Bytes)", None,
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="request.size_bytes", metric_op="sum",
        series_type="line", fill_opacity=20))
    y += _PANEL_H

    # ── Response Times ────────────────────────────────────────────────
    panels.append(_row("Response Times", y))
    y += _ROW_H

    panels.append(mk_timeseries(
        "Avg ES Latency (ms)", None,
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field="response.es_took_ms", metric_op="avg",
        series_type="line", fill_opacity=20))
    y += _PANEL_H

    return _wrap_dashboard(
        uid="alo-main",
        title="ALO — Stress Analysis",
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
        ("Flagged Requests", "stress.cost_indicator_count", "count",
         "stress.cost_indicator_count:[1 TO *]"),
        ("Avg Indicator Count", "stress.cost_indicator_count", "avg", ""),
        ("Avg Stress Multiplier", "stress.multiplier", "avg", ""),
        ("Max Stress Multiplier", "stress.multiplier", "max", ""),
    ]
    for i, (title, field, op, query) in enumerate(kpis):
        panels.append(mk_stat(title, field, op,
                              {"x": i * _QUARTER_W, "y": y, "w": _QUARTER_W,
                               "h": _KPI_H},
                              query=query))
    y += _KPI_H

    # ── Score Composition ─────────────────────────────────────────────
    panels.append(_row("Score Composition", y))
    y += _ROW_H

    # Stacked bar: what drives the base score per template
    panels.append(mk_stacked_bar(
        "Score Composition by Template", "request.template", [
            ("Took", "stress.components.took", "avg"),
            ("Shards", "stress.components.shards", "avg"),
            ("Hits", "stress.components.hits", "avg"),
            ("Bonus", "stress.components.bonus", "avg"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _BAR_H}))
    y += _BAR_H

    # Base vs Final score + Multiplier breakdown
    panels.append(mk_table(
        "Base vs Final Score by Template", "request.template", "Template", [
            ("Requests", None, "count"),
            ("Avg Base", "stress.base", "avg"),
            ("Avg Multiplier", "stress.multiplier", "avg"),
            ("Avg Final Score", "stress.score", "avg"),
            ("Avg Indicators", "stress.cost_indicator_count", "avg"),
        ], {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H}))
    panels.append(mk_table(
        "Top Templates by Cost Indicator Count",
        "request.template", "Template", [
            ("Avg Indicators", "stress.cost_indicator_count", "avg"),
            ("Avg Multiplier", "stress.multiplier", "avg"),
            ("Avg Stress", "stress.score", "avg"),
            ("Requests", None, "count"),
        ], {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}))
    y += _BAR_H

    # ── Score Breakdown ──────────────────────────────────────────────
    panels.append(_row("Score Breakdown", y))
    y += _ROW_H

    panels.append(mk_table(
        "Score Breakdown by Template", "request.template", "Template", [
            ("Requests", None, "count"),
            ("Avg Score", "stress.score", "avg"),
            ("Multiplier", "stress.multiplier", "avg"),
            ("ES Took (weighted)", "stress.components.took", "avg"),
            ("ES Latency (ms)", "response.es_took_ms", "avg"),
            ("Shards (weighted)", "stress.components.shards", "avg"),
            ("Shards (raw)", "response.shards_total", "avg"),
            ("Hits (weighted)", "stress.components.hits", "avg"),
            ("Hits (raw)", "response.hits", "avg"),
            ("Bonus", "stress.components.bonus", "avg"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _BAR_H}))
    y += _BAR_H

    # ── Trends ──────────────────────────────────────────────────────
    panels.append(_row("Trends", y))
    y += _ROW_H

    panels.append(mk_timeseries_multi(
        "Score Components", [
            ("Avg Took", "stress.components.took", "avg", ""),
            ("Avg Shards", "stress.components.shards", "avg", ""),
            ("Avg Hits", "stress.components.hits", "avg", ""),
            ("Avg Bonus", "stress.components.bonus", "avg", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", stacked=True))
    y += _PANEL_H

    panels.append(mk_timeseries_multi(
        "Flagged vs Total Requests", [
            ("Flagged Requests", None, "count",
             "stress.cost_indicator_count:[1 TO *]"),
            ("Total Requests", None, "count", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line"))
    y += _PANEL_H

    # ── Cost Indicator Deep Dive ──────────────────────────────────────
    panels.append(_row("Cost Indicator Deep Dive", y))
    y += _ROW_H

    panels.append(mk_bar(
        "Cost Indicator Types - Frequency",
        "stress.cost_indicator_names", None, "count", "Count",
        {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H}))
    panels.append(mk_bar(
        "Stress Multiplier by Application",
        "identity.applicative_provider", "stress.multiplier", "avg",
        "Avg Stress Multiplier",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8))
    y += _BAR_H

    panels.append(mk_bar(
        "Cost Indicator Count by Target Index",
        "request.target", "stress.cost_indicator_count", "avg",
        "Avg Indicator Count",
        {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8))
    panels.append(mk_bar(
        "Stress Multiplier by Target Index",
        "request.target", "stress.multiplier", "avg",
        "Avg Multiplier",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8))
    y += _BAR_H

    # ── Clause Patterns ──────────────────────────────────────────────
    panels.append(_row("Clause Patterns", y))
    y += _ROW_H

    panels.append(mk_timeseries_multi(
        "Clause Count Trends", [
            ("Avg terms_values", "clause_counts.terms_values", "avg", ""),
            ("Avg agg", "clause_counts.agg", "avg", ""),
            ("Avg script", "clause_counts.script", "avg", ""),
            ("Avg wildcard", "clause_counts.wildcard", "avg", ""),
        ], {"x": 0, "y": y, "w": _HALF_W + 2, "h": _BAR_H},
        series_type="line"))
    panels.append(mk_timeseries_multi(
        "Bool Clause Breakdown", [
            ("Avg must", "clause_counts.bool_must", "avg", ""),
            ("Avg should", "clause_counts.bool_should", "avg", ""),
            ("Avg filter", "clause_counts.bool_filter", "avg", ""),
            ("Avg must_not", "clause_counts.bool_must_not", "avg", ""),
        ], {"x": _HALF_W + 2, "y": y, "w": _HALF_W - 2, "h": _BAR_H},
        series_type="line", stacked=True))
    y += _BAR_H

    # ── Historical Trends ──────────────────────────────────────────
    panels.append(_row("Historical Trends", y, collapsed=True))
    y += _ROW_H

    panels.append(mk_summary_timeseries(
        "Base Score by Template (Historical)", "avg_base", "template",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10))
    panels.append(mk_summary_timeseries(
        "Avg Multiplier by Template (Historical)", "avg_multiplier", "template",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    panels.append(mk_summary_timeseries(
        "Avg Cost Indicators by Application (Historical)",
        "avg_cost_indicator_count", "applicative_provider",
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=8))

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

    # ── Request Rates ───────────────────────────────────────────────────
    panels.append(_section_header("Request Rates", y))
    y += _HDR_H

    panels.append(mk_timeseries_multi(
        "Total Request Rate", [
            ("Requests", None, "count", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line"))
    y += _PANEL_H

    for field, label in [
        ("request.operation", "Operation"),
        ("identity.applicative_provider", "Application"),
        ("request.target", "Target Index"),
    ]:
        panels.append(mk_timeseries(
            f"Rate by {label}", field,
            {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
            metric_field=None, metric_op="count", size=8,
            series_type="line", fill_opacity=20))
        y += _PANEL_H

    # ── Latency ─────────────────────────────────────────────────────────
    panels.append(_section_header("Latency", y))
    y += _HDR_H

    for latency_field, title in [
        ("response.es_took_ms", "ES Latency"),
        ("response.gateway_took_ms", "Gateway Latency"),
    ]:
        panels.append(mk_timeseries_multi(title, [
            ("Min", latency_field, "min", ""),
            ("Avg", latency_field, "avg", ""),
            ("P50", latency_field, "percentile_50", ""),
            ("P75", latency_field, "percentile_75", ""),
            ("P95", latency_field, "percentile_95", ""),
            ("P99", latency_field, "percentile_99", ""),
            ("Max", latency_field, "max", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
            series_type="line"))
        y += _PANEL_H

    panels.append(mk_timeseries(
        "Avg ES Latency by Operation", "request.operation",
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field="response.es_took_ms", metric_op="avg", size=8,
        series_type="line", fill_opacity=20))
    y += _PANEL_H

    # ── Errors ──────────────────────────────────────────────────────────
    panels.append(_section_header("Errors", y))
    y += _HDR_H

    panels.append(mk_timeseries_multi(
        "Error Rate", [
            ("Errors (4xx+5xx)", None, "count",
             "response.status:[400 TO *]"),
            ("Total Requests", None, "count", ""),
        ], {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        series_type="line"))
    panels.append(mk_bar(
        "Requests by Status Code",
        "response.status", None, "count", "Count",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    panels.append(mk_table(
        "Errors by Application",
        "identity.applicative_provider", "Application", [
            ("Errors", None, "count"),
            ("Total", None, "count"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    # ── Data Volume ─────────────────────────────────────────────────────
    panels.append(_section_header("Data Volume", y))
    y += _HDR_H

    panels.append(mk_timeseries(
        "Read Volume (Total Hits)", "request.operation",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response.hits", metric_op="sum", size=8,
        series_type="line", fill_opacity=20))
    panels.append(mk_timeseries(
        "Write Volume (Docs Affected)", "request.operation",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response.docs_affected", metric_op="sum", size=8,
        series_type="line", fill_opacity=20))
    y += _PANEL_H

    panels.append(mk_timeseries_multi(
        "Payload Sizes", [
            ("Avg Request Size", "request.size_bytes", "avg", ""),
            ("Avg Response Size", "response.size_bytes", "avg", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line"))
    y += _PANEL_H

    # ── Top Activity ────────────────────────────────────────────────────
    panels.append(_section_header("Top Activity", y))
    y += _HDR_H

    panels.append(mk_bar(
        "Top 10 Applications",
        "identity.applicative_provider", None, "count", "Requests",
        {"x": 0, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10))
    panels.append(mk_bar(
        "Top 10 Indices",
        "request.target", None, "count", "Requests",
        {"x": _THIRD_W, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10))
    panels.append(mk_bar(
        "Top 10 Users",
        "identity.username", None, "count", "Requests",
        {"x": 2 * _THIRD_W, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10))

    return _wrap_dashboard(
        uid="alo-usage",
        title="ALO — Cluster Usage",
        description="Request rates, latency percentiles, error tracking, "
                    "and data volume analytics.",
        panels=panels,
    )


# ---------------------------------------------------------------------------
# Historical Trends dashboard (summary index only — lightweight)
# ---------------------------------------------------------------------------

def build_historical_dashboard() -> dict:
    _reset_ids()
    panels = []
    y = 0

    # ── Stress Trends ──────────────────────────────────────────────────
    panels.append(_section_header("Stress Trends", y))
    y += _HDR_H

    panels.append(mk_summary_timeseries(
        "Stress Score by Template", "avg_score", "template",
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    panels.append(mk_summary_timeseries(
        "Stress Score by Application", "avg_score", "applicative_provider",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=8))
    panels.append(mk_summary_timeseries(
        "Stress Score by Target Index", "avg_score", "target",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=8))
    y += _PANEL_H

    # ── Score Composition ──────────────────────────────────────────────
    panels.append(_section_header("Score Composition", y))
    y += _HDR_H

    panels.append(mk_summary_timeseries(
        "Avg Base Score by Template", "avg_base", "template",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10))
    panels.append(mk_summary_timeseries(
        "Avg Multiplier by Template", "avg_multiplier", "template",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    panels.append(mk_summary_timeseries(
        "Avg Cost Indicators by Application",
        "avg_cost_indicator_count", "applicative_provider",
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=8))
    y += _PANEL_H

    # ── Volume & Latency ───────────────────────────────────────────────
    panels.append(_section_header("Volume & Latency", y))
    y += _HDR_H

    panels.append(mk_summary_timeseries(
        "Request Volume by Operation", "count", "operation",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_op="sum", size=8))
    panels.append(mk_summary_timeseries(
        "Request Volume by Application", "count", "applicative_provider",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_op="sum", size=8))
    y += _PANEL_H

    panels.append(mk_summary_timeseries(
        "Avg ES Latency by Template", "avg_es_took_ms", "template",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10))
    panels.append(mk_summary_timeseries(
        "Avg Gateway Latency by Template", "avg_gateway_took_ms", "template",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10))
    y += _PANEL_H

    # ── Top Tables ─────────────────────────────────────────────────────
    panels.append(_section_header("Top Offenders (All Time)", y))
    y += _HDR_H

    panels.append(mk_summary_table(
        "Top Templates by Cumulative Stress", "template", "Template", [
            ("Total Stress", "sum_score", "sum"),
            ("Avg Score", "avg_score", "avg"),
            ("Total Requests", "count", "sum"),
            ("Avg Latency (ms)", "avg_es_took_ms", "avg"),
            ("Avg Multiplier", "avg_multiplier", "avg"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _BAR_H}, size=10))
    y += _BAR_H

    panels.append(mk_summary_table(
        "Top Applications by Cumulative Stress",
        "applicative_provider", "Application", [
            ("Total Stress", "sum_score", "sum"),
            ("Avg Score", "avg_score", "avg"),
            ("Total Requests", "count", "sum"),
            ("Avg Latency (ms)", "avg_es_took_ms", "avg"),
        ], {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H}, size=10))
    panels.append(mk_summary_table(
        "Top Indices by Cumulative Stress", "target", "Target Index", [
            ("Total Stress", "sum_score", "sum"),
            ("Avg Score", "avg_score", "avg"),
            ("Total Requests", "count", "sum"),
        ], {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}, size=10))

    return _wrap_dashboard(
        uid="alo-historical",
        title="ALO — Historical Trends",
        description="Long-term trends from hourly summary data. "
                    "Persists after raw indices are deleted.",
        panels=panels,
    )
