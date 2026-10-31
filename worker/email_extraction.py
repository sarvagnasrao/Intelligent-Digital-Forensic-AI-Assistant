"""Extract searchable text from RFC 822 messages without reading attachments."""

import re
from email import policy
from email.parser import BytesParser
from html import unescape


def _simple_html_text(text: str) -> str | None:
    """Recognize only attribute-free markup, without discarding source-bearing HTML."""
    if re.search(r"<(?!/?[a-zA-Z][a-zA-Z0-9]*\s*/?>)", text):
        return None
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())


def extract_email_text(content: bytes, warnings: list[str] | None = None) -> str:
    """Decode message headers and text bodies; skip attached files.

    Distinct alternatives retain their original source text and MIME provenance.
    This does not attempt OCR or extract text from attachments.
    """
    message = BytesParser(policy=policy.default).parsebytes(content)
    parts = [f"{name}: {value}" for name, value in message.items()]

    def visit(part):
        disposition = part.get_content_disposition()
        if disposition == "attachment" or (disposition != "inline" and part.get_filename()):
            return []
        if part.is_multipart():
            children = list(part.iter_parts())
            if part.get_content_type() == "message/rfc822":
                result = []
                for child in children:
                    result.extend(f"{name}: {value}" for name, value in child.items())
                    result.extend(visit(child))
                return result
            if part.get_content_subtype() == "alternative":
                result = []
                seen = set()
                plain_texts = set()
                for index, child in enumerate(children, 1):
                    content = visit(child)
                    if not content:
                        continue
                    kind = child.get_content_type()
                    for text in content:
                        if text in seen:
                            continue
                        if kind == "text/html" and _simple_html_text(text) in plain_texts:
                            continue
                        seen.add(text)
                        if kind == "text/plain":
                            plain_texts.add(" ".join(text.split()))
                        result.append(f"[Alternative {index}: {kind}]\n{text}")
                return result
            result = []
            for child in children:
                result.extend(visit(child))
            return result
        # Calendar invitations commonly carry attendee addresses and locations
        # in an inline text/calendar part, sometimes without a plain-text body.
        # Keep the decoded iCalendar source rather than inferring identities.
        if part.get_content_type() in ("text/plain", "text/html", "text/calendar"):
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "ascii"
            if isinstance(payload, bytes):
                try:
                    payload.decode(charset, errors="strict")
                except (LookupError, UnicodeError):
                    if warnings is not None:
                        warnings.append(
                            f"email {part.get_content_type()} body has invalid or "
                            f"unknown charset {charset}"
                        )
            try:
                text = part.get_content()
            except (LookupError, UnicodeError):
                text = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
            if isinstance(text, str) and text.strip():
                text = text.strip()
                if part.get_content_type() == "text/html":
                    decoded = unescape(text)
                    if decoded != text:
                        return [f"{text}\n[HTML character references decoded]\n{decoded}"]
                return [text]
        return []

    parts.extend(visit(message))
    return "\n".join(parts)
