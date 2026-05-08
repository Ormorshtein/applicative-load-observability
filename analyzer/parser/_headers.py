"""Header extraction — parse identity and label fields from request headers."""

import base64
import binascii
import logging
import re

logger = logging.getLogger(__name__)

_BASIC_AUTH_PREFIX = "Basic "
_LABEL_PREFIX = "x-alo-"


def parse_username(headers: dict) -> str:
    auth = headers.get("authorization", "")
    if auth.startswith(_BASIC_AUTH_PREFIX):
        try:
            raw = base64.b64decode(auth[len(_BASIC_AUTH_PREFIX):])
            decoded = raw.decode("utf-8", errors="replace")
            return decoded.split(":")[0]
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            logger.debug("auth header undecodable: %s", exc)
    return ""


def parse_applicative_provider(headers: dict[str, str]) -> str:
    opaque: str = headers.get("x-opaque-id", "")
    if opaque:
        return opaque.split("/")[0]

    app_name: str = headers.get("x-app-name", "")
    if app_name:
        return app_name

    user_agent: str = headers.get("user-agent", "")
    if user_agent:
        return re.split(r"[/ ]", user_agent)[0]

    return ""


def parse_user_agent(headers: dict[str, str]) -> str:
    return str(headers.get("user-agent", ""))


def parse_labels(headers: dict) -> dict[str, str]:
    """Extract custom user labels from x-alo-* headers."""
    prefix_len = len(_LABEL_PREFIX)
    return {
        key[prefix_len:]: str(value)
        for key, value in headers.items()
        if key.startswith(_LABEL_PREFIX) and len(key) > prefix_len
    }
