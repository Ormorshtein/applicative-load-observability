"""Visualization specs for the three Kibana dashboards.

Each builder returns a list of (vis_id, attributes) tuples that are
upserted as Kibana Lens saved objects by _dashboards.do_rebuild().
"""

from _visualizations import (
    CHEAT_SHEET_MARKDOWN,
    PANEL_DESCRIPTIONS,
    SECTIONS,
    mk_ci_metric,
    mk_datatable,
    mk_horizontal_bar,
    mk_markdown,
    mk_metric,
    mk_pie,
    mk_ts,
    mk_ts_multi,
    mk_ts_response,
)


def _section_header(vis_id: str, title: str) -> tuple[str, dict]:
    """Thin markdown panel used as a visual section divider."""
    return mk_markdown(vis_id, title, f"### {title}")


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

def build_main_visualizations() -> list[tuple[str, dict]]:
    vis: list[tuple[str, dict]] = []

    # ── Section 1: Overview ────────────────────────────────────────────────
    vis.append(mk_markdown(
        "alo-cheat-sheet", "Dashboard Guide",
        CHEAT_SHEET_MARKDOWN,
        description="Quick reference guide for examining this dashboard."))

    vis.append(mk_metric(
        "alo-total-stress", "Total Stress Score",
        "stress.score", "sum",
        description="Sum of all stress scores in the selected time period."))

    for field, label in SECTIONS:
        if label == "Cost Indicator":
            vis.append(mk_pie(
                "alo-pie-cost-indicators", "Stress by Cost Indicator (Selected Period)",
                field, size=10, include_missing=True,
                description="Stress by cost indicator type. "
                "(missing) = requests with no cost indicators."))
            continue
        size = 10 if field == "request.template" else 8
        slug = label.lower().replace(" ", "-")
        vis.append(mk_pie(
            f"alo-pie-{slug}",
            f"Stress by {label} (Selected Period)",
            field, size=size,
            description=PANEL_DESCRIPTIONS["pie"][label]))

    # ── Section 2: Top Offenders ───────────────────────────────────────────
    vis.append(_section_header("alo-hdr-offenders", "Highest Impact"))

    vis.append(mk_datatable(
        "alo-table-top-templates", "Top 10 Templates by Stress Score",
        "request.template", "Template", [
            ("sum_stress",      "Sum Stress",              "stress.score",                "sum"),
            ("avg_stress",      "Avg Stress",              "stress.score",                "average"),
            ("avg_es_latency",  "Avg ES Latency (ms)",     "response.es_took_ms",         "average"),
            ("avg_gw_latency",  "Avg Gateway Latency (ms)", "response.gateway_took_ms",   "average"),
            ("cost_indicators", "Avg Cost Indicators",     "stress.cost_indicator_count",  "average"),
            ("requests",        "Requests",                None,                           "count"),
        ], size=10))

    vis.append(mk_datatable(
        "alo-table-top-indicators", "Top 10 Cost Indicators by Stress Score",
        "stress.cost_indicator_names", "Cost Indicator", [
            ("sum_stress",     "Sum Stress",              "stress.score",             "sum"),
            ("avg_stress",     "Avg Stress",              "stress.score",             "average"),
            ("avg_es_latency", "Avg ES Latency (ms)",     "response.es_took_ms",      "average"),
            ("requests",       "Requests",                None,                        "count"),
        ], size=10))

    # ── Stress Trends ─────────────────────────────────────────────────────
    vis.append(_section_header("alo-hdr-trends", "Stress Trends"))

    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 5
        slug = label.lower().replace(" ", "-")
        vis.append(mk_ts(
            f"alo-ts-{slug}",
            f"Stress by {label}",
            field, size=size,
            description=PANEL_DESCRIPTIONS["ts"][label]))

    # ── Volume & Throughput ───────────────────────────────────────────────
    vis.append(_section_header("alo-hdr-volume", "Volume & Throughput"))

    vis.append(mk_ts(
        "alo-ts-volume-template", "Request Volume by Template",
        "request.template",
        metric_field="___records___", metric_label="Requests",
        metric_op="count", size=10,
        description="Request count by template."))

    vis.append(mk_ts(
        "alo-ts-total-hits", "Documents Matched by Queries",
        "request.operation",
        metric_field="response.hits", metric_label="Documents Matched by Queries",
        metric_op="sum", size=8,
        description="Sum of response hits by operation."))

    vis.append(mk_ts(
        "alo-ts-docs-affected", "Write Volume (Documents)",
        "request.operation",
        metric_field="response.docs_affected", metric_label="Write Volume (Documents)",
        metric_op="sum", size=8,
        description="Sum of docs affected by operation."))

    vis.append(mk_ts(
        "alo-ts-request-size", "Request Size (Bytes)",
        "request.operation",
        metric_field="request.size_bytes", metric_label="Request Bytes",
        metric_op="sum", size=8,
        description="Sum of request payload size by operation."))

    # ── Response Times ──────────────────────────────────────────────────────
    vis.append(_section_header("alo-hdr-latency", "Response Times"))

    vis.append(mk_ts(
        "alo-resp-es-template", "Avg ES Latency (ms)",
        "request.template",
        metric_field="response.es_took_ms", metric_label="Avg ES Latency (ms)",
        metric_op="average", size=10))

    return vis


