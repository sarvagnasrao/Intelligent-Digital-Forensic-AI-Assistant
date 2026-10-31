from worker.vcard_extraction import extract_vcard_text


def test_vcard_quoted_printable_soft_break_and_charset():
    card = (b"BEGIN:VCARD\r\nVERSION:2.1\r\n"
            b"FN;CHARSET=ISO-8859-1;ENCODING=QUOTED-PRINTABLE:Andr=E9=\r\n"
            b"=20Smith\r\nEND:VCARD\r\n")
    assert extract_vcard_text(card) == "FN: André Smith"


def test_vcard_unknown_charset_does_not_abort_other_fields():
    card = (b"BEGIN:VCARD\nFN;CHARSET=unknown-idfa;ENCODING=QUOTED-PRINTABLE:Alice\n"
            b"EMAIL:alice@example.com\nEND:VCARD\n")
    assert extract_vcard_text(card) == "FN: Alice\nEMAIL: alice@example.com"
