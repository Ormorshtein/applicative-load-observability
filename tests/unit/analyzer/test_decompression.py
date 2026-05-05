"""Unit tests for analyzer/_decompression.py."""

import gzip
import zlib

from analyzer._decompression import decompress_body


def _as_text(blob: bytes) -> str:
    return blob.decode("utf-8", errors="surrogateescape")


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

    def test_corrupt_gzip_falls_back_to_input(self):
        corrupt = "\x1f\x8b\x08\x00garbage"
        assert decompress_body(corrupt) == corrupt

    def test_byte_resembling_zlib_but_not_valid(self):
        # Starts with 0x78 but fails the header checksum / inflate.
        text = "\x78garbage"
        assert decompress_body(text) == text

    def test_non_compressed_starting_with_x(self):
        # Plain text starting with 'x' must not trigger zlib detection.
        assert decompress_body("xyz123") == "xyz123"