# ---------------------------------------------------------------------------
# Cost indicators dashboard
# ---------------------------------------------------------------------------

def build_ci_visualizations() -> list[tuple[str, dict]]:
    return [
        # ── KPIs ────────────────────────────────────────────────────────
        mk_ci_metric("alo-ci-kpi-flagged",   "Flagged Requests",
                      "stress.cost_indicator_count", "count",
                      "stress.cost_indicator_count >= 1"),
        mk_ci_metric("alo-ci-kpi-avg-flags",  "Avg Indicator Count",
                      "stress.cost_indicator_count", "average"),
        mk_ci_metric("alo-ci-kpi-avg-mult",   "Avg Stress Multiplier",
                      "stress.multiplier", "average"),
        mk_ci_metric("alo-ci-kpi-max-mult",   "Max Stress Multiplier",
                      "stress.multiplier", "max"),

        # ── Score Breakdown ─────────────────────────────────────────────
        _section_header("alo-ci-hdr-breakdown", "Score Breakdown"),

        mk_datatable("alo-ci-table-breakdown", "Score Breakdown by Template",
                     "request.template", "Template", [
                         ("count",          "Requests",          None,                       "count"),
                         ("avg_score",      "Avg Score",         "stress.score",             "average"),
                         ("avg_mult",       "Multiplier",        "stress.multiplier",        "average"),
                         ("avg_took_w",     "ES Took (weighted)", "stress.components.took",   "average"),
                         ("avg_took_raw",   "ES Latency (ms)",   "response.es_took_ms",      "average"),
                         ("avg_shards_w",   "Shards (weighted)", "stress.components.shards", "average"),
                         ("avg_shards_raw", "Shards (raw)",      "response.shards_total",    "average"),
                         ("avg_hits_w",     "Hits (weighted)",   "stress.components.hits",   "average"),
                         ("avg_hits_raw",   "Hits (raw)",        "response.hits",            "average"),
                         ("avg_bonus",      "Bonus",             "stress.components.bonus",  "average"),
                     ]),

        # ── Trends ──────────────────────────────────────────────────────
        _section_header("alo-ci-hdr-trends", "Trends"),

        mk_ts_multi("alo-ci-ts-components", "Score Components", [
            ("took",   "Avg Took",   "stress.components.took",   "average"),
            ("shards", "Avg Shards", "stress.components.shards", "average"),
            ("hits",   "Avg Hits",   "stress.components.hits",   "average"),
            ("bonus",  "Avg Bonus",  "stress.components.bonus",  "average"),
        ], "area_stacked"),

        mk_ts_multi("alo-ci-ts-flag-rate", "Flagged vs Total Requests", [
            ("flagged", "Flagged Requests", "stress.cost_indicator_count >= 1", "count"),
            ("total",   "Total Requests",   "",                                  "count"),
        ], "area"),

        # ── Cost Indicator Deep Dive ────────────────────────────────────
        _section_header("alo-ci-hdr-indicators", "Cost Indicator Deep Dive"),

        mk_horizontal_bar("alo-ci-bar-indicator-types",
                          "Cost Indicator Types - Frequency",
                          "stress.cost_indicator_names", None, "count", "Count"),
        mk_datatable("alo-ci-table-templates",
                     "Top Templates by Cost Indicator Count",
                     "request.template", "Template", [
                         ("avg_indicators", "Avg Indicators",
                          "stress.cost_indicator_count", "average"),
                         ("count",   "Requests",      None,                "count"),
                         ("avg_mult", "Avg Multiplier", "stress.multiplier", "average"),
                         ("avg_stress", "Avg Stress",  "stress.score",      "average"),
                     ]),
        mk_horizontal_bar("alo-ci-bar-apps", "Stress Multiplier by Application",
                          "identity.applicative_provider", "stress.multiplier",
                          "average", "Avg Stress Multiplier", 8),
        mk_horizontal_bar("alo-ci-bar-targets",
                          "Cost Indicator Count by Target Index",
                          "request.target", "stress.cost_indicator_count",
                          "average", "Avg Indicator Count", 8),

        # ── Clause Patterns ─────────────────────────────────────────────
        _section_header("alo-ci-hdr-clauses", "Clause Patterns"),

        mk_ts_multi("alo-ci-ts-clause-counts", "Clause Count Trends", [
            ("terms_avg",    "Avg terms_values", "clause_counts.terms_values", "average"),
            ("aggs_avg",     "Avg agg",          "clause_counts.agg",          "average"),
            ("script_avg",   "Avg script",       "clause_counts.script",       "average"),
            ("wildcard_avg", "Avg wildcard",     "clause_counts.wildcard",     "average"),
        ], "line"),
        mk_ts_multi("alo-ci-ts-bool", "Bool Clause Breakdown", [
            ("must",     "Avg must",     "clause_counts.bool_must",     "average"),
            ("should",   "Avg should",   "clause_counts.bool_should",   "average"),
            ("filter_c", "Avg filter",   "clause_counts.bool_filter",   "average"),
            ("must_not", "Avg must_not", "clause_counts.bool_must_not", "average"),
        ], "area_stacked"),
    ]


