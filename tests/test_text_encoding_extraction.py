"""Text evidence decoding uses synthetic in-memory inputs only."""

import pytest

from worker.main import extract_text_content


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-be", "utf-32", "utf-32-be"])
def test_bom_encoded_text_is_searchable(encoding):
    import codecs

    text = "Evidence: café\nSecond line"
    content = text.encode(encoding)
    if encoding == "utf-16-be":
        content = codecs.BOM_UTF16_BE + content
    elif encoding == "utf-32-be":
        content = codecs.BOM_UTF32_BE + content
    assert extract_text_content(content, None, ".log") == text


def test_unmarked_utf8_and_invalid_bytes_keep_existing_fallback():
    assert extract_text_content("café".encode(), None, ".txt") == "café"
    assert extract_text_content(b"bad\xffbyte", None, ".txt") == "bad\ufffdbyte"


def test_truncated_bom_encoded_text_does_not_raise():
    assert extract_text_content(b"\xff\xfeA", None, ".txt") == "\ufffd"
