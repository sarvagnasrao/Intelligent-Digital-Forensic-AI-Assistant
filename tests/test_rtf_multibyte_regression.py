from worker.rtf_extraction import extract_rtf_text


def test_shift_jis_hex_and_literal_bytes_are_decoded_together():
    # The first character mixes escaped and literal bytes; the second uses
    # two escaped bytes. Decoding each byte independently loses both characters.
    source = br"{\rtf1\ansi\ansicpg932 \'82" + b"\xa0" + br"\'82\'a2}"
    assert extract_rtf_text(source) == "あい"


def test_codepage_changes_flush_pending_text():
    source = br"{\rtf1\ansicpg932 \'82\'a0{\ansicpg1252 \'e9}\'82\'a2}"
    assert extract_rtf_text(source) == "あéい"
