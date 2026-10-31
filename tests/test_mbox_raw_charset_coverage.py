from worker.mbox_extraction import extract_mbox_text


def test_mbox_preserves_each_messages_declared_8bit_charset():
    archive = (
        b"From first Mon Jan  1 00:00:00 2024\n"
        b"Subject: First\nContent-Type: text/plain; charset=windows-1252\n"
        b"Content-Transfer-Encoding: 8bit\n\nCaf\xe9 contact\n\n"
        b"From second Tue Jan  2 00:00:00 2024\n"
        b"Subject: Second\nContent-Type: text/plain; charset=utf-8\n"
        b"Content-Transfer-Encoding: 8bit\n\n"
        b"M\xc3\xbcnchen account\n"
    )

    text = extract_mbox_text(archive)

    assert text is not None
    assert "Caf\u00e9 contact" in text
    assert "M\u00fcnchen account" in text
    assert "\ufffd" not in text
