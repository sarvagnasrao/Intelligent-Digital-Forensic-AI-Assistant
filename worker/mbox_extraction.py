"""Extract searchable message text from an mbox evidence file.

The output belongs to the archive artifact, not to individually registered
messages. Envelope separators and MIME decoding are parser interpretations;
the archive's original bytes and digest remain the authoritative evidence.
"""

import mailbox
import os
import tempfile

try:
    from .email_extraction import extract_email_text
except ImportError:  # Direct execution as python worker/main.py
    from email_extraction import extract_email_text


def extract_mbox_text(content: bytes) -> str | None:
    """Read standard mbox messages without modifying the evidence or attachments.

    Uses a temporary copy because stdlib mailbox requires a filesystem path.
    Non-mbox, empty and unsupported mailbox variants can yield no text. No
    message-level provenance, attachment extraction or OCR is provided.
    """
    if not content.startswith(b"From "):
        return None
    path = None
    box = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mbox") as temp:
            path = temp.name
            temp.write(content)
        box = mailbox.mbox(path, create=False)
        parts = []
        for key in box.iterkeys():
            # Re-serializing mailbox's Message converts raw 8-bit body bytes
            # before the MIME charset is applied, corrupting legacy mail.
            text = extract_email_text(box.get_bytes(key))
            if text.strip():
                parts.append(text)
        return "\n\n".join(parts) or None
    except (OSError, ValueError, mailbox.Error):
        return None
    finally:
        if box is not None:
            box.close()
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass
