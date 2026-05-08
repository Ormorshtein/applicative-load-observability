"""Path / URL extraction — parse ES operation and target index from request path."""

_METHOD_DISPATCH = {
    "GET":    "get",
    "HEAD":   "get",
    "PUT":    "index",
    "POST":   "index",
    "DELETE": "delete",
}


def parse_target(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    for segment in segments:
        if not segment.startswith("_"):
            return segment
    return "_all"


def parse_operation(method: str, path: str) -> str:
    for segment in reversed(path.split("/")):
        if segment.startswith("_"):
            if segment == "_doc":
                return _METHOD_DISPATCH.get(method, "index")
            return segment
    return _METHOD_DISPATCH.get(method, "index")
