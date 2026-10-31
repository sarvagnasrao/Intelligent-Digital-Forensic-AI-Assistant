from worker.main import extract_text_content
from worker.vcard_extraction import extract_vcard_text


def test_vcard_contacts_and_folding():
    content = (b"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jane "
               b"\r\n Doe\r\nEMAIL:jane@example.test\r\n"
               b"PHOTO;ENCODING=b:secret\r\nEND:VCARD\r\n"
               b"BEGIN:VCARD\r\nFN:John\\, Smith\r\nEND:VCARD\r\n")
    result = extract_text_content(content, None, ".vcf")
    assert "FN: Jane Doe" in result
    assert "EMAIL: jane@example.test" in result
    assert "FN: John, Smith" in result
    assert "secret" not in result


def test_invalid_vcard_has_no_fabricated_text():
    assert extract_vcard_text(b"FN:Not a card") is None
