"""Output TypedDicts — schema-as-code for the observability record."""

from typing import TypedDict


class IdentitySection(TypedDict):
    username: str
    applicative_provider: str
    user_agent: str
    client_host: str
    labels: list[str]


class RequestSection(TypedDict, total=False):
    method: str
    path: str
    operation: str
    target: str
    template: str
    body: str
    body_truncated: bool
    size_bytes: int
    size: int
    geo_vertex_count: int
    bulk_doc_count: int


class ResponseSection(TypedDict):
    status: int
    es_took_ms: float
    gateway_took_ms: float
    hits: int
    shards_total: int
    docs_affected: int
    size_bytes: int


class StressSection(TypedDict):
    score: float
    base: float
    multiplier: float
    components: dict[str, float]
    bonuses: dict[str, float]
    cost_indicator_count: int
    cost_indicator_names: list[str]


class ObservabilityRecord(TypedDict):
    """The full record indexed into Elasticsearch."""

    timestamp: str  # key is "@timestamp" in output
    identity: IdentitySection
    request: RequestSection
    response: ResponseSection
    clause_counts: dict[str, int]
    cost_indicators: dict[str, int]
    stress: StressSection
