"""Dashboard assembly for Grafana provisioning.

Each builder creates a complete dashboard dict ready for JSON export.
Panel helpers (mk_*) are imported from _dashboards.
"""

from _dashboards import (
    PANEL_DESCRIPTIONS,
    SECTIONS,
    _reset_ids,
    _wrap_dashboard,
    cheat_sheet,
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
from _strings import tr

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


_MAIN_UIDS = {"en": "alo-main", "he": "alo-main-he"}


def _main_dashboard_links(lang):
    """Top-bar links pointing at the other-language variant of this dashboard."""
    if lang == "en":
        target_uid = _MAIN_UIDS["he"]
        title = "עברית"
    else:
        target_uid = _MAIN_UIDS["en"]
        title = "English"
    return [{
        "type": "link",
        "title": title,
        "url": f"/d/{target_uid}",
        "targetBlank": False,
        "icon": "external link",
        "tags": [],
        "asDropdown": False,
        "includeVars": True,
        "keepTime": True,
    }]

_ROW_H = 1


def _section_header(title, y):
    """Thin markdown panel used as a visual section divider."""
    return mk_text(title, f"### {title}",
                   {"x": 0, "y": y, "w": _FULL_W, "h": _HDR_H})


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

def build_main_dashboard(lang: str = "en") -> dict:
    _reset_ids()
    panels = []
    y = 0
    own_uid = _MAIN_UIDS[lang]

    def t(s):
        return tr(s, lang)

    # ── ES CPU + KPI ─────────────────────────────────────────────────────
    panels.append(mk_cpu_panel({"x": 0, "y": y, "w": 18, "h": 6}, lang=lang))
    panels.append(mk_stat(t("Total Stress Score"), "stress.score", "sum",
                          {"x": 18, "y": y, "w": _QUARTER_W, "h": 6},
                          description=t("Sum of all stress scores in the selected time period.")))
    y += 6

    # ── Overview ────────────────────────────────────────────────────────
    panels.append(mk_text(t("Dashboard Guide"), cheat_sheet(lang),
                          {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
                          description=t("Quick reference guide for examining this dashboard.")))
    y += _PANEL_H

    # 5 pie charts — Cost Indicator pie uses raw (needs indicator names)
    for i, (field, label) in enumerate(SECTIONS[:3]):
        title = t("Stress by {label} (Selected Period)").format(label=t(label))
        panels.append(mk_pie(title, field,
                             {"x": i * _THIRD_W, "y": y, "w": _THIRD_W, "h": _PIE_H},
                             size=8, dashboard_uid=own_uid,
                             description=t(PANEL_DESCRIPTIONS["pie"][label])))
    y += _PIE_H
    panels.append(mk_pie(
        t("Stress by {label} (Selected Period)").format(label=t("Cost Indicator")),
        "stress.cost_indicator_names",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PIE_H}, size=10,
        dashboard_uid=own_uid,
        description=t(PANEL_DESCRIPTIONS["pie"]["Cost Indicator"])))
    panels.append(mk_pie(
        t("Stress by {label} (Selected Period)").format(label=t("Template")),
        "request.template",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PIE_H}, size=10,
        dashboard_uid=own_uid,
        description=t(PANEL_DESCRIPTIONS["pie"]["Template"])))
    y += _PIE_H

    # ── Highest Impact ──────────────────────────────────────────────────
    panels.append(_row(t("Highest Impact"), y))
    y += _ROW_H

    panels.append(mk_table(
        t("Top 10 Templates by Stress Score"), "request.template",
        t("Template"), [
            (t("Sum Stress Score"), "stress.score", "sum"),
            (t("Avg Stress Score"), "stress.score", "avg"),
            (t("P50 ES Latency (ms)"), "response.es_took_ms", "percentile_50"),
            (t("P95 ES Latency (ms)"), "response.es_took_ms", "percentile_95"),
            (t("P99 ES Latency (ms)"), "response.es_took_ms", "percentile_99"),
            (t("Avg Cost Indicators"), "stress.cost_indicator_count", "avg"),
            (t("Requests"), None, "count"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10,
        dashboard_uid=own_uid,
        description=t("Top 10 request templates ranked by total stress score, with "
                      "latency percentiles and cost-indicator averages.")))
    y += _PANEL_H

    panels.append(mk_raw_docs_table(
        t("Top 10 Heaviest Operations"), [
            ("@timestamp", t("Time")),
            ("request.body", t("Request Body")),
            ("request.operation", t("Operation")),
            ("request.target", t("Target")),
            ("request.path", t("Path")),
            ("stress.score", t("Stress")),
            ("response.es_took_ms", t("ES Latency (ms)")),
            ("stress.cost_indicator_names", t("Cost Indicators")),
        ],
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H + 2},
        size=50, sort_field="stress.score", dashboard_uid=own_uid,
        description=t("Individual requests with the highest stress scores in the "
                      "selected time range. Click column headers to re-sort.")))
    y += _PANEL_H + 2

    # Uses raw — needs cost_indicator_names as bucket
    panels.append(mk_table(
        t("Top 10 Cost Indicators by Stress Score"),
        "stress.cost_indicator_names", t("Cost Indicator"), [
            (t("Sum Stress"), "stress.score", "sum"),
            (t("Avg Stress"), "stress.score", "avg"),
            (t("P50 ES Latency (ms)"), "response.es_took_ms", "percentile_50"),
            (t("P95 ES Latency (ms)"), "response.es_took_ms", "percentile_95"),
            (t("P99 ES Latency (ms)"), "response.es_took_ms", "percentile_99"),
            (t("Requests"), None, "count"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10,
        dashboard_uid=own_uid,
        description=t("Cost indicator types ranked by total stress contribution, "
                      "with latency percentiles.")))
    y += _PANEL_H

    # ── Stress Trends ───────────────────────────────────────────────────
    panels.append(_row(t("Stress Trends"), y))
    y += _ROW_H

    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 5
        panels.append(mk_timeseries(
            t("Stress by {label}").format(label=t(label)), field,
            {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
            size=size, series_type="line", fill_opacity=20,
            description=t(PANEL_DESCRIPTIONS["ts"][label])))
        y += _PANEL_H

    # ── Volume & Throughput ─────────────────────────────────────────────
    panels.append(_row(t("Volume & Throughput"), y))
    y += _ROW_H

    panels.append(mk_timeseries(
        t("Request Volume"), None,
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field=None, metric_op="count",
        series_type="line", fill_opacity=20, summary_fallback=True,
        description=t("Total request count over time. Dashed series = hourly "
                      "summary-index fallback (survives raw-data ILM expiry).")))
    y += _PANEL_H

    panels.append(mk_timeseries(
        t("Documents Matched by Queries"), None,
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field="response.hits", metric_op="sum",
        series_type="line", fill_opacity=20,
        description=t("Total documents matched by queries. Correlates with ES "
                      "CPU under queue saturation.")))
    y += _PANEL_H

    panels.append(mk_timeseries(
        t("Write Volume (Documents)"), None,
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response.docs_affected", metric_op="sum",
        series_type="line", fill_opacity=20,
        description=t("Total documents written (index / bulk / update).")))
    panels.append(mk_timeseries(
        t("Request Size"), None,
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="request.size_bytes", metric_op="sum",
        series_type="line", fill_opacity=20, unit="decbytes",
        description=t("Total inbound request payload size.")))
    y += _PANEL_H

    # ── Response Times ────────────────────────────────────────────────
    panels.append(_row(t("Response Times"), y))
    y += _ROW_H

    panels.append(mk_timeseries_multi(t("ES Latency"), [
        (t("Avg"), "response.es_took_ms", "avg", ""),
        ("P50", "response.es_took_ms", "percentile_50", ""),
        ("P95", "response.es_took_ms", "percentile_95", ""),
        ("P99", "response.es_took_ms", "percentile_99", ""),
    ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", unit="ms",
        description=t("Elasticsearch response-time trend with Avg / P50 / P95 / "
                      "P99 — rising P95/P99 signals tail-latency issues.")))
    y += _PANEL_H

    return _wrap_dashboard(
        uid=own_uid,
        title=t("ALO — Stress Analysis"),
        description=t("Stress analysis by application, target, operation, and "
                      "template, with overall trend."),
        panels=panels,
        lang=lang,
        links=_main_dashboard_links(lang),
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
         "stress.cost_indicator_count:[1 TO *]",
         "Requests with at least one cost indicator firing."),
        ("Avg Indicator Count", "stress.cost_indicator_count", "avg", "",
         "Mean number of cost indicators per request."),
        ("Avg Stress Multiplier", "stress.multiplier", "avg", "",
         "Mean stress multiplier applied to base score."),
        ("Max Stress Multiplier", "stress.multiplier", "max", "",
         "Largest stress multiplier observed in the selected period."),
    ]
    for i, (title, field, op, query, desc) in enumerate(kpis):
        panels.append(mk_stat(title, field, op,
                              {"x": i * _QUARTER_W, "y": y, "w": _QUARTER_W,
                               "h": _KPI_H},
                              query=query, description=desc))
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
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _BAR_H},
        description="Stacked contribution of each base-score component (Took / "
                    "Shards / Hits / Bonus) per template — shows what drives the score."))
    y += _BAR_H

    # Base vs Final score + Multiplier breakdown
    panels.append(mk_table(
        "Base vs Final Score by Template", "request.template", "Template", [
            ("Requests", None, "count"),
            ("Avg Base", "stress.base", "avg"),
            ("Avg Multiplier", "stress.multiplier", "avg"),
            ("Avg Final Score", "stress.score", "avg"),
            ("Avg Indicators", "stress.cost_indicator_count", "avg"),
        ], {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H},
        description="Base score vs multiplier vs final score per template — "
                    "reveals whether stress is driven by the base or the multiplier."))
    panels.append(mk_table(
        "Top Templates by Cost Indicator Count",
        "request.template", "Template", [
            ("Avg Indicators", "stress.cost_indicator_count", "avg"),
            ("Avg Multiplier", "stress.multiplier", "avg"),
            ("Avg Stress", "stress.score", "avg"),
            ("Requests", None, "count"),
        ], {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H},
        description="Templates ranked by average cost indicator count — "
                    "query optimization candidates."))
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
            ("P50 ES Latency (ms)", "response.es_took_ms", "percentile_50"),
            ("P95 ES Latency (ms)", "response.es_took_ms", "percentile_95"),
            ("P99 ES Latency (ms)", "response.es_took_ms", "percentile_99"),
            ("Shards (weighted)", "stress.components.shards", "avg"),
            ("Shards (raw)", "response.shards_total", "avg"),
            ("Hits (weighted)", "stress.components.hits", "avg"),
            ("Hits (raw)", "response.hits", "avg"),
            ("Bonus", "stress.components.bonus", "avg"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _BAR_H},
        description="Full per-template breakdown: score, multiplier, weighted "
                    "components, and raw ES metrics (latency percentiles, shards, hits)."))
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
        series_type="line", stacked=True,
        description="Stacked trend of the four base-score components (Took, "
                    "Shards, Hits, Bonus) over time."))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Avg Base Score by Template", "request.template",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="stress.base", metric_op="avg", size=10,
        description="Average base stress score over time, per template."))
    panels.append(mk_timeseries(
        "Avg Multiplier by Template", "request.template",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="stress.multiplier", metric_op="avg", size=10,
        description="Average stress multiplier over time, per template."))
    y += _PANEL_H

    panels.append(mk_timeseries(
        "Avg Cost Indicators by Application",
        "identity.applicative_provider",
        {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        metric_field="stress.cost_indicator_count", metric_op="avg", size=8,
        description="Average number of cost indicators per request over time, "
                    "broken down by applicative provider."))
    y += _PANEL_H

    panels.append(mk_timeseries_multi(
        "Flagged vs Total Requests", [
            ("Flagged Requests", None, "count",
             "stress.cost_indicator_count:[1 TO *]"),
            ("Total Requests", None, "count", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line",
        description="Count of flagged (≥1 cost indicator) vs total requests — "
                    "the ratio indicates how many queries are suboptimal."))
    y += _PANEL_H

    # ── Cost Indicator Deep Dive ──────────────────────────────────────
    panels.append(_row("Cost Indicator Deep Dive", y))
    y += _ROW_H

    panels.append(mk_bar(
        "Cost Indicator Types - Frequency",
        "stress.cost_indicator_names", None, "count", "Count",
        {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H},
        description="How often each cost indicator type fires in the selected period."))
    panels.append(mk_bar(
        "Stress Multiplier by Application",
        "identity.applicative_provider", "stress.multiplier", "avg",
        "Avg Stress Multiplier",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8,
        description="Average stress multiplier per applicative provider."))
    y += _BAR_H

    panels.append(mk_bar(
        "Cost Indicator Count by Target Index",
        "request.target", "stress.cost_indicator_count", "avg",
        "Avg Indicator Count",
        {"x": 0, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8,
        description="Average cost indicators per request, per target index."))
    panels.append(mk_bar(
        "Stress Multiplier by Target Index",
        "request.target", "stress.multiplier", "avg",
        "Avg Multiplier",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _BAR_H}, size=8,
        description="Average stress multiplier per target index."))
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
        series_type="line",
        description="Average per-request counts of heavy clause types over time."))
    panels.append(mk_timeseries_multi(
        "Bool Clause Breakdown", [
            ("Avg must", "clause_counts.bool_must", "avg", ""),
            ("Avg should", "clause_counts.bool_should", "avg", ""),
            ("Avg filter", "clause_counts.bool_filter", "avg", ""),
            ("Avg must_not", "clause_counts.bool_must_not", "avg", ""),
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

    # ── Request Rates ───────────────────────────────────────────────────
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
        ("request.operation", "Operation"),
        ("identity.applicative_provider", "Application"),
        ("request.target", "Target Index"),
        ("request.template", "Template"),
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

    # ── Latency ─────────────────────────────────────────────────────────
    panels.append(_section_header("Latency", y))
    y += _HDR_H

    panels.append(mk_timeseries_multi("ES Latency", [
        ("Avg", "response.es_took_ms", "avg", ""),
        ("P50", "response.es_took_ms", "percentile_50", ""),
        ("P95", "response.es_took_ms", "percentile_95", ""),
        ("P99", "response.es_took_ms", "percentile_99", ""),
    ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", unit="ms",
        description="Elasticsearch response-time trend with Avg / P50 / P95 / "
                    "P99. Rising P95/P99 signals tail-latency issues."))
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
        series_type="line",
        description="Count of error responses (status ≥ 400) vs total requests."))
    panels.append(mk_table(
        "Requests by Status Code",
        "response.status", "Status Code", [
            ("Requests", None, "count"),
        ], {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H}, size=10,
        description="Top 10 response status codes by request count."))
    y += _PANEL_H

    panels.append(mk_table(
        "Requests by Application",
        "identity.applicative_provider", "Application", [
            ("Requests", None, "count"),
            ("P50 ES Latency (ms)", "response.es_took_ms", "percentile_50"),
            ("P95 ES Latency (ms)", "response.es_took_ms", "percentile_95"),
            ("P99 ES Latency (ms)", "response.es_took_ms", "percentile_99"),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H}, size=10,
        description="Per-application request counts and ES latency percentiles."))
    y += _PANEL_H

    # ── Data Volume ─────────────────────────────────────────────────────
    panels.append(_section_header("Data Volume", y))
    y += _HDR_H

    panels.append(mk_timeseries(
        "Read Volume (Total Hits)", "request.operation",
        {"x": 0, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response.hits", metric_op="sum", size=8,
        series_type="line", fill_opacity=20,
        description="Total documents matched by queries, split by operation type."))
    panels.append(mk_timeseries(
        "Write Volume (Docs Affected)", "request.operation",
        {"x": _HALF_W, "y": y, "w": _HALF_W, "h": _PANEL_H},
        metric_field="response.docs_affected", metric_op="sum", size=8,
        series_type="line", fill_opacity=20,
        description="Total documents written (indexed / updated / deleted), "
                    "split by operation type."))
    y += _PANEL_H

    panels.append(mk_timeseries_multi(
        "Payload Sizes", [
            ("Avg Request Size", "request.size_bytes", "avg", ""),
            ("Avg Response Size", "response.size_bytes", "avg", ""),
        ], {"x": 0, "y": y, "w": _FULL_W, "h": _PANEL_H},
        series_type="line", unit="decbytes",
        description="Average request and response payload sizes over time."))
    y += _PANEL_H

    # ── Top Activity ────────────────────────────────────────────────────
    panels.append(_section_header("Top Activity", y))
    y += _HDR_H

    panels.append(mk_bar(
        "Top 10 Applications",
        "identity.applicative_provider", None, "count", "Requests",
        {"x": 0, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10,
        description="Top 10 applicative providers by request count."))
    panels.append(mk_bar(
        "Top 10 Indices",
        "request.target", None, "count", "Requests",
        {"x": _THIRD_W, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10,
        description="Top 10 target indices by request count."))
    panels.append(mk_bar(
        "Top 10 Users",
        "identity.username", None, "count", "Requests",
        {"x": 2 * _THIRD_W, "y": y, "w": _THIRD_W, "h": _BAR_H}, size=10,
        description="Top 10 users by request count."))

    return _wrap_dashboard(
        uid="alo-usage",
        title="ALO — Cluster Usage",
        description="Request rates, latency percentiles, error tracking, "
                    "and data volume analytics.",
        panels=panels,
    )
