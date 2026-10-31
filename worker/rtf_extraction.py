"""Conservative extraction of visible text from RTF, without executing content.

This is not a rendering engine: embedded objects, fields' instructions, images,
headers and footers are omitted. Output is derived text, not byte offsets or
proof that a particular renderer displayed it.
"""

import re

_CONTROL = re.compile(rb"([a-zA-Z]+)(-?\d+)? ?")
_SKIP = {b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict",
         b"object", b"objdata", b"filetbl", b"listtable", b"listoverridetable",
         b"generator", b"header", b"footer", b"headerl", b"headerr",
         b"footerl", b"footerr", b"fldinst", b"xmlopen", b"xmlclose"}


def extract_rtf_text(content: bytes) -> str | None:
    """Return recoverable text from a structurally valid RTF document.

    Supports ANSI code pages, hex escapes and RTF Unicode fallback. Unknown
    destinations marked with \\* and binary payloads are ignored. Malformed
    groups or binary lengths return None rather than indexing partial garbage.
    """
    if not content.startswith(b"{\\rtf"):
        return None
    # Each group inherits its parent's destination and Unicode fallback count.
    stack = []
    skip = False
    uc = 1
    codepage = "cp1252"
    fallback = 0
    out = []
    pending = bytearray()

    def flush_text():
        if pending:
            out.append(pending.decode(codepage, errors="replace"))
            pending.clear()

    i = 0
    while i < len(content):
        c = content[i]
        if c == 123:  # {
            flush_text()
            stack.append((skip, uc, codepage))
            i += 1
        elif c == 125:  # }
            flush_text()
            if not stack:
                return None
            skip, uc, codepage = stack.pop()
            i += 1
            if not stack and content[i:].strip():
                return None
        elif c == 92:
            i += 1
            if i >= len(content):
                return None
            symbol = content[i]
            if symbol in (92, 123, 125, 126, 45, 95):
                if fallback:
                    fallback -= 1
                elif not skip:
                    flush_text()
                    out.append({126: "\u00a0", 45: "\u00ad", 95: "\u2011"}.get(symbol, chr(symbol)))
                i += 1
            elif symbol == 42:
                skip = True
                i += 1
            elif symbol == 39:
                if i + 2 >= len(content):
                    return None
                try:
                    value = int(content[i + 1:i + 3], 16)
                except ValueError:
                    return None
                if fallback:
                    fallback -= 1
                elif not skip:
                    pending.append(value)
                i += 3
            else:
                match = _CONTROL.match(content, i)
                if not match:
                    i += 1
                    continue
                word = match.group(1).lower()
                number = int(match.group(2)) if match.group(2) else None
                i = match.end()
                if word == b"bin":
                    if number is None or number < 0 or i + number > len(content):
                        return None
                    i += number
                elif word in _SKIP:
                    skip = True
                elif word == b"ansicpg" and number is not None:
                    flush_text()
                    import codecs
                    try:
                        codepage = codecs.lookup(f"cp{number}").name
                    except LookupError:
                        codepage = "cp1252"
                elif word == b"uc" and number is not None:
                    uc = max(0, number)
                elif word == b"u" and number is not None:
                    if not skip:
                        flush_text()
                        out.append(chr(number & 0xffff))
                    fallback = uc
                elif not skip and word in (b"par", b"line", b"tab"):
                    flush_text()
                    out.append("\t" if word == b"tab" else "\n")
        else:
            if c not in (10, 13):
                if fallback:
                    fallback -= 1
                elif not skip:
                    pending.append(c)
            i += 1
    if stack:
        return None
    flush_text()
    # Combine UTF-16 surrogate pairs emitted by consecutive \u controls.
    text = "".join(out).encode("utf-16", errors="surrogatepass").decode("utf-16", errors="replace")
    return text if text.strip() else None
