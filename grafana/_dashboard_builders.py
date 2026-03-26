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
    mk_pie,
    mk_stat,
    mk_table,
    mk_text,
    mk_timeseries,
    mk_timeseries_multi,
    mk_timeseries_response,
)


def build_main_dashboard() -> dict:
    _reset_ids()
    panels = []
    y = 0

    # Row 0: Cheat sheet + Total Stress Score
    panels.append(mk_text("Dashboard Guide", CHEAT_SHEET,
                          {"x": 0, "y": y, "w": 18, "h": 8}))
    panels.append(mk_stat("Total Stress Score", "stress.score", "sum",
                          {"x": 18, "y": y, "w": 6, "h": 8}))
    y += 8

    # Row 1: 5 pie charts
    pie_h = 10
    for i, (field, label) in enumerate(SECTIONS[:3]):
        panels.append(mk_pie(f"Stress by {label} (Selected Period)", field,
                             {"x": i * 8, "y": y, "w": 8, "h": pie_h}, size=8))
    y += pie_h
    panels.append(mk_pie("Stress by Cost Indicator (Selected Period)",
                         "stress.cost_indicator_names",
                         {"x": 0, "y": y, "w": 12, "h": pie_h}, size=10))
    panels.append(mk_pie("Stress by Template (Selected Period)",
                         "request.template",
                         {"x": 12, "y": y, "w": 12, "h": pie_h}, size=10))
    y += pie_h

    # Stress over time per dimension
    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 5
        panels.append(mk_timeseries(
            f"Stress Over Time by {label}", field,
            {"x": 0, "y": y, "w": 24, "h": 8},
            size=size, series_type="line", fill_opacity=20))
        y += 8

    # Request volume over time by template
    panels.append(mk_timeseries(
        "Request Volume Over Time by Template", "request.template",
        {"x": 0, "y": y, "w": 24, "h": 8},
        metric_field=None, metric_op="count", size=10,
        series_type="line", fill_opacity=20))
    y += 8

    # Total hits over time
    panels.append(mk_timeseries(
        "Total Hits Over Time", "request.operation",
        {"x": 0, "y": y, "w": 24, "h": 8},
        metric_field="response.hits", metric_op="sum", size=8,
        series_type="line", fill_opacity=20))
    y += 8

    # Docs affected + request size over time
    panels.append(mk_timeseries(
        "Docs Affected Over Time", "request.operation",
        {"x": 0, "y": y, "w": 12, "h": 8},
        metric_field="response.docs_affected", metric_op="sum", size=8,
        series_type="line", fill_opacity=20))
    panels.append(mk_timeseries(
        "Request Size Over Time", "request.operation",
        {"x": 12, "y": y, "w": 12, "h": 8},
        metric_field="request.size_bytes", metric_op="sum", size=8,
        series_type="line", fill_opacity=20))
    y += 8

    # Top 10 Templates table
    panels.append(mk_table(
        "Top 10 Templates by Stress Score", "request.template", "Template", [
            ("Sum Stress", "stress.score", "sum"),
            ("Avg Stress", "stress.score", "avg"),
            ("Avg ES Latency (ms)", "response.es_took_ms", "avg"),
            ("Avg Gateway Latency (ms)", "response.gateway_took_ms", "avg"),
            ("Avg Cost Indicators", "stress.cost_indicator_count", "avg"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": 24, "h": 8}, size=10))
    y += 8

    # Top 10 Cost Indicators table
    panels.append(mk_table(
        "Top 10 Cost Indicators by Stress Score",
        "stress.cost_indicator_names", "Cost Indicator", [
            ("Sum Stress", "stress.score", "sum"),
            ("Avg Stress", "stress.score", "avg"),
            ("Avg ES Latency (ms)", "response.es_took_ms", "avg"),
            ("Avg Gateway Latency (ms)", "response.gateway_took_ms", "avg"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": 24, "h": 8}, size=10))
    y += 8

    # Response time panels
    response_breakdowns = [
        ("stress.cost_indicator_names", "Cost Indicator"),
        ("request.operation", "Operation"),
        ("request.template", "Template"),
    ]
    for latency_field, _latency_label, row_label in [
        ("response.es_took_ms", "Avg ES Latency (ms)", "ES"),
        ("response.gateway_took_ms", "Avg Gateway Latency (ms)", "Gateway"),
    ]:
        for j, (bd_field, bd_label) in enumerate(response_breakdowns):
            panels.append(mk_timeseries_response(
                f"Avg {row_label} Response Time by {bd_label}",
                bd_field, latency_field, f"Avg {row_label} Latency (ms)",
                {"x": j * 8, "y": y, "w": 8, "h": 8}))
        y += 8

    # Sanity check tables
    panels.append(mk_table(
        "Top 10 Most Recurring Templates", "request.template", "Template", [
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": 12, "h": 8}, size=10))
    panels.append(mk_table(
        "Top 10 Templates with Most Cost Indicators",
        "request.template", "Template", [
            ("Avg Cost Indicators", "stress.cost_indicator_count", "avg"),
            ("Requests", None, "count"),
        ], {"x": 12, "y": y, "w": 12, "h": 8}, size=10))

    return _wrap_dashboard(
        uid="alo-main",
        title="ALO — Stress Analysis",
        description="Stress analysis by application, target, operation, and "
                    "template, with overall trend.",
        panels=panels,
    )


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
                              {"x": i * 6, "y": y, "w": 6, "h": 5},
                              query=query))
    y += 5

    # Row 1: Indicator overview
    panels.append(mk_bar(
        "Cost Indicator Types - Frequency",
        "stress.cost_indicator_names", None, "count", "Count",
        {"x": 0, "y": y, "w": 10, "h": 10}))
    panels.append(mk_timeseries_multi(
        "Flagged vs Total Requests Over Time", [
            ("Flagged Requests", None, "count",
             "stress.cost_indicator_count:[1 TO *]"),
            ("Total Requests", None, "count", ""),
        ], {"x": 10, "y": y, "w": 14, "h": 10}, series_type="line"))
    y += 10

    # Row 2: Clause counts
    panels.append(mk_timeseries_multi(
        "Clause Count Trends", [
            ("Avg terms_values", "clause_counts.terms_values", "avg", ""),
            ("Avg agg", "clause_counts.agg", "avg", ""),
            ("Avg script", "clause_counts.script", "avg", ""),
            ("Avg wildcard", "clause_counts.wildcard", "avg", ""),
        ], {"x": 0, "y": y, "w": 14, "h": 10}, series_type="line"))
    panels.append(mk_timeseries_multi(
        "Bool Clause Breakdown Over Time", [
            ("Avg must", "clause_counts.bool_must", "avg", ""),
            ("Avg should", "clause_counts.bool_should", "avg", ""),
            ("Avg filter", "clause_counts.bool_filter", "avg", ""),
            ("Avg must_not", "clause_counts.bool_must_not", "avg", ""),
        ], {"x": 14, "y": y, "w": 10, "h": 10},
        series_type="line", stacked=True))
    y += 10

    # Row 3: Template table
    panels.append(mk_table(
        "Top Templates by Cost Indicator Count",
        "request.template", "Template", [
            ("Avg Indicators", "stress.cost_indicator_count", "avg"),
            ("Requests", None, "count"),
            ("Avg Multiplier", "stress.multiplier", "avg"),
            ("Avg Stress", "stress.score", "avg"),
        ], {"x": 0, "y": y, "w": 24, "h": 8}))
    y += 8

    # Row 4: By dimension
    panels.append(mk_bar(
        "Stress Multiplier by Application",
        "identity.applicative_provider", "stress.multiplier", "avg",
        "Avg Stress Multiplier", {"x": 0, "y": y, "w": 12, "h": 10}, size=8))
    panels.append(mk_bar(
        "Cost Indicator Count by Target Index",
        "request.target", "stress.cost_indicator_count", "avg",
        "Avg Indicator Count", {"x": 12, "y": y, "w": 12, "h": 10}, size=8))

    return _wrap_dashboard(
        uid="alo-cost-indicators",
        title="Cost Indicators & Query Patterns",
        description="Cost indicators, clause counts, and query pattern analysis.",
        panels=panels,
    )
