"""
Elasticsearch data stream resources for ALO.

Defines a shared component template (mappings), three ILM policies
(search / write / default), and three composable index templates that
route each operation category to the correct lifecycle.

Long-term retention
~~~~~~~~~~~~~~~~~~~
A continuous ES transform aggregates raw data into ``alo-summary`` with
hourly buckets grouped by template / operation / app / target / cluster.
The summary index uses the **same nested field paths** as the raw indices
(``stress.score``, ``response.es_took_ms``, ``request.template``, …) so
that dashboard panels work against both without modification.

Dashboards query a combined index pattern (``logs-alo.*-*,alo-summary``).
While raw data exists it vastly outnumbers summary docs (~1 000 raw vs
~20 summary per hour), so the summary's contribution is <2 % noise on
aggregations — invisible on charts and preserving rankings in tables.
After ILM deletes raw indices (3 days) the summary docs seamlessly take
over, providing avg metrics and p50/p95/p99 percentiles at hourly
granularity for up to 120 days.  The transform's ``retention_policy``
automatically deletes summary docs older than 120 days (rolling, not
bulk — unlike ILM on a regular index which would drop the entire index).
"""

# ── Component template (shared mappings + settings) ─────────────────────────

COMPONENT_TEMPLATE: dict = {
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "5s",
            "index.lifecycle.parse_origination_date": True,
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "@timestamp": {"type": "date"},
                "identity": {
                    "properties": {
                        "username":             {"type": "keyword"},
                        "applicative_provider": {"type": "keyword"},
                        "user_agent":           {"type": "keyword"},
                        "client_host":          {"type": "keyword"},
                        "labels":               {"type": "flattened"},
                    }
                },
                "request": {
                    "properties": {
                        "method":     {"type": "keyword"},
                        "path":       {"type": "keyword"},
                        "operation":  {"type": "keyword"},
                        "target":     {"type": "keyword"},
                        "template":   {"type": "keyword"},
                        "body":       {"type": "keyword", "doc_values": False},
                        "size_bytes": {"type": "integer"},
                        "size":       {"type": "integer"},
                        "geo_vertex_count": {"type": "integer"},
                    }
                },
                "response": {
                    "properties": {
                        "status":          {"type": "short"},
                        "es_took_ms":      {"type": "float"},
                        "gateway_took_ms": {"type": "float"},
                        "hits":            {"type": "long"},
                        "shards_total":    {"type": "integer"},
                        "docs_affected":   {"type": "long"},
                        "size_bytes":      {"type": "integer"},
                    }
                },
                "clause_counts": {
                    "properties": {
                        "bool":            {"type": "integer"},
                        "bool_must":       {"type": "integer"},
                        "bool_should":     {"type": "integer"},
                        "bool_filter":     {"type": "integer"},
                        "bool_must_not":   {"type": "integer"},
                        "terms_values":    {"type": "integer"},
                        "knn":             {"type": "integer"},
                        "fuzzy":           {"type": "integer"},
                        "geo_bbox":        {"type": "integer"},
                        "geo_distance":    {"type": "integer"},
                        "geo_shape":       {"type": "integer"},
                        "agg":             {"type": "integer"},
                        "wildcard":        {"type": "integer"},
                        "nested":          {"type": "integer"},
                        "runtime_mapping": {"type": "integer"},
                        "script":          {"type": "integer"},
                    }
                },
                "cost_indicators": {
                    "properties": {
                        "has_script":          {"type": "integer"},
                        "has_runtime_mapping": {"type": "integer"},
                        "has_wildcard":        {"type": "integer"},
                        "has_nested":          {"type": "integer"},
                        "has_fuzzy":           {"type": "integer"},
                        "has_geo":             {"type": "integer"},
                        "has_knn":             {"type": "integer"},
                        "excessive_bool":      {"type": "integer"},
                        "large_terms_list":    {"type": "integer"},
                        "deep_aggs":           {"type": "integer"},
                        "unbound_hits":        {"type": "integer"},
                    }
                },
                "stress": {
                    "properties": {
                        "score":                {"type": "float"},
                        "base":                 {"type": "float"},
                        "multiplier":           {"type": "float"},
                        "components": {
                            "properties": {
                                "took":          {"type": "float"},
                                "shards":        {"type": "float"},
                                "hits":          {"type": "float"},
                                "docs_affected": {"type": "float"},
                                "bonus":         {"type": "float"},
                            }
                        },
                        "cost_indicator_count": {"type": "integer"},
                        "cost_indicator_names": {"type": "keyword"},
                        "cost_indicator_multipliers": {"type": "flattened"},
                        "bonuses":              {"type": "object", "enabled": False},
                    }
                },
                # _msearch fan-out metadata
                "msearch": {
                    "properties": {
                        "request_id":      {"type": "keyword"},
                        "batch_size":      {"type": "integer"},
                        "sub_query_index": {"type": "integer"},
                    }
                },
                # Infrastructure
                "cluster_name": {"type": "constant_keyword"},
                # Error records (partial)
                "error":  {"type": "text"},
                "path":   {"type": "keyword"},
                "method": {"type": "keyword"},
            }
        }
    }
}

