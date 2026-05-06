"""Unit tests for analyzer/_decompression.py."""

import gzip
import zlib

from analyzer._decompression import decompress_body


def _as_text(blob: bytes) -> str:
    return blob.decode("latin-1")


class TestDecompressBody:
    def test_empty_passthrough(self):
        assert decompress_body("") == ""

    def test_plain_json_passthrough(self):
        assert decompress_body('{"foo": "bar"}') == '{"foo": "bar"}'

    def test_plain_text_passthrough(self):
        assert decompress_body("hello world") == "hello world"

    def test_gzip_decompresses(self):
        original = '{"query":{"match_all":{}}}'
        encoded = _as_text(gzip.compress(original.encode("utf-8")))
        assert decompress_body(encoded) == original

    def test_gzip_bulk_ndjson(self):
        original = (
            '{"index":{"_index":"a"}}\n{"foo":"bar"}\n'
            '{"index":{"_index":"b"}}\n{"baz":"qux"}\n'
        )
        encoded = _as_text(gzip.compress(original.encode("utf-8")))
        assert decompress_body(encoded) == original

    def test_zlib_decompresses(self):
        original = '{"hello":"world"}'
        encoded = _as_text(zlib.compress(original.encode("utf-8")))
        assert decompress_body(encoded) == original

    def test_corrupt_gzip_falls_back_to_utf8_decode(self):
        corrupt = "\x1f\x8b\x08\x00garbage"
        # Corrupt gzip falls through to UTF-8 decode of the raw bytes.
        # The result is the UTF-8 interpretation of the latin-1 bytes.
        result = decompress_body(corrupt)
        expected = corrupt.encode("latin-1").decode("utf-8", errors="replace")
        assert result == expected

    def test_byte_resembling_zlib_but_not_valid(self):
        # Starts with 0x78 but fails the header checksum / inflate.
        text = "\x78garbage"
        assert decompress_body(text) == text

    def test_non_compressed_starting_with_x(self):
        # Plain text starting with 'x' must not trigger zlib detection.
        assert decompress_body("xyz123") == "xyz123"

    def test_hebrew_round_trip(self):
        # Hebrew text arrives as latin-1 mojibake (each UTF-8 byte
        # mapped to a U+00XX codepoint). decompress_body must recover it.
        original = '{"query":{"match":{"title":"שלום"}}}'
        mojibake = _as_text(original.encode("utf-8"))
        assert decompress_body(mojibake) == original

    def test_mixed_ascii_and_hebrew(self):
        original = 'hello שלום world'
        mojibake = _as_text(original.encode("utf-8"))
        assert decompress_body(mojibake) == original

    def test_gzip_hebrew_body(self):
        original = '{"query":{"match":{"title":"שלום"}}}'
        encoded = _as_text(gzip.compress(original.encode("utf-8")))
        assert decompress_body(encoded) == original
