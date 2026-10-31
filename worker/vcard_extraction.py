"""Extract readable contact fields from vCard evidence without external tools."""

import base64
import binascii
import quopri
import re


def _encoding(header: str, values: str) -> bool:
    """Match a complete encoding parameter, optionally quoted."""
    return bool(re.search(rf'(?:^|;)ENCODING="?(?:{values})"?(?:;|$)', header, re.IGNORECASE))


def extract_vcard_text(content: bytes) -> str | None:
    """Return vCard properties, including multiple cards and folded lines.

    Binary values are omitted; this is not a complete vCard parser.
    """
    # Preserve undecodable bytes until each property's declared charset is known.
    utf16 = content.startswith((b"\xff\xfe", b"\xfe\xff"))
    text = (
        content.decode("utf-16", errors="replace") if utf16
        else content.decode("utf-8-sig", errors="surrogateescape")
    )
    lines = text.splitlines()
    # vCard 2.1 quoted-printable values may use MIME soft line breaks, which
    # are distinct from the whitespace-prefixed vCard folding handled above.
    unfolded = []
    for line in lines:
        if (
            unfolded
            and unfolded[-1].endswith("=")
            # A damaged value must not consume a structural card boundary.
            and line.upper() not in {"BEGIN:VCARD", "END:VCARD"}
            # Nor should it swallow an unindented following property when a
            # damaged quoted-printable value ends in a stray equals sign.
            and not re.match(r"^[A-Za-z0-9.-]+(?:;[^:]*)?:", line)
            and _encoding(unfolded[-1].split(":", 1)[0], "QUOTED-PRINTABLE")
        ):
            continuation = line[1:] if line.startswith((" ", "\t")) else line
            unfolded[-1] = unfolded[-1][:-1] + continuation
        elif unfolded and line.startswith((" ", "\t")):
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    result = []
    inside = False
    for line in unfolded:
        if line.upper() == "BEGIN:VCARD":
            inside = True
            continue
        if line.upper() == "END:VCARD":
            inside = False
            continue
        if not inside or ":" not in line:
            continue
        header, value = line.split(":", 1)
        name = header.split(";", 1)[0].rsplit(".", 1)[-1].upper()
        params = header.upper()
        if name in {"VERSION", "PHOTO", "LOGO", "SOUND", "KEY"}:
            continue
        base64_encoded = _encoding(params, "B|BASE64")
        # Only decode known textual properties: unknown extensions may carry
        # arbitrary binary data even when their encoding is valid base64.
        if base64_encoded and name not in {
            "FN", "N", "NICKNAME", "EMAIL", "TEL", "ADR", "LABEL", "ORG",
            "TITLE", "ROLE", "NOTE", "URL", "UID",
        }:
            continue
        charset = re.search(r"(?:^|;)CHARSET=([^;]+)", header, re.IGNORECASE)
        raw = value.encode("utf-8", errors="surrogateescape")
        if base64_encoded:
            try:
                raw = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                continue
        elif _encoding(params, "QUOTED-PRINTABLE"):
            raw = quopri.decodestring(raw)
        # Unencoded values in a UTF-16 container are already Unicode. A
        # property charset only applies to encoded bytes, not these characters.
        if not utf16 or base64_encoded or _encoding(params, "QUOTED-PRINTABLE"):
            try:
                value = raw.decode(
                    charset.group(1).strip('"') if charset else "utf-8", errors="replace"
                )
            except LookupError:
                value = raw.decode("utf-8", errors="replace")
        value = re.sub(r"\\[nN]", "\n", value)
        value = re.sub(r"\\([,;\\])", r"\1", value).strip()
        if value:
            result.append(f"{name}: {value}")
    return "\n".join(result) or None
