"""Best-effort decompression of gzip/zlib request and response bodies.

The gateway forwards raw HTTP bodies to the pipeline via cjson.encode, so a
client that sends ``Content-Encoding: gzip`` (e.g. Logstash with
``http_compression: true``) produces a JSON string whose value is binary
gzip data.  Logstash receives the payload with a plain/ISO-8859-1 codec and
pre-escapes high bytes as ``\\u00XX``, so by the time JSON is parsed each
original byte is represented as a codepoint U+0000–U+00FF.  This module
recovers the original bytes via ``latin-1`` encoding (1:1 codepoint→byte).

Detection is by magic byte rather than HTTP header because the gateway only
forwards request headers; an upstream-compressed response would otherwise be
indistinguishable from binary garbage.
"""

import base64
import gzip
import zlib

_GZIP_MAGIC = b"\x1f\x8b"
_ZLIB_FIRST_BYTE = 0x78
_ZLIB_HEADER_MOD = 31
# Prefix the gateway sets when it base64-encodes a gzip response body
# so that cjson can serialise it without corrupting binary bytes.
_GZIP_B64_PREFIX = "gzip+b64:"


def _to_bytes(text: str) -> bytes | None:
    try:
        return text.encode("latin-1")
    except UnicodeEncodeError:
        # Text contains characters outside Latin-1 (e.g. U+FFFD).
        # This cannot be compressed binary data — signal caller to skip.
        return None


def _looks_gzip(blob: bytes) -> bool:
    return len(blob) >= 2 and blob[:2] == _GZIP_MAGIC


def _looks_zlib(blob: bytes) -> bool:
    if len(blob) < 2 or blob[0] != _ZLIB_FIRST_BYTE:
        return False
    return ((blob[0] << 8) | blob[1]) % _ZLIB_HEADER_MOD == 0


def decompress_body(text: str) -> str:
    if not text:
        return text

    # Fast path: gateway base64-encoded a gzip response body to keep the
    # payload ASCII-safe across cjson serialisation.
    if text.startswith(_GZIP_B64_PREFIX):
        try:
            blob = base64.b64decode(text[len(_GZIP_B64_PREFIX):])
            if _looks_gzip(blob):
                return gzip.decompress(blob).decode("utf-8", errors="replace")
            if _looks_zlib(blob):
                return zlib.decompress(blob).decode("utf-8", errors="replace")
        except Exception:
            pass
        return ""  # corrupt / unexpected — treat as empty

    blob = _to_bytes(text)
    if blob is None:
        # Body contains non-Latin-1 characters — not compressed binary;
        # return as-is rather than crashing.
        return text
    try:
        if _looks_gzip(blob):
            return gzip.decompress(blob).decode("utf-8", errors="replace")
        if _looks_zlib(blob):
            return zlib.decompress(blob).decode("utf-8", errors="replace")
    except (OSError, zlib.error, EOFError):
        pass
    # Not compressed — the blob holds the original UTF-8 bytes
    # (latin-1 mojibake in the string). Decode to recover real text.
    return blob.decode("utf-8", errors="replace")