# ---------------------------------------------------------------------------
# Usage dashboard
# ---------------------------------------------------------------------------

def build_usage_visualizations() -> list[tuple[str, dict]]:
    return [
        # ── Rates ──────────────────────────────────────────────────────────
        _section_header("alo-usage-hdr-rates", "Request Rates"),

        mk_ts_multi("alo-usage-ts-total-rate", "Total Request Rate", [
            ("total", "Requests", "", "count"),
        ], "area"),

        mk_ts("alo-usage-ts-rate-by-op", "Rate by Operation",
               "request.operation",
               metric_field="___records___", metric_label="Requests",
               metric_op="count", size=8),

        mk_ts("alo-usage-ts-rate-by-app", "Rate by Application",
               "identity.applicative_provider",
               metric_field="___records___", metric_label="Requests",
               metric_op="count", size=8),

        mk_ts("alo-usage-ts-rate-by-index", "Rate by Target Index",
               "request.target",
               metric_field="___records___", metric_label="Requests",
               metric_op="count", size=8),

        # ── Latency ────────────────────────────────────────────────────────
        _section_header("alo-usage-hdr-latency", "Latency"),

        mk_ts_multi("alo-usage-ts-es-latency", "ES Latency", [
            ("min", "Min", "response.es_took_ms", "min"),
            ("avg", "Avg", "response.es_took_ms", "average"),
            ("p50", "P50", "response.es_took_ms", "percentile_50"),
            ("p75", "P75", "response.es_took_ms", "percentile_75"),
            ("p95", "P95", "response.es_took_ms", "percentile_95"),
            ("p99", "P99", "response.es_took_ms", "percentile_99"),
            ("max", "Max", "response.es_took_ms", "max"),
        ], "line"),

        mk_ts_multi("alo-usage-ts-gw-latency", "Gateway Latency", [
            ("min", "Min", "response.gateway_took_ms", "min"),
            ("avg", "Avg", "response.gateway_took_ms", "average"),
            ("p50", "P50", "response.gateway_took_ms", "percentile_50"),
            ("p75", "P75", "response.gateway_took_ms", "percentile_75"),
            ("p95", "P95", "response.gateway_took_ms", "percentile_95"),
            ("p99", "P99", "response.gateway_took_ms", "percentile_99"),
            ("max", "Max", "response.gateway_took_ms", "max"),
        ], "line"),

        mk_ts("alo-usage-ts-latency-by-op", "Avg ES Latency by Operation",
               "request.operation",
               metric_field="response.es_took_ms",
               metric_label="Avg ES Latency (ms)",
               metric_op="average", size=8),

        # ── Errors ─────────────────────────────────────────────────────────
        _section_header("alo-usage-hdr-errors", "Errors"),

        mk_ts_multi("alo-usage-ts-errors", "Error Rate", [
            ("errors", "Errors (4xx+5xx)", "response.status >= 400", "count"),
            ("total",  "Total Requests",   "",                       "count"),
        ], "area"),

        mk_horizontal_bar("alo-usage-bar-status", "Requests by Status Code",
                          "response.status", None, "count", "Count", 10),

        mk_datatable("alo-usage-table-errors-by-app", "Errors by Application",
                     "identity.applicative_provider", "Application", [
                         ("errors", "Errors", "response.status", "count"),
                         ("total",  "Total",  None,              "count"),
                     ], size=10),

        # ── Data Volume ────────────────────────────────────────────────────
        _section_header("alo-usage-hdr-volume", "Data Volume"),

        mk_ts("alo-usage-ts-hits", "Read Volume (Total Hits)",
               "request.operation",
               metric_field="response.hits", metric_label="Documents Matched by Queries",
               metric_op="sum", size=8),

        mk_ts("alo-usage-ts-docs", "Write Volume (Docs Affected)",
               "request.operation",
               metric_field="response.docs_affected",
               metric_label="Write Volume (Documents)",
               metric_op="sum", size=8),

        mk_ts_multi("alo-usage-ts-payload", "Payload Sizes", [
            ("req", "Avg Request Size", "request.size_bytes", "average"),
            ("resp", "Avg Response Size", "response.size_bytes", "average"),
        ], "line"),

        # ── Activity ───────────────────────────────────────────────────────
        _section_header("alo-usage-hdr-activity", "Top Activity"),

        mk_horizontal_bar("alo-usage-bar-apps", "Top 10 Applications",
                          "identity.applicative_provider", None,
                          "count", "Requests", 10),

        mk_horizontal_bar("alo-usage-bar-indices", "Top 10 Indices",
                          "request.target", None, "count", "Requests", 10),

        mk_horizontal_bar("alo-usage-bar-users", "Top 10 Users",
                          "identity.username", None, "count", "Requests", 10),
    ]


