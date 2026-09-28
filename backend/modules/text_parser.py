from pdfminer.high_level import extract_text as pdf_extract
import re


# Byte-order marks, longest first, each paired with an EXPLICIT byte order.
#
# Two ordering rules, both load-bearing:
#   * longest first, because UTF-32-LE's BOM starts with UTF-16-LE's, so the
#     short entry would match it and a UTF-32 file would decode as UTF-16
#     with every other character coming back as NUL;
#   * '-le' / '-be' rather than bare 'utf-16' / 'utf-32', because the BOM is
#     stripped before decoding, and the BOM-sniffing codecs then have no BOM
#     left to read and fall back to NATIVE byte order. On a little-endian
#     machine that silently turns a big-endian UTF-16 file into CJK-looking
#     mojibake with no error raised.
_BOMS = [
    (b'\xff\xfe\x00\x00', 'utf-32-le'),
    (b'\x00\x00\xfe\xff', 'utf-32-be'),
    (b'\xef\xbb\xbf', 'utf-8-sig'),
    (b'\xff\xfe', 'utf-16-le'),
    (b'\xfe\xff', 'utf-16-be'),
]


def decode_text_bytes(data: bytes) -> tuple:
    """
    Decodes text evidence, returning (text, encoding_name).

    This was a bare data.decode('utf-8', errors='ignore'), which is quietly
    wrong for a large share of real forensic text and — worse — wrong
    *silently*. A Windows Event Log export or an Excel CSV saved as "Unicode"
    is UTF-16; decoding it as UTF-8 with errors ignored does not raise, it
    returns mostly NUL characters. The file uploads, the job completes, the
    evidence is marked Indexed, and nothing useful was indexed. So the
    byte-order mark is honoured first, and the encoding actually used is
    returned alongside the text rather than thrown away.

    cp1252 is the final fallback rather than latin-1 because it maps the
    0x80-0x9F range to printable characters, which is what a log full of
    curly quotes and em-dashes actually contains. Its five undefined bytes
    are replaced rather than allowed to fail the whole file.

    Deliberately no BOM-less UTF-16 sniffing. Guessing from a NUL-byte ratio
    could turn a NUL-containing UTF-8 file into mojibake, which would be a
    regression on the behaviour above; without it, such a file keeps the
    answer it already gets. Only an encoding the file actually declares is
    believed.
    """
    if not data:
        return "", "empty"

    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return (data[len(bom):]
                        .decode(encoding, errors='replace'), encoding)
            except (LookupError, UnicodeDecodeError):
                break

    try:
        return data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return data.decode('cp1252', errors='replace'), 'cp1252'


def extract_text(file_path: str) -> str:
    """
    Extracts raw text from PDF or TXT file.
    Returns cleaned string.

    Non-PDF files are read as bytes and handed to decode_text_bytes rather
    than opened with encoding='utf-8'. The .txt fast path in ingestion.py and
    the byte path in forensic_ingestion.py are separate code, and decoding
    only one of them is how a UTF-16 file ends up garbled in one path and
    correct in the other for no reason a reader could infer.
    """
    try:
        if file_path.endswith(".pdf"):
            text = pdf_extract(file_path)
        else:
            with open(file_path, "rb") as f:
                data = f.read()
            text, _ = decode_text_bytes(data)

        # Clean excessive whitespace using fast regex
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\r\n|\r', '\n', text)
        text = re.sub(r'\n\s*\n', '\n', text)
        return text.strip()

    except Exception as e:
        print(f"TEXT EXTRACTION ERROR: {e}")
        return ""


def chunk_text(text: str,
               chunk_size: int = 20000,
               overlap: int = 0) -> list[str]:
    """
    Splits text into overlapping chunks.
    """
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return [c for c in chunks if len(c.strip()) > 20]
