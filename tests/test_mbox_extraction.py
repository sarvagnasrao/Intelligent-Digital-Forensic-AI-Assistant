import hashlib
import mailbox
from email.message import EmailMessage

from worker.main import describe_file_evidence, extract_text_content


def test_mbox_archive_messages_and_provenance(tmp_path):
    path = tmp_path / "mail.mbox"
    box = mailbox.mbox(path)
    first = EmailMessage()
    first["Subject"] = "First message"
    first.set_content("Searchable body")
    first.add_attachment(b"attachment secret", maintype="text", subtype="plain", filename="secret.txt")
    second = EmailMessage()
    second["Subject"] = "Second message"
    second.set_content("Another body", cte="base64")
    box.add(first)
    box.add(second)
    box.close()
    original = path.read_bytes()

    artifact = describe_file_evidence(str(path))

    assert artifact["content_hash"] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original
    assert artifact["extraction_status"] == "extracted"
    assert "First message" in artifact["content_text"]
    assert "Searchable body" in artifact["content_text"]
    assert "Second message" in artifact["content_text"]
    assert "Another body" in artifact["content_text"]
    assert "attachment secret" not in artifact["content_text"]


def test_non_mbox_is_not_interpreted_as_message():
    assert extract_text_content(b"Subject: not an mbox\n\nbody", None, ".mbox") is None
    assert extract_text_content(b"", None, ".mbox") is None