# ---------------------------------------------------------------------------
# Historical dashboard (summary index — flat field names)
# ---------------------------------------------------------------------------

def build_historical_visualizations() -> list[tuple[str, dict]]:
    """Visualizations for the historical dashboard.

    Uses the summary index fields (flat: avg_score, count, template)
    instead of nested raw fields (stress.score, request.template).
    """
    return [
        # ── Stress Trends ───────────────────────────────────────────────
        _section_header("alo-hist-hdr-stress", "Stress Trends"),

        mk_ts("alo-hist-ts-score-template", "Stress Score by Template",
               "template",
               metric_field="avg_score", metric_label="Avg Score",
               metric_op="average", size=10),

        mk_ts("alo-hist-ts-score-app", "Stress Score by Application",
               "applicative_provider",
               metric_field="avg_score", metric_label="Avg Score",
               metric_op="average", size=8),

        mk_ts("alo-hist-ts-score-target", "Stress Score by Target",
               "target",
               metric_field="avg_score", metric_label="Avg Score",
               metric_op="average", size=8),

        # ── Score Composition ───────────────────────────────────────────
        _section_header("alo-hist-hdr-composition", "Score Composition"),

        mk_ts("alo-hist-ts-base", "Avg Base Score by Template",
               "template",
               metric_field="avg_base", metric_label="Avg Base",
               metric_op="average", size=10),

        mk_ts("alo-hist-ts-mult", "Avg Multiplier by Template",
               "template",
               metric_field="avg_multiplier", metric_label="Avg Multiplier",
               metric_op="average", size=10),

        mk_ts("alo-hist-ts-ci-count", "Avg Cost Indicators by Application",
               "applicative_provider",
               metric_field="avg_cost_indicator_count",
               metric_label="Avg Indicators",
               metric_op="average", size=8),

        # ── Volume & Latency ───────────────────────────────────────────
        _section_header("alo-hist-hdr-volume", "Volume & Latency"),

        mk_ts("alo-hist-ts-volume-op", "Request Volume by Operation",
               "operation",
               metric_field="count", metric_label="Requests",
               metric_op="sum", size=8),

        mk_ts("alo-hist-ts-volume-app", "Request Volume by Application",
               "applicative_provider",
               metric_field="count", metric_label="Requests",
               metric_op="sum", size=8),

        mk_ts("alo-hist-ts-latency-es", "Avg ES Latency by Template",
               "template",
               metric_field="avg_es_took_ms", metric_label="Avg ES Latency (ms)",
               metric_op="average", size=10),

        mk_ts("alo-hist-ts-latency-gw", "Avg Gateway Latency by Template",
               "template",
               metric_field="avg_gateway_took_ms",
               metric_label="Avg Gateway Latency (ms)",
               metric_op="average", size=10),

        # ── Top Offenders ──────────────────────────────────────────────
        _section_header("alo-hist-hdr-top", "Top Offenders (All Time)"),

        mk_datatable("alo-hist-table-templates",
                     "Top Templates by Cumulative Stress",
                     "template", "Template", [
                         ("sum_stress", "Total Stress", "sum_score", "sum"),
                         ("avg_stress", "Avg Score",    "avg_score", "average"),
                         ("total_reqs", "Total Requests", "count",  "sum"),
                         ("avg_lat",    "Avg Latency (ms)", "avg_es_took_ms", "average"),
                         ("avg_mult",   "Avg Multiplier", "avg_multiplier", "average"),
                     ]),

        mk_datatable("alo-hist-table-apps",
                     "Top Applications by Cumulative Stress",
                     "applicative_provider", "Application", [
                         ("sum_stress", "Total Stress", "sum_score", "sum"),
                         ("avg_stress", "Avg Score",    "avg_score", "average"),
                         ("total_reqs", "Total Requests", "count",  "sum"),
                         ("avg_lat",    "Avg Latency (ms)", "avg_es_took_ms", "average"),
                     ]),
    ]