COMPONENT_TEMPLATE_NAME = "alo-mappings"

# ── Operation categories ────────────────────────────────────────────────────

_SEARCH_OPS = [
    "search", "msearch", "async_search",
    "search_template", "msearch_template",
    "sql", "esql", "eql",
    "count", "scroll", "knn_search",
]

_WRITE_OPS = [
    "bulk", "index", "create", "delete",
    "update_by_query", "delete_by_query", "reindex",
]

# ── ILM policies ────────────────────────────────────────────────────────────


def _ilm_policy(delete_after: str) -> dict:
    return {
        "policy": {
            "phases": {
                "hot": {
                    "actions": {
                        "rollover": {
                            "max_age": "3d",
                            "max_primary_shard_size": "50gb",
                        }
                    }
                },
                "delete": {
                    "min_age": delete_after,
                    "actions": {"delete": {}}
                },
            }
        }
    }


ILM_POLICIES: dict[str, dict] = {
    "alo-search-lifecycle":      _ilm_policy("3d"),
    "alo-write-lifecycle":       _ilm_policy("3d"),
    "alo-default-lifecycle":     _ilm_policy("3d"),
    "alo-dead-letter-lifecycle": _ilm_policy("3d"),
}

# ── Summary index (long-term retention) ────────────────────────────────────

SUMMARY_INDEX = "alo-summary"
SUMMARY_TRANSFORM_ID = "alo-summary-transform"

_PCT_FIELDS: dict = {
    "properties": {
        "50": {"type": "double"},
        "95": {"type": "double"},
        "99": {"type": "double"},
    },
}

SUMMARY_INDEX_TEMPLATE: dict = {
    "index_patterns": ["alo-summary"],
    "priority": 200,
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "@timestamp": {"type": "date"},
                # ── Dimensions (same paths as raw index) ──
                "request": {
                    "properties": {
                        "template":  {"type": "keyword"},
                        "operation": {"type": "keyword"},
                        "target":    {"type": "keyword"},
                    },
                },
                "identity": {
                    "properties": {
                        "applicative_provider": {"type": "keyword"},
                    },
                },
                "cluster_name": {"type": "keyword"},
                # ── Averages (same paths as raw — panels work on both) ──
                "response": {
                    "properties": {
                        "es_took_ms":      {"type": "double"},
                        "gateway_took_ms": {"type": "double"},
                        "hits":            {"type": "double"},
                        "shards_total":    {"type": "double"},
                        "docs_affected":   {"type": "double"},
                    },
                },
                "stress": {
                    "properties": {
                        "score":                {"type": "double"},
                        "base":                 {"type": "double"},
                        "multiplier":           {"type": "double"},
                        "cost_indicator_count": {"type": "double"},
                    },
                },
                # ── Summary-only fields ──
                "count":     {"type": "long"},
                "sum_score": {"type": "double"},
                "request_size_bytes": {"type": "double"},
                # ── Percentiles (p50 / p95 / p99 per hourly bucket) ──
                "pct_es_took_ms":      _PCT_FIELDS,
                "pct_gateway_took_ms": _PCT_FIELDS,
                "pct_score":           _PCT_FIELDS,
            },
        },
    },
}

_PERCENTILES = [50, 95, 99]

