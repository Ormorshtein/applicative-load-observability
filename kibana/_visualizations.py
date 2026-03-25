"""
Kibana Lens visualization builders and dashboard layout functions.

Each mk_* function returns (vis_id, attrs_dict) for a Kibana saved object.
Layout functions arrange visualization panels on a dashboard grid.
"""

import json

# Ordered per dashboard layout: Application -> Target -> Operation -> Cost Indicator -> Template
SECTIONS = [
    ("identity.applicative_provider", "Application"),
    ("request.target",                "Target"),
    ("request.operation",             "Operation"),
    ("stress.cost_indicator_names",   "Cost Indicator"),
    ("request.template",              "Template"),
]

# Panel descriptions for hover notes (item 3)
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

CHEAT_SHEET_MARKDOWN = """\
## Dashboard Cheat Sheet

**How to examine this dashboard:**

1. **Start with the overview** — pie charts show which application, target, \
operation, or template contributes the most stress.
2. **Check Highest Impact** — the Top 10 Templates and Heaviest Operations \
tables show exactly what to fix. Focus on templates with high sum stress \
and cost indicator counts.
3. **Look at trends** — stress over time charts reveal spikes and patterns. \
Correlate with deployments or traffic changes.
4. **Review volume & throughput** — request volume, total hits, docs affected, \
and request size panels show operational load. Total hits correlates with CPU.
5. **Examine response times** — high ES or gateway latency alongside high stress \
may indicate query optimization opportunities.
6. **Sanity checks** — verify if the most recurring templates are also the \
most stressful; templates with many cost indicators need attention.

**What to focus on:**
- **High stress slices** in pie charts — optimization targets
- **Upward trends** in time series — growing load or degrading patterns
- **Templates with many cost indicators** — query optimization candidates
- **Latency spikes** correlating with specific operations or templates
- **Total hits spikes** — correlate with CPU usage under queue saturation
"""


# ---------------------------------------------------------------------------
# Visualization builders
# ---------------------------------------------------------------------------

