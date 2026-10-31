from worker.main import extract_text_content


def test_invalid_text_bytes_are_reported_without_losing_readable_content():
    warnings = []
    text = extract_text_content(b"lead@example.org \xff", "text/plain", ".txt", warnings=warnings)

    assert text == "lead@example.org \ufffd"
    assert warnings == ["Invalid utf-8 bytes replaced during text decoding"]


def test_valid_replacement_character_is_not_a_decode_error():
    warnings = []
    assert extract_text_content("\ufffd".encode(), None, ".txt", warnings=warnings) == "\ufffd"
    assert warnings == []


def test_truncated_bom_encoded_text_is_reported():
    warnings = []
    assert extract_text_content(b"\xff\xfeA\x00B", None, ".txt", warnings=warnings) == "A\ufffd"
    assert warnings == ["Invalid utf-16 bytes replaced during text decoding"]
