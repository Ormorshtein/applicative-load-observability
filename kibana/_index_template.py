"""
Elasticsearch data stream resources for ALO.

Defines a shared component template (mappings), three ILM policies
(search / write / default), and three composable index templates that
route each operation category to the correct lifecycle.
"""

# ── Component template (shared mappings + settings) ─────────────────────────

COMPONENT_TEMPLATE: dict = {
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "5s",
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
                    }
                },
                "request": {
                    "properties": {
                        "method":     {"type": "keyword"},
                        "path":       {"type": "keyword"},
                        "operation":  {"type": "keyword"},
                        "target":     {"type": "keyword"},
                        "template":   {"type": "keyword"},
                        "body":       {"type": "object", "enabled": False},
                        "size_bytes": {"type": "integer"},
                        "size":       {"type": "integer"},
                    }
                },
                "response": {
                    "properties": {
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
                    }
                },
                "stress": {
                    "properties": {
                        "score":                {"type": "float"},
                        "multiplier":           {"type": "float"},
                        "cost_indicator_count": {"type": "integer"},
                        "cost_indicator_names": {"type": "keyword"},
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
                            "max_age": "1d",
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
    "alo-search-lifecycle":  _ilm_policy("90d"),
    "alo-write-lifecycle":   _ilm_policy("30d"),
    "alo-default-lifecycle": _ilm_policy("60d"),
    "alo-dead-letter-lifecycle": _ilm_policy("7d"),
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
        "priority": 100,
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