def mk_metric(vis_id: str, title: str, source_field: str,
              operation: str,
              description: str = "") -> tuple[str, dict]:
    col = {"label": title, "dataType": "number", "operationType": operation, "isBucketed": False}
    col["sourceField"] = "___records___" if operation == "count" else source_field
    attrs = {
        "title": title, "visualizationType": "lnsMetric",
        "state": {
            "visualization": {"layerId": "layer1", "layerType": "data", "metricAccessor": "metric"},
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {"metric": col}, "columnOrder": ["metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }
    if description:
        attrs["description"] = description
    return vis_id, attrs


def mk_markdown(vis_id: str, title: str, content: str,
                description: str = "") -> tuple[str, dict]:
    attrs = {
        "title": title,
        "visState": json.dumps({
            "title": title,
            "type": "markdown",
            "aggs": [],
            "params": {
                "fontSize": 12,
                "openLinksInNewTab": False,
                "markdown": content,
            },
        }),
        "uiStateJSON": "{}",
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps(
                {"query": {"query": "", "language": "kuery"}, "filter": []}),
        },
    }
    if description:
        attrs["description"] = description
    return vis_id, attrs


def mk_pie(vis_id: str, title: str, field: str,
           size: int = 8, include_missing: bool = False,
           description: str = "") -> tuple[str, dict]:
    attrs = {
        "title": title, "visualizationType": "lnsPie",
        "state": {
            "visualization": {
                "shape": "donut",
                "layers": [{"layerId": "layer1", "layerType": "data",
                            "primaryGroups": ["breakdown"],
                            "metrics": ["metric", "request_count"],
                            "numberDisplay": "percent", "categoryDisplay": "default",
                            "legendDisplay": "default", "legendPosition": "right"}],
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {
                    "breakdown": {"label": field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": False,
                                             "missingBucket": include_missing}},
                    "metric": {"label": "Total Stress", "dataType": "number",
                               "operationType": "sum", "sourceField": "stress.score", "isBucketed": False},
                    "request_count": {"label": "Requests", "dataType": "number",
                                      "operationType": "count", "sourceField": "___records___",
                                      "isBucketed": False},
                },
                "columnOrder": ["breakdown", "metric", "request_count"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }
    if description:
        attrs["description"] = description
    return vis_id, attrs


def mk_pie_filters(
    vis_id: str, title: str,
    filters: list[tuple[str, str]],
    description: str = "",
) -> tuple[str, dict]:
    """Pie chart with explicit KQL filters as slices.

    *filters* is a list of (label, kql_query) tuples — one slice per filter.
    Metric is sum of stress.score.
    """
    columns = {}
    column_order = []
    for i, (label, kql) in enumerate(filters):
        col_id = f"filter_{i}"
        columns[col_id] = {
            "label": label, "dataType": "string",
            "operationType": "filters", "isBucketed": True,
            "params": {"filters": [{"label": label, "input": {"query": kql, "language": "kuery"}}]},
        } if i == 0 else None

    # Lens filters column: single column with all filters
    filter_params = [{"label": label, "input": {"query": kql, "language": "kuery"}}
                     for label, kql in filters]
    columns = {
        "breakdown": {
            "label": "Segment", "dataType": "string",
            "operationType": "filters", "isBucketed": True,
            "params": {"filters": filter_params},
        },
        "metric": {
            "label": "Total Stress", "dataType": "number",
            "operationType": "sum", "sourceField": "stress.score", "isBucketed": False,
        },
    }
    attrs = {
        "title": title, "visualizationType": "lnsPie",
        "state": {
            "visualization": {
                "shape": "donut",
                "layers": [{"layerId": "layer1", "layerType": "data",
                            "primaryGroups": ["breakdown"],
                            "metrics": ["metric"],
                            "numberDisplay": "percent", "categoryDisplay": "default",
                            "legendDisplay": "default", "legendPosition": "right"}],
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": columns,
                "columnOrder": ["breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }
    if description:
        attrs["description"] = description
    return vis_id, attrs


def mk_ts(vis_id: str, title: str, field: str,
           metric_field: str = "stress.score", metric_label: str = "Avg Stress Score",
           metric_op: str = "average", size: int = 5,
           description: str = "") -> tuple[str, dict]:
    attrs = {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": "area",
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": "area",
                            "xAccessor": "time", "accessors": ["metric"], "splitAccessor": "breakdown"}],
                "legend": {"isVisible": True, "position": "right"},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": True, "yRight": True},
                "yLeftExtent": {"mode": "dataBounds"},
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {
                    "time": {"label": "@timestamp", "dataType": "date", "operationType": "date_histogram",
                             "sourceField": "@timestamp", "isBucketed": True, "params": {"interval": "auto"}},
                    "breakdown": {"label": field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": False}},
                    "metric": {"label": metric_label, "dataType": "number",
                               "operationType": metric_op, "sourceField": metric_field, "isBucketed": False},
                },
                "columnOrder": ["time", "breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }
    if description:
        attrs["description"] = description
    return vis_id, attrs


def mk_ts_response(vis_id: str, title: str, breakdown_field: str,
                   latency_field: str, latency_label: str,
                   size: int = 5,
                   description: str = "") -> tuple[str, dict]:
    attrs = {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": "line",
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": "line",
                            "xAccessor": "time", "accessors": ["latency", "count"], "splitAccessor": "breakdown"}],
                "legend": {"isVisible": True, "position": "right"},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": True, "yRight": True},
                "yLeftExtent": {"mode": "dataBounds"},
                "yRightExtent": {"mode": "dataBounds"},
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {
                    "time": {"label": "@timestamp", "dataType": "date", "operationType": "date_histogram",
                             "sourceField": "@timestamp", "isBucketed": True, "params": {"interval": "auto"}},
                    "breakdown": {"label": breakdown_field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": breakdown_field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "latency"},
                                             "orderDirection": "desc", "otherBucket": False}},
                    "latency": {"label": latency_label, "dataType": "number",
                                "operationType": "average", "sourceField": latency_field, "isBucketed": False},
                    "count": {"label": "Requests", "dataType": "number",
                              "operationType": "count", "sourceField": "___records___", "isBucketed": False},
                },
                "columnOrder": ["time", "breakdown", "latency", "count"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }
    if description:
        attrs["description"] = description
    return vis_id, attrs


def mk_ci_metric(vis_id: str, title: str, source_field: str,
                 operation: str,
                 kql_filter: str | None = None) -> tuple[str, dict]:
    col = {"label": title, "dataType": "number", "operationType": operation, "isBucketed": False}
    col["sourceField"] = "___records___" if operation == "count" else source_field
    if kql_filter:
        col["filter"] = {"language": "kuery", "query": kql_filter}
    return vis_id, {
        "title": title, "visualizationType": "lnsMetric",
        "state": {
            "visualization": {"layerId": "layer1", "layerType": "data", "metricAccessor": "metric"},
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {"metric": col}, "columnOrder": ["metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_horizontal_bar(vis_id: str, title: str, field: str,
                      metric_field: str | None, metric_op: str,
                      metric_label: str, size: int = 10) -> tuple[str, dict]:
    cols = {
        "breakdown": {"label": field.split(".")[-1], "dataType": "string",
                      "operationType": "terms", "sourceField": field, "isBucketed": True,
                      "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                 "orderDirection": "desc", "otherBucket": False}},
        "metric": {"label": metric_label, "dataType": "number",
                   "operationType": metric_op, "isBucketed": False},
    }
    cols["metric"]["sourceField"] = "___records___" if metric_op == "count" else metric_field
    return vis_id, {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": "bar_horizontal",
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": "bar_horizontal",
                            "xAccessor": "breakdown", "accessors": ["metric"]}],
                "legend": {"isVisible": False},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": False, "yRight": False},
                "valueLabels": "show",
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": cols, "columnOrder": ["breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ts_multi(vis_id: str, title: str, metrics: list[tuple],
                series_type: str = "line") -> tuple[str, dict]:
    cols = {
        "time": {"label": "@timestamp", "dataType": "date", "operationType": "date_histogram",
                 "sourceField": "@timestamp", "isBucketed": True, "params": {"interval": "auto"}},
    }
    col_order = ["time"]
    accessors = []
    for col_id, label, field, op in metrics:
        c = {"label": label, "dataType": "number", "operationType": op, "sourceField": field, "isBucketed": False}
        if op == "count":
            c["sourceField"] = "___records___"
            if field:
                c["filter"] = {"language": "kuery", "query": field}
        cols[col_id] = c
        col_order.append(col_id)
        accessors.append(col_id)
    return vis_id, {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": series_type,
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": series_type,
                            "xAccessor": "time", "accessors": accessors}],
                "legend": {"isVisible": True, "position": "right"},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": True, "yRight": True},
                "yLeftExtent": {"mode": "dataBounds"},
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": cols, "columnOrder": col_order, "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_datatable(vis_id: str, title: str, bucket_field: str,
                 bucket_label: str, metrics: list[tuple],
                 size: int = 10) -> tuple[str, dict]:
    cols = {
        "bucket": {"label": bucket_label, "dataType": "string",
                   "operationType": "terms", "sourceField": bucket_field, "isBucketed": True,
                   "params": {"size": size, "orderBy": {"type": "column", "columnId": metrics[0][0]},
                              "orderDirection": "desc", "otherBucket": False}},
    }
    col_order = ["bucket"]
    vis_columns = [{"columnId": "bucket"}]
    for col_id, label, field, op in metrics:
        c = {"label": label, "dataType": "number", "operationType": op, "isBucketed": False}
        c["sourceField"] = "___records___" if op == "count" else field
        cols[col_id] = c
        col_order.append(col_id)
        vis_columns.append({"columnId": col_id})
    return vis_id, {
        "title": title, "visualizationType": "lnsDatatable",
        "state": {
            "visualization": {"columns": vis_columns, "layerId": "layer1", "layerType": "data"},
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": cols, "columnOrder": col_order, "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


# ---------------------------------------------------------------------------
# Dashboard layout functions
# ---------------------------------------------------------------------------

def _add_panel(panels: list[dict], refs: list[dict], vid: str,
               x: int, y: int, w: int, h: int,
               panel_type: str = "lens") -> None:
    panels.append({"panelIndex": vid,
                   "gridData": {"x": x, "y": y, "w": w, "h": h, "i": vid},
                   "type": panel_type, "panelRefName": f"panel_{vid}"})
    refs.append({"type": panel_type, "id": vid, "name": f"panel_{vid}"})


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

    pie_w = 48 // 5
    for i in range(5):
        vid = vis_ids[2 + i]
        w = pie_w if i < 4 else 48 - pie_w * 4
        _add_panel(panels, refs, vid, i * pie_w, y, w, 10)
    y += 10

    # ── Section 2: Highest Impact ──────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[7], 0, y, 48, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[8], 0, y, 48, 14)
    y += 14

    _add_panel(panels, refs, vis_ids[32], 0, y, 48, 16, panel_type="search")
    y += 16

    _add_panel(panels, refs, vis_ids[9], 0, y, 48, 14)
    y += 14

    # ── Section 3: Stress Trends ───────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[10], 0, y, 48, HDR_H, panel_type="visualization")
    y += HDR_H

    for i in range(5):
        _add_panel(panels, refs, vis_ids[11 + i], 0, y, 48, 12)
        y += 12

    # ── Section 4: Volume & Throughput ─────────────────────────────────────
    _add_panel(panels, refs, vis_ids[16], 0, y, 48, HDR_H, panel_type="visualization")
    y += HDR_H

    _add_panel(panels, refs, vis_ids[17], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[18], 24, y, 24, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[19], 0, y, 48, 12)
    y += 12

    _add_panel(panels, refs, vis_ids[20], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[21], 24, y, 24, 12)
    y += 12

    # ── Section 5: Response Times ──────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[22], 0, y, 48, HDR_H, panel_type="visualization")
    y += HDR_H

    for row_start in (23, 26):
        for j in range(3):
            _add_panel(panels, refs, vis_ids[row_start + j], j * 16, y, 16, 12)
        y += 12

    # ── Section 6: Sanity Checks ───────────────────────────────────────────
    _add_panel(panels, refs, vis_ids[29], 0, y, 48, HDR_H, panel_type="visualization")
    y += HDR_H

    for j in range(2):
        _add_panel(panels, refs, vis_ids[30 + j], j * 24, y, 24, 12)


def layout_cost_indicators(vis_ids: list[str], panels: list[dict],
                           refs: list[dict]) -> None:
    grid = [
        # Row 0: KPIs (h=6)
        (vis_ids[0],  0,  0, 12, 6),
        (vis_ids[1], 12,  0, 12, 6),
        (vis_ids[2], 24,  0, 12, 6),
        (vis_ids[3], 36,  0, 12, 6),
        # Row 1: Score breakdown table (h=14)
        (vis_ids[4],  0,  6, 48, 14),
        # Row 2: Component trends (h=14)
        (vis_ids[5],  0, 20, 48, 14),
        # Row 3: Indicator overview (h=14)
        (vis_ids[6],  0, 34, 20, 14),
        (vis_ids[7], 20, 34, 28, 14),
        # Row 4: Clause counts (h=14)
        (vis_ids[8],  0, 48, 28, 14),
        (vis_ids[9], 28, 48, 20, 14),
        # Row 5: Table (h=12)
        (vis_ids[10], 0, 62, 48, 12),
        # Row 6: By dimension (h=14)
        (vis_ids[11],  0, 74, 24, 14),
        (vis_ids[12], 24, 74, 24, 14),
    ]
    for vid, x, y, w, h in grid:
        panels.append({"panelIndex": vid, "gridData": {"x": x, "y": y, "w": w, "h": h, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
