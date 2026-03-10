"""Elasticsearch composable index template for ALO data streams."""

INDEX_TEMPLATE: dict = {
    "index_patterns": ["alo-*-*"],
    "data_stream": {},
    "priority": 100,
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
                # Error records (partial)
                "error":  {"type": "text"},
                "path":   {"type": "keyword"},
                "method": {"type": "keyword"},
            }
        }
    }
}
