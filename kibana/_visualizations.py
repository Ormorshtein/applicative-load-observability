"""
Kibana Lens visualization builders and dashboard layout functions.

Each mk_* function returns (vis_id, attrs_dict) for a Kibana saved object.
Layout functions arrange visualization panels on a dashboard grid.
"""

# Ordered per dashboard layout: Application -> Target -> Operation -> Cost Indicator -> Template
SECTIONS = [
    ("identity.applicative_provider", "Application"),
    ("request.target",                "Target"),
    ("request.operation",             "Operation"),
    ("stress.cost_indicator_names",   "Cost Indicator"),
    ("request.template",              "Template"),
]


# ---------------------------------------------------------------------------
# Visualization builders
# ---------------------------------------------------------------------------

def mk_metric(vis_id: str, title: str, source_field: str,
              operation: str) -> tuple[str, dict]:
    col = {"label": title, "dataType": "number", "operationType": operation, "isBucketed": False}
    col["sourceField"] = "___records___" if operation == "count" else source_field
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


def mk_pie(vis_id: str, title: str, field: str,
           size: int = 8) -> tuple[str, dict]:
    return vis_id, {
        "title": title, "visualizationType": "lnsPie",
        "state": {
            "visualization": {
                "shape": "donut",
                "layers": [{"layerId": "layer1", "layerType": "data",
                            "primaryGroups": ["breakdown"], "metrics": ["metric"],
                            "numberDisplay": "percent", "categoryDisplay": "default",
                            "legendDisplay": "default", "legendPosition": "right"}],
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {
                    "breakdown": {"label": field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": True}},
                    "metric": {"label": "Total Stress", "dataType": "number",
                               "operationType": "sum", "sourceField": "stress.score", "isBucketed": False},
                },
                "columnOrder": ["breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ts(vis_id: str, title: str, field: str,
           metric_field: str = "stress.score", metric_label: str = "Avg Stress Score",
           metric_op: str = "average", size: int = 5) -> tuple[str, dict]:
    return vis_id, {
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
                    "time": {"label": "timestamp", "dataType": "date", "operationType": "date_histogram",
                             "sourceField": "timestamp", "isBucketed": True, "params": {"interval": "auto"}},
                    "breakdown": {"label": field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": True}},
                    "metric": {"label": metric_label, "dataType": "number",
                               "operationType": metric_op, "sourceField": metric_field, "isBucketed": False},
                },
                "columnOrder": ["time", "breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ts_response(vis_id: str, title: str, breakdown_field: str,
                   latency_field: str, latency_label: str,
                   size: int = 5) -> tuple[str, dict]:
    return vis_id, {
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
                    "time": {"label": "timestamp", "dataType": "date", "operationType": "date_histogram",
                             "sourceField": "timestamp", "isBucketed": True, "params": {"interval": "auto"}},
                    "breakdown": {"label": breakdown_field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": breakdown_field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "latency"},
                                             "orderDirection": "desc", "otherBucket": True}},
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
        "time": {"label": "timestamp", "dataType": "date", "operationType": "date_histogram",
                 "sourceField": "timestamp", "isBucketed": True, "params": {"interval": "auto"}},
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

def layout_main(vis_ids: list[str], panels: list[dict],
                refs: list[dict]) -> None:
    """
    Layout structure (mapped to improvement notes):

    Row 0 (y=0, h=10):   5 pie charts — Application, Target, Operation, Cost Indicator, Template
    Row 1-5 (h=12 each): 5 stress-over-time charts, same order as pies
    Row 6 (h=14):         Top 10 Templates by Stress Score table
    Row 7-8 (h=12 each): Avg ES/Gateway Response Time — by Cost Indicator, Operation, Template
    Row 9 (h=12):         Sanity check tables — most recurring templates, most cost indicators
    """
    y = 0

    # --- Row 0: 5 pie charts (indices 0-4) ---
    pie_w = 48 // 5
    for i in range(5):
        vid = vis_ids[i]
        w = pie_w if i < 4 else 48 - pie_w * 4
        panels.append({"panelIndex": vid, "gridData": {"x": i * pie_w, "y": y, "w": w, "h": 10, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
    y += 10

    # --- Rows 1-5: 5 stress-over-time charts (indices 5-9) ---
    for i in range(5):
        vid = vis_ids[5 + i]
        panels.append({"panelIndex": vid, "gridData": {"x": 0, "y": y, "w": 48, "h": 12, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
        y += 12

    # --- Row 6: Top Templates by Stress Score table (index 10) ---
    vid = vis_ids[10]
    panels.append({"panelIndex": vid, "gridData": {"x": 0, "y": y, "w": 48, "h": 14, "i": vid},
                   "type": "lens", "panelRefName": f"panel_{vid}"})
    refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
    y += 14

    # --- Rows 7-8: Response time panels (indices 11-16), 3 per row ---
    for row_start in (11, 14):
        for j in range(3):
            vid = vis_ids[row_start + j]
            panels.append({"panelIndex": vid, "gridData": {"x": j * 16, "y": y, "w": 16, "h": 12, "i": vid},
                           "type": "lens", "panelRefName": f"panel_{vid}"})
            refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
        y += 12

    # --- Row 9: 2 sanity check tables (indices 17-18) ---
    for j in range(2):
        vid = vis_ids[17 + j]
        panels.append({"panelIndex": vid, "gridData": {"x": j * 24, "y": y, "w": 24, "h": 12, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})


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