SUMMARY_TRANSFORM: dict = {
    "source": {
        "index": ["logs-alo.*-*"],
        "query": {
            "bool": {
                "must_not": [
                    {"term": {"request.operation": "unknown"}},
                ],
            },
        },
    },
    "dest": {
        "index": SUMMARY_INDEX,
    },
    "pivot": {
        "group_by": {
            # Dotted paths → output matches raw index structure
            "@timestamp": {
                "date_histogram": {
                    "field": "@timestamp",
                    "calendar_interval": "1h",
                },
            },
            "request.template": {
                "terms": {"field": "request.template"},
            },
            "request.operation": {
                "terms": {"field": "request.operation"},
            },
            "identity.applicative_provider": {
                "terms": {"field": "identity.applicative_provider"},
            },
            "request.target": {
                "terms": {"field": "request.target"},
            },
            "cluster_name": {
                "terms": {"field": "cluster_name"},
            },
        },
        "aggregations": {
            # Volume
            "count": {"value_count": {"field": "@timestamp"}},
            # Averages — dotted paths match raw index for shared panels
            "stress.score":                {"avg": {"field": "stress.score"}},
            "sum_score":                   {"sum": {"field": "stress.score"}},
            "stress.base":                 {"avg": {"field": "stress.base"}},
            "stress.multiplier":           {"avg": {"field": "stress.multiplier"}},
            "stress.cost_indicator_count": {"avg": {"field": "stress.cost_indicator_count"}},
            "response.es_took_ms":         {"avg": {"field": "response.es_took_ms"}},
            "response.gateway_took_ms":    {"avg": {"field": "response.gateway_took_ms"}},
            "response.hits":               {"avg": {"field": "response.hits"}},
            "response.shards_total":       {"avg": {"field": "response.shards_total"}},
            "response.docs_affected":      {"avg": {"field": "response.docs_affected"}},
            "request_size_bytes":          {"avg": {"field": "request.size_bytes"}},
            # Percentiles (p50 / p95 / p99)
            "pct_es_took_ms": {
                "percentiles": {
                    "field": "response.es_took_ms",
                    "percents": _PERCENTILES,
                },
            },
            "pct_gateway_took_ms": {
                "percentiles": {
                    "field": "response.gateway_took_ms",
                    "percents": _PERCENTILES,
                },
            },
            "pct_score": {
                "percentiles": {
                    "field": "stress.score",
                    "percents": _PERCENTILES,
                },
            },
        },
    },
    "sync": {
        "time": {
            "field": "@timestamp",
            "delay": "5m",
        },
    },
    "retention_policy": {
        "time": {
            "field": "@timestamp",
            "max_age": "120d",
        },
    },
    "frequency": "5m",
    "description": "ALO hourly summary with percentiles per template/operation/app/target.",
}

# ── Composable index templates ──────────────────────────────────────────────

INDEX_TEMPLATES: dict[str, dict] = {
    "alo-search-operations": {
        "index_patterns": [f"logs-alo.{op}-*" for op in _SEARCH_OPS],
        "data_stream": {},
        "composed_of": [COMPONENT_TEMPLATE_NAME],
        "priority": 200,
        "template": {
            "settings": {
                "index.lifecycle.name": "alo-search-lifecycle",
            }
        },
    },
    "alo-write-operations": {
        "index_patterns": [f"logs-alo.{op}-*" for op in _WRITE_OPS],
        "data_stream": {},
        "composed_of": [COMPONENT_TEMPLATE_NAME],
        "priority": 200,
        "template": {
            "settings": {
                "index.lifecycle.name": "alo-write-lifecycle",
            }
        },
    },
    "alo-default": {
        "index_patterns": ["logs-alo.*-*"],
        "data_stream": {},
        "composed_of": [COMPONENT_TEMPLATE_NAME],
        "priority": 150,
        "template": {
            "settings": {
                "index.lifecycle.name": "alo-default-lifecycle",
            }
        },
    },
    "alo-dead-letter": {
        "index_patterns": ["logs-alo.dead_letter-*"],
        "data_stream": {},
        "priority": 200,
        "template": {
            "settings": {
                "index.lifecycle.name": "alo-dead-letter-lifecycle",
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "dynamic": True,
            },
        },
    },
}
