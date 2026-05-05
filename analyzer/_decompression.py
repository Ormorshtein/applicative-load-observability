"""Best-effort decompression of gzip/zlib request and response bodies.

The gateway forwards raw HTTP bodies to the pipeline via cjson.encode, so a
client that sends ``Content-Encoding: gzip`` (e.g. Logstash with
``http_compression: true``) produces a JSON string whose value is binary
gzip data. By the time the body reaches the analyzer it must round-trip
through Logstash's JSON codec — main.py preserves the bytes by decoding the
incoming HTTP body with ``errors='surrogateescape'``, and this module
re-encodes the field with the same handler to recover the original bytes.

Detection is by magic byte rather than HTTP header because the gateway only
forwards request headers; an upstream-compressed response would otherwise be
indistinguishable from binary garbage.
"""

import gzip
import zlib

_GZIP_MAGIC = b"\x1f\x8b"
_ZLIB_FIRST_BYTE = 0x78
_ZLIB_HEADER_MOD = 31


def _to_bytes(text: str) -> bytes:
    return text.encode("utf-8", errors="surrogateescape")


def _looks_gzip(blob: bytes) -> bool:
    return len(blob) >= 2 and blob[:2] == _GZIP_MAGIC


def _looks_zlib(blob: bytes) -> bool:
    if len(blob) < 2 or blob[0] != _ZLIB_FIRST_BYTE:
        return False
    return ((blob[0] << 8) | blob[1]) % _ZLIB_HEADER_MOD == 0


def decompress_body(text: str) -> str:
    if not text:
        return text
    blob = _to_bytes(text)
    try:
        if _looks_gzip(blob):
            return gzip.decompress(blob).decode("utf-8", errors="replace")
        if _looks_zlib(blob):
            return zlib.decompress(blob).decode("utf-8", errors="replace")
    except (OSError, zlib.error, EOFError):
        pass
    return text
