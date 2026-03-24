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

1. **Start with the top row** — pie charts show which application, target, \
operation, or template contributes the most stress; the overall trend shows \
whether stress is rising or falling.
2. **Check the time series** — look for spikes or trends in stress over time. \
Correlate with deployments or traffic changes.
3. **Review the Top 10 Templates table** — focus on templates with the highest \
sum stress and cost indicator counts.
4. **Inspect the Top 10 Heaviest Operations** — use filters to narrow down, then \
examine the actual request bodies of the most resource-intensive individual requests.
5. **Examine response times** — high ES or gateway latency alongside high stress \
may indicate query optimization opportunities.
6. **Sanity check tables** — verify if the most recurring templates are also the \
most stressful; templates with many cost indicators need attention.

**What to focus on:**
- **High stress slices** in pie charts — these are your optimization targets
- **Upward trends** in time series — indicates growing load or degrading patterns
- **Templates with many cost indicators** — likely candidates for query optimization
- **Latency spikes** correlating with specific operations or templates
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
           size: int = 8,
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
                                             "orderDirection": "desc", "otherBucket": False}},
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
    Layout structure:

    Row 0 (y=0, h=10):    Cheat sheet (w=36) + Total Stress Score metric (w=12)
    Row 1 (y=10, h=10):   5 pie charts — Application, Target, Operation, Cost Indicator, Template
    Row 2-6 (h=12 each):  5 stress-over-time charts, same order as pies
    Row 7 (h=12):          Request Volume Over Time (w=24) + by Template (w=24)
    Row 8 (h=12):          Total Hits Over Time
    Row 9 (h=12):          Docs Affected Over Time (w=24) + Request Size Over Time (w=24)
    Row 10 (h=14):         Top 10 Templates by Stress Score table
    Row 11 (h=16):         Top 10 Heaviest Operations (saved search)
    Row 12 (h=14):         Top 10 Cost Indicators by Stress Score table
    Row 13-14 (h=12 each): Avg ES/Gateway Response Time — by Cost Indicator, Operation, Template
    Row 15 (h=12):         Sanity check tables — most recurring templates, most cost indicators

    Vis indices: 0=cheat, 1=metric, 2-6=pies, 7-11=ts, 12=volume-op,
    13=volume-template, 14=hits, 15=docs, 16=reqsize, 17=top-templates,
    18=top-indicators, 19-21=es-resp, 22-24=gw-resp, 25=recurring,
    26=cost-ind-table, saved-search=27
    """
    y = 0

    # --- Row 0: Cheat sheet + Total Stress Score (indices 0-1) ---
    _add_panel(panels, refs, vis_ids[0], 0, y, 36, 10, panel_type="visualization")
    _add_panel(panels, refs, vis_ids[1], 36, y, 12, 10)
    y += 10

    # --- Row 1: 5 pie charts (indices 2-6) ---
    pie_w = 48 // 5
    for i in range(5):
        vid = vis_ids[2 + i]
        w = pie_w if i < 4 else 48 - pie_w * 4
        _add_panel(panels, refs, vid, i * pie_w, y, w, 10)
    y += 10

    # --- Rows 2-6: 5 stress-over-time charts (indices 7-11) ---
    for i in range(5):
        _add_panel(panels, refs, vis_ids[7 + i], 0, y, 48, 12)
        y += 12

    # --- Row 7: Request Volume side by side (indices 12-13) ---
    _add_panel(panels, refs, vis_ids[12], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[13], 24, y, 24, 12)
    y += 12

    # --- Row 8: Total Hits Over Time (index 14) ---
    _add_panel(panels, refs, vis_ids[14], 0, y, 48, 12)
    y += 12

    # --- Row 9: Docs Affected + Request Size side by side (indices 15-16) ---
    _add_panel(panels, refs, vis_ids[15], 0, y, 24, 12)
    _add_panel(panels, refs, vis_ids[16], 24, y, 24, 12)
    y += 12

    # --- Row 10: Top Templates by Stress Score table (index 17) ---
    _add_panel(panels, refs, vis_ids[17], 0, y, 48, 14)
    y += 14

    # --- Row 11: Top 10 Heaviest Operations (index 27, saved search) ---
    _add_panel(panels, refs, vis_ids[27], 0, y, 48, 16, panel_type="search")
    y += 16

    # --- Row 12: Top Cost Indicators by Stress Score table (index 18) ---
    _add_panel(panels, refs, vis_ids[18], 0, y, 48, 14)
    y += 14

    # --- Rows 13-14: Response time panels (indices 19-24), 3 per row ---
    for row_start in (19, 22):
        for j in range(3):
            _add_panel(panels, refs, vis_ids[row_start + j], j * 16, y, 16, 12)
        y += 12

    # --- Row 15: 2 sanity check tables (indices 25-26) ---
    for j in range(2):
        _add_panel(panels, refs, vis_ids[25 + j], j * 24, y, 24, 12)


def layout_cost_indicators(vis_ids: list[str], panels: list[dict],
                           refs: list[dict]) -> None:
    grid = [
        # Row 0: KPIs (h=6)
        (vis_ids[0],  0,  0, 12, 6),
        (vis_ids[1], 12,  0, 12, 6),
        (vis_ids[2], 24,  0, 12, 6),
        (vis_ids[3], 36,  0, 12, 6),
        # Row 1: Indicator overview (h=14)
        (vis_ids[4],  0,  6, 20, 14),
        (vis_ids[5], 20,  6, 28, 14),
        # Row 2: Clause counts (h=14)
        (vis_ids[6],  0, 20, 28, 14),
        (vis_ids[7], 28, 20, 20, 14),
        # Row 3: Table (h=12)
        (vis_ids[8],  0, 34, 48, 12),
        # Row 4: By dimension (h=14)
        (vis_ids[9],   0, 46, 24, 14),
        (vis_ids[10], 24, 46, 24, 14),
    ]
    for vid, x, y, w, h in grid:
        panels.append({"panelIndex": vid, "gridData": {"x": x, "y": y, "w": w, "h": h, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
