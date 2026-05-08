"""Shared data containers — no project imports, no side effects."""

from dataclasses import dataclass


@dataclass
class RawFields:
    method:               str
    path:                 str
    headers:              dict
    request_body:         dict
    request_body_raw:     str
    response_body:        dict
    client_host:          str
    response_status:      int
    gateway_took_ms:      float
    request_size_bytes:   int
    response_size_bytes:  int
    cluster_name:         str


@dataclass(frozen=True, slots=True)
class StressResult:
    clause_counts:         dict[str, int]
    cost_indicators:       dict[str, int]
    stress_multiplier:     float
    indicator_multipliers: dict[str, float]
    geo_vertex_count:      int
    score:                 float
    bonuses:               dict[str, float]
    components:            dict[str, float]


@dataclass(frozen=True, slots=True)
class ResponseMetrics:
    es_took_ms:     float
    hits:           int
    shards_total:   int
    docs_affected:  int
    bulk_doc_count: int


@dataclass(frozen=True, slots=True)
class OperationMeta:
    operation: str
    target:    str
    template:  str
