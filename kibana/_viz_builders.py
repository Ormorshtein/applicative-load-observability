"""Reusable Kibana Lens visualization builders.

Each mk_* function returns (vis_id, attrs_dict) for a Kibana saved object.
"""

import json

# Kibana Lens unit formats keyed by short name
_LENS_FORMATS: dict[str, dict] = {
    "ms":       {"id": "suffix", "params": {"suffix": " ms"}},
    "bytes":    {"id": "bytes", "params": {"decimals": 1}},
    "percent":  {"id": "percent", "params": {"decimals": 1}},
}


def _lens_metric_col(label: str, op: str, field: str,
                     unit: str = "") -> dict:
    """Build a Kibana Lens metric column with optional unit format."""
    col: dict = {
        "label": label, "customLabel": True, "dataType": "number",
        "operationType": op, "sourceField": field, "isBucketed": False,
    }
    if unit and unit in _LENS_FORMATS:
        col["params"] = {"format": _LENS_FORMATS[unit]}
    return col


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
                            "metrics": ["metric"],
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
                },
                "columnOrder": ["breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }
    if description:
        attrs["description"] = description
    return vis_id, attrs


def mk_ts(vis_id: str, title: str, field: str | None,
           metric_field: str = "stress.score", metric_label: str = "Avg Stress Score",
           metric_op: str = "average", size: int = 5,
           description: str = "", unit: str = "") -> tuple[str, dict]:
    columns = {
        "time": {"label": "@timestamp", "dataType": "date", "operationType": "date_histogram",
                 "sourceField": "@timestamp", "isBucketed": True, "params": {"interval": "auto"}},
        "metric": _lens_metric_col(metric_label, metric_op, metric_field, unit),
    }
    col_order = ["time", "metric"]
    layer = {"layerId": "layer1", "layerType": "data", "seriesType": "area",
             "xAccessor": "time", "accessors": ["metric"]}

    if field:
        columns["breakdown"] = {
            "label": field.split(".")[-1], "dataType": "string",
            "operationType": "terms", "sourceField": field, "isBucketed": True,
            "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                       "orderDirection": "desc", "otherBucket": False},
        }
        col_order = ["time", "breakdown", "metric"]
        layer["splitAccessor"] = "breakdown"

    attrs = {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": "area",
                "layers": [layer],
                "legend": {"isVisible": True, "position": "right"},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": True, "yRight": True},
                "yLeftExtent": {"mode": "dataBounds"},
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": columns,
                "columnOrder": col_order, "incompleteColumns": {},
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
                series_type: str = "line", unit: str = "") -> tuple[str, dict]:
    cols = {
        "time": {"label": "@timestamp", "dataType": "date", "operationType": "date_histogram",
                 "sourceField": "@timestamp", "isBucketed": True, "params": {"interval": "auto"}},
    }
    col_order = ["time"]
    accessors = []
    for col_id, label, field, op in metrics:
        c: dict = {"label": label, "dataType": "number", "operationType": op,
                   "sourceField": field, "isBucketed": False}
        if op == "count":
            c["sourceField"] = "___records___"
            if field:
                c["filter"] = {"language": "kuery", "query": field}
        elif op.startswith("percentile_"):
            pct = int(op.split("_")[1])
            c["operationType"] = "percentile"
            c["params"] = {"percentile": pct}
        if unit and unit in _LENS_FORMATS and "params" not in c:
            c["params"] = {"format": _LENS_FORMATS[unit]}
        elif unit and unit in _LENS_FORMATS and "params" in c:
            c["params"]["format"] = _LENS_FORMATS[unit]
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
        "bucket": {"label": bucket_label, "customLabel": True, "dataType": "string",
                   "operationType": "terms", "sourceField": bucket_field, "isBucketed": True,
                   "params": {"size": size, "orderBy": {"type": "column", "columnId": metrics[0][0]},
                              "orderDirection": "desc", "otherBucket": False}},
    }
    col_order = ["bucket"]
    vis_columns = [{"columnId": "bucket"}]
    for col_id, label, field, op in metrics:
        c: dict = {"label": label, "customLabel": True, "dataType": "number",
                   "operationType": op, "isBucketed": False}
        c["sourceField"] = "___records___" if op == "count" else field
        if op.startswith("percentile_"):
            pct = int(op.split("_")[1])
            c["operationType"] = "percentile"
            c["params"] = {"percentile": pct}
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
