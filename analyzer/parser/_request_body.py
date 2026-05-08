"""Request body extraction — parse and scrub ES request bodies."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_ES_DEFAULT_SIZE = 10
_SCRUB_PLACEHOLDER = "?"


def parse_size(body: dict) -> int:
    return int(body.get("size", _ES_DEFAULT_SIZE))


def _scrub(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _scrub(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub(item) for item in node]
    return _SCRUB_PLACEHOLDER


def scrub_template(body: dict) -> str:
    return json.dumps(_scrub(body), sort_keys=True)


def scrub_bulk_template(raw_body: str) -> tuple[str, str]:
    """Build a structural template from an NDJSON bulk request body.

    Extracts unique action types and target indices from action lines,
    producing a stable template like:
        {"actions": ["index"], "target": ["my-index"]}

    Returns (template_str, comma_separated_targets).
    """
    actions = set()
    targets = set()
    for line_no, line in enumerate(raw_body.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("bulk template: malformed line %d: %s", line_no, exc)
            continue
        if not isinstance(obj, dict):
            continue
        for action_type in ("index", "create", "update", "delete"):
            if action_type in obj and isinstance(obj[action_type], dict):
                actions.add(action_type)
                idx = obj[action_type].get("_index", "")
                if idx:
                    targets.add(idx)
                break
    sorted_targets = sorted(targets) if targets else ["_all"]
    target_str = ",".join(sorted_targets)
    if not actions:
        return "", target_str
    template = json.dumps({
        "actions": sorted(actions),
        "target": sorted_targets,
    }, sort_keys=True)
    return template, target_str


def parse_bulk_doc_count(raw_body: str) -> int:
    """Count the number of documents submitted in a ``_bulk`` request body.

    Counts NDJSON action lines (``index``, ``create``, ``update``, ``delete``)
    only — document body lines that follow each action are not counted.
    Returns 0 for an empty or entirely malformed body.
    """
    count = 0
    skipped = 0
    expect_action = True  # alternates: action line → doc line → action line …
    for line_no, line in enumerate(raw_body.splitlines()):
        line = line.strip()
        if not line:
            continue
        if expect_action:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("bulk doc count: malformed line %d: %s", line_no, exc)
                skipped += 1
                continue
            if not isinstance(obj, dict):
                continue
            for action_type in ("index", "create", "update", "delete"):
                if action_type in obj and isinstance(obj[action_type], dict):
                    count += 1
                    # ``delete`` has no following doc body line
                    expect_action = action_type == "delete"
                    break
        else:
            # This is the document body line; skip it
            expect_action = True
    if skipped:
        logger.info("bulk doc count: skipped %d malformed lines (counted %d docs)", skipped, count)
    return count


def parse_msearch_pairs(raw_body: str) -> list[tuple[dict, dict]]:
    """Extract (header, search_body) pairs from an _msearch NDJSON request.

    _msearch alternates: header line, search body line, header line, ...
    Returns [(header_dict, body_dict), ...].
    """
    pairs: list[tuple[dict, dict]] = []
    lines = [ln for ln in raw_body.splitlines() if ln.strip()]
    for i in range(0, len(lines) - 1, 2):
        try:
            header = json.loads(lines[i])
            body = json.loads(lines[i + 1])
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("msearch: skipping pair at offset %d: %s", i, exc)
            continue
        if isinstance(header, dict) and isinstance(body, dict):
            pairs.append((header, body))
    return pairs
