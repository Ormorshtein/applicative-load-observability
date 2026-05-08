"""Geo vertex counting — count coordinate points in geo_shape / geo_polygon queries."""

from typing import Any


def _count_coords(node: Any) -> int:
    """Count coordinate points in nested arrays."""
    if not node or not isinstance(node, list):
        return 0
    if len(node) >= 2 and isinstance(node[0], (int, float)):
        return 1
    return sum(_count_coords(item) for item in node)


def _count_geo_vertices(node: Any) -> int:
    """Walk a query body and count total vertices in geo_shape/geo_polygon."""
    if isinstance(node, list):
        return sum(_count_geo_vertices(item) for item in node)
    if not isinstance(node, dict):
        return 0
    total = 0
    for key, value in node.items():
        if key in ("geo_shape", "geo_polygon") and isinstance(value, dict):
            for field_val in value.values():
                if not isinstance(field_val, dict):
                    continue
                shape = field_val.get("shape", field_val)
                total += _count_coords(shape.get("coordinates", []))

        if isinstance(value, (dict, list)):
            total += _count_geo_vertices(value)
    return total


def parse_geo_vertex_count(body: dict) -> int:
    """Total vertices across all geo_shape/geo_polygon clauses in the query."""
    return _count_geo_vertices(body.get("query", {}))
