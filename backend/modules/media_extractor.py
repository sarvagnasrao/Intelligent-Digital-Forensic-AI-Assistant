"""
media_extractor.py
==================
Handles multimedia file text extraction for
the Intelligent Digital Forensic AI Assistant pipeline.

Supports:
  - Office documents (.docx, .xlsx, .pptx)
  - Email files    (.eml, .msg)
  - Images with OCR (.jpg, .png, .tiff, …)
  - Audio files    (.mp3, .wav, .m4a, .flac, …)
  - Video files    (.mp4, .avi, .mov, .mkv, …)

All extraction is wrapped in try/except so a
single bad file never breaks the pipeline.
"""

import os
import json
import shutil
import tempfile
import subprocess
from datetime import datetime

# ── Conditional imports ───────────────────

try:
    import pytesseract
    from PIL import Image as PILImage
    import io as _io
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    print("WARNING: pytesseract not available. "
          "Image OCR disabled.")

try:
    from whisper import whisper as _whisper_mod
    _WHISPER_MODEL = None
    WHISPER_AVAILABLE = True
except ImportError:
    try:
        import whisper
        _WHISPER_MODEL = None
        WHISPER_AVAILABLE = True
    except ImportError:
        WHISPER_AVAILABLE = False
        print("WARNING: whisper not available. "
              "Audio/video transcription disabled.")

# ── Registry parser ───────────────────────────────────────────────────────────
try:
    from backend.modules.registry_parser import (
        is_registry_hive,
        parse_registry_hive,
        REGISTRY_HIVES,
    )
    REGISTRY_PARSER_AVAILABLE = True
except ImportError:
    REGISTRY_PARSER_AVAILABLE = False

try:
    from docx import Document as DocxDoc
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import openpyxl
    XLSX_AVAILABLE = True
except ImportError:
    XLSX_AVAILABLE = False

try:
    from pptx import Presentation
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False

try:
    import extract_msg
    MSG_AVAILABLE = True
except ImportError:
    MSG_AVAILABLE = False

import email as email_lib
from email import policy as email_policy

# ── Extension sets ────────────────────────

AUDIO_EXTENSIONS = {
    '.mp3', '.wav', '.m4a',
    '.flac', '.ogg', '.aac',
    '.wma', '.aiff'
}
VIDEO_EXTENSIONS = {
    '.mp4', '.avi', '.mov',
    '.mkv', '.wmv', '.flv',
    '.webm', '.m4v'
}
OFFICE_EXTENSIONS = {
    '.docx', '.doc',
    '.xlsx', '.xls',
    '.pptx', '.ppt'
}
EMAIL_EXTENSIONS = {
    '.eml', '.msg'
}
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png',
    '.tiff', '.tif', '.bmp',
    '.gif', '.webp'
}

# 30 minutes max for Whisper transcription
MAX_AUDIO_DURATION_SECONDS = 1800


# ── Whisper model (lazy load, per size) ─────────────

# Cache one model per size, so a queue mixing 'fastest' and 'accurate' jobs
# does not thrash between two model loads.
_WHISPER_MODELS: dict = {}
_WHISPER_DEVICE: str = None


def _resolve_whisper_device(want_gpu: bool = True) -> str:
    """
    Returns 'cuda' when a usable CUDA device is present, else 'cpu'.

    Resolved once and cached. A CPU-only build of torch is common on
    Windows laptops even when the GPU is capable, and asking for 'cuda'
    there raises instead of falling back - which is why this probes rather
    than assuming.

    The probe itself lives in ingestion_modes.transcription_device() so the
    profile the UI previews and the device used here are the same fact read
    from one implementation. This used to be a second, independent probe,
    which meant the queue form could promise GPU transcription that this
    function then silently refused to use.
    """
    global _WHISPER_DEVICE
    if not want_gpu:
        return 'cpu'
    if _WHISPER_DEVICE is None:
        from backend.modules.ingestion_modes import transcription_device
        _WHISPER_DEVICE = transcription_device() or 'cpu'
    if _WHISPER_DEVICE == 'cuda':
        try:
            import torch
            print(
                f"[MEDIA] Whisper will use GPU: "
                f"{torch.cuda.get_device_name(0)}")
        except Exception:
            pass
    else:
        print(
            "[MEDIA] No CUDA device available to torch - "
            "transcription will run on the CPU."
        )
    return _WHISPER_DEVICE


def _get_whisper_model(model_name: str = None, use_gpu: bool = True):
    """
    Loads the requested Whisper model on first use and caches it per size.

    The size used to be hardcoded to 'tiny', which meant the "accurate"
    profile could never actually transcribe accurately, and the model was
    always loaded on the CPU even on a box with a discrete GPU. Both are
    now driven by the ingestion mode.
    """
    global _WHISPER_MODEL
    size = model_name or os.environ.get("WHISPER_MODEL", "tiny")
    device = _resolve_whisper_device(use_gpu)

    cached = _WHISPER_MODELS.get((size, device))
    if cached is not None:
        return cached

    print(f"[MEDIA] Loading Whisper '{size}' on {device}…")
    model = whisper.load_model(size, device=device)
    _WHISPER_MODELS[(size, device)] = model
    # Back-compat: some callers still read the single-model global.
    _WHISPER_MODEL = model
    print(f"[MEDIA] Whisper '{size}' ready on {device}")
    return model


# ── Office document extractors ────────────

def extract_docx(data: bytes) -> str:
    """
    Extracts text from .docx files including
    all paragraphs and table cell contents.
    """
    if not DOCX_AVAILABLE:
        return ""
    try:
        import io
        doc = DocxDoc(io.BytesIO(data))
        paragraphs = []
        for para in doc.paragraphs:
            t = para.text.strip()
            if t:
                paragraphs.append(t)
        # Extract tables
        for table in doc.tables:
            for row in table.rows:
                row_text = ' | '.join(
                    cell.text.strip()
                    for cell in row.cells
                    if cell.text.strip()
                )
                if row_text:
                    paragraphs.append(row_text)
        return '\n'.join(paragraphs)[:50000]
    except Exception as e:
        print(f"[MEDIA] docx extraction error: {e}")
        return ""


def extract_xlsx(data: bytes) -> str:
    """
    Extracts text from .xlsx files.
    Iterates up to 1000 rows per sheet,
    all sheets included with a header.
    """
    if not XLSX_AVAILABLE:
        return ""
    try:
        import io
        wb = openpyxl.load_workbook(
            io.BytesIO(data),
            read_only=True,
            data_only=True
        )
        text_parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            text_parts.append(
                f"[Sheet: {sheet_name}]")
            row_count = 0
            for row in ws.iter_rows(
                    values_only=True):
                if row_count >= 1000:
                    break
                row_text = ' | '.join(
                    str(cell)
                    for cell in row
                    if cell is not None
                    and str(cell).strip()
                )
                if row_text:
                    text_parts.append(row_text)
                    row_count += 1
        wb.close()
        return '\n'.join(text_parts)[:50000]
    except Exception as e:
        print(f"[MEDIA] xlsx extraction error: {e}")
        return ""


def extract_pptx(data: bytes) -> str:
    """
    Extracts text from .pptx files.
    Includes slide numbers and all shape text.
    """
    if not PPTX_AVAILABLE:
        return ""
    try:
        import io
        prs = Presentation(io.BytesIO(data))
        text_parts = []
        for i, slide in enumerate(prs.slides, 1):
            text_parts.append(
                f"--- Slide {i} ---")
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    t = shape.text.strip()
                    if t:
                        text_parts.append(t)
        return '\n'.join(text_parts)[:50000]
    except Exception as e:
        print(f"[MEDIA] pptx extraction error: {e}")
        return ""


# ── Email extractors ──────────────────────

def extract_eml(data: bytes) -> str:
    """
    Extracts headers and body from RFC 2822
    .eml email files using the standard
    library email module.
    """
    try:
        msg = email_lib.message_from_bytes(
            data,
            policy=email_policy.default
        )
        parts = []
        # Extract key headers
        for header in [
            'From', 'To', 'Cc', 'Bcc',
            'Subject', 'Date',
            'Reply-To', 'Message-ID'
        ]:
            val = msg.get(header)
            if val:
                parts.append(f"{header}: {val}")
        parts.append("")

        # Extract body text
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == 'text/plain':
                    try:
                        body = part.get_payload(
                            decode=True
                        ).decode('utf-8',
                                 errors='ignore')
                        parts.append(body)
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_payload(
                    decode=True
                ).decode('utf-8', errors='ignore')
                parts.append(body)
            except Exception:
                pass

        return '\n'.join(parts)[:50000]
    except Exception as e:
        print(f"[MEDIA] eml extraction error: {e}")
        return ""


def extract_msg_file(data: bytes,
                     temp_dir: str) -> str:
    """
    Extracts text from Outlook .msg files
    using the extract-msg library.
    Writes to a temp file (library requires
    a file path, not bytes).
    """
    if not MSG_AVAILABLE:
        return ""
    tmp_path = None
    try:
        tmp_path = os.path.join(
            temp_dir, f"tmp_{os.getpid()}.msg")
        with open(tmp_path, 'wb') as f:
            f.write(data)
        msg_obj = extract_msg.Message(tmp_path)
        parts = []
        if msg_obj.sender:
            parts.append(f"From: {msg_obj.sender}")
        if msg_obj.to:
            parts.append(f"To: {msg_obj.to}")
        if msg_obj.cc:
            parts.append(f"Cc: {msg_obj.cc}")
        if msg_obj.subject:
            parts.append(
                f"Subject: {msg_obj.subject}")
        if msg_obj.date:
            parts.append(f"Date: {msg_obj.date}")
        parts.append("")
        if msg_obj.body:
            parts.append(msg_obj.body)
        return '\n'.join(parts)[:50000]
    except Exception as e:
        print(f"[MEDIA] .msg extraction error: {e}")
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ── Image OCR ─────────────────────────────

def extract_image_ocr(data: bytes) -> str:
    """
    Performs OCR on image bytes using Tesseract.
    Extracts visible text from screenshots,
    scanned documents, photos of documents.
    Returns empty string if Tesseract is not
    installed or OCR yields no text.
    """
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        import io
        img = PILImage.open(io.BytesIO(data))
        # Convert to a mode Tesseract can handle
        if img.mode not in ('RGB', 'L', 'RGBA'):
            img = img.convert('RGB')
        text = pytesseract.image_to_string(
            img, timeout=30)
        clean = '\n'.join(
            line.strip()
            for line in text.splitlines()
            if line.strip()
        )
        return clean[:20000]
    except Exception as e:
        print(f"[MEDIA] OCR error: {e}")
        return ""


# ── Audio transcription ───────────────────

def extract_audio_transcript(data: bytes,
                              filename: str,
                              temp_dir: str,
                              model_name: str = None,
                              use_gpu: bool = True) -> str:
    """
    Transcribes an audio file using Whisper.
    - Lazy-loads the requested model on first call
    - Runs on the GPU when torch reports a usable CUDA device
    - Skips files longer than MAX_AUDIO_DURATION_SECONDS
    - Returns a placeholder if Whisper is not installed
    - Temp files are cleaned up in a finally block
    """
    if not WHISPER_AVAILABLE:
        return (
            f"[Audio file: {filename}. "
            f"Whisper not installed — "
            f"transcription unavailable. "
            f"Install: pip install openai-whisper "
            f"and brew install ffmpeg]"
        )

    tmp_path = None
    try:
        ext = os.path.splitext(
            filename.lower())[1] or '.audio'
        tmp_path = os.path.join(
            temp_dir,
            f"audio_{os.getpid()}{ext}")
        with open(tmp_path, 'wb') as f:
            f.write(data)

        # Check duration with ffprobe first
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet',
                 '-print_format', 'json',
                 '-show_streams', tmp_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                for stream in info.get(
                        'streams', []):
                    dur = float(
                        stream.get('duration', 0))
                    if dur > \
                            MAX_AUDIO_DURATION_SECONDS:
                        return (
                            f"[Audio file: {filename} "
                            f"({dur:.0f}s). Exceeds "
                            f"{MAX_AUDIO_DURATION_SECONDS}s "
                            f"limit — not transcribed.]"
                        )
        except Exception:
            pass  # ffprobe not available, continue

        print(f"[MEDIA] Transcribing: {filename}…")
        model = _get_whisper_model(model_name, use_gpu)
        # fp16 is only safe on CUDA. Half precision on CPU is either
        # unsupported or silently wrong, so it is tied to the device.
        device = _resolve_whisper_device(use_gpu)
        result = model.transcribe(
            tmp_path,
            fp16=(device == 'cuda'),
            language=None       # Auto-detect language
        )
        transcript = result.get("text", "").strip()
        lang = result.get("language", "unknown")
        return (
            f"[Audio Transcript — Language: {lang}]\n\n"
            f"{transcript}"
        )[:50000]

    except Exception as e:
        print(f"[MEDIA] Audio transcription error: {e}")
        return (
            f"[Audio transcription failed: "
            f"{str(e)[:120]}]"
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ── Video extraction ──────────────────────

def extract_video(data: bytes,
                  filename: str,
                  temp_dir: str,
                  whisper_model: str = None,
                  whisper_gpu: bool = True) -> tuple:
    """
    Extracts forensic metadata and audio
    transcript from a video file.

    Steps:
      1. Write to temp file
      2. Run ffprobe for container metadata
         (duration, creation time, GPS, etc.)
      3. Extract audio track with ffmpeg → WAV
      4. Transcribe with Whisper
      5. Clean up all temp files

    whisper_model / whisper_gpu come from the ingestion mode.

    Returns (text: str, metadata: dict)
    """
    parts = []
    metadata = {}
    tmp_path = None
    audio_tmp = None
    failures = []

    # ---- can this reader run at all? -----------------------------------
    #
    # Measured on a box with no ffmpeg: every step below raised
    #     [MEDIA] ffprobe error: [WinError 2] The system cannot find the file
    #     [MEDIA] Video audio extraction error: [WinError 2] ...
    # both were PRINTED and execution continued, so extract_video returned
    # ''. The caller was then told nothing about why.
    #
    # That empty string is the §18 defect: a video that uploads successfully and
    # yields no text, with the reason in a log nobody reads. It is also what
    # forced a false label downstream -- the empty-result guard in
    # forensic_ingestion has to choose a type, and 'unsupported' is wrong,
    # because .flv IS an accepted upload and IS in the estimator's video set.
    # "My reader could not run" and "this format is not supported" are
    # different facts and the app must not report the second when it means the
    # first (§16: never report a value you did not measure).
    #
    # So probe first and, when the tools are absent, say so in the artifact
    # text with the install command. This mirrors what
    # extract_audio_transcript has always done for a missing Whisper -- which is
    # why .aiff and .wma come back with 84 bytes of honest placeholder and keep
    # their type, and only the two video formats were coming back empty.
    missing = [t for t in ('ffprobe', 'ffmpeg')
               if shutil.which(t) is None]
    if missing:
        return (
            f"[Video file: {filename}. No video could be read: "
            f"{' and '.join(missing)} "
            f"{'are' if len(missing) > 1 else 'is'} not on PATH, so no "
            f"container metadata and no audio track were extracted and "
            f"nothing was transcribed. The file is a supported type and was "
            f"stored in full -- it simply was not read. "
            f"Install: winget install Gyan.FFmpeg (Windows) | "
            f"apt install ffmpeg (Debian/Ubuntu) | brew install ffmpeg (macOS) "
            f"-- then re-ingest to extract the audio track.]",
            {}
        )

    try:
        ext = os.path.splitext(
            filename.lower())[1] or '.video'
        tmp_path = os.path.join(
            temp_dir,
            f"video_{os.getpid()}{ext}")
        with open(tmp_path, 'wb') as f:
            f.write(data)

        # Step 1: Extract metadata with ffprobe
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet',
                 '-print_format', 'json',
                 '-show_format', '-show_streams',
                 tmp_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                fmt = info.get('format', {})
                tags = fmt.get('tags', {})

                metadata = {
                    'duration_seconds': float(
                        fmt.get('duration', 0)),
                    'size_bytes': int(
                        fmt.get('size', 0)),
                    'format_name': fmt.get(
                        'format_name'),
                    'creation_time': tags.get(
                        'creation_time'),
                    'location': tags.get(
                        'location'),
                    'artist': tags.get('artist'),
                    'title': tags.get('title'),
                    'comment': tags.get('comment'),
                    'encoder': tags.get('encoder'),
                }

                parts.append("[Video Metadata]")
                dur = metadata['duration_seconds']
                parts.append(
                    f"Duration: {dur:.1f}s "
                    f"({dur / 60:.1f} min)")
                if metadata['format_name']:
                    parts.append(
                        f"Format: "
                        f"{metadata['format_name']}")
                if metadata['creation_time']:
                    parts.append(
                        f"Created: "
                        f"{metadata['creation_time']}")
                if metadata['location']:
                    parts.append(
                        f"GPS Location: "
                        f"{metadata['location']}")
                if metadata['title']:
                    parts.append(
                        f"Title: {metadata['title']}")
                if metadata['comment']:
                    parts.append(
                        f"Comment: "
                        f"{metadata['comment']}")
                if metadata['artist']:
                    parts.append(
                        f"Artist: "
                        f"{metadata['artist']}")

                # Per-stream info
                for stream in info.get(
                        'streams', []):
                    codec_type = stream.get(
                        'codec_type', '')
                    codec_name = stream.get(
                        'codec_name', '')
                    if codec_type == 'video':
                        w = stream.get('width', 0)
                        h = stream.get('height', 0)
                        fps = stream.get(
                            'r_frame_rate', '')
                        parts.append(
                            f"Video Stream: "
                            f"{codec_name} "
                            f"{w}x{h} @ {fps}")
                    elif codec_type == 'audio':
                        sr = stream.get(
                            'sample_rate', '')
                        ch = stream.get(
                            'channels', '')
                        parts.append(
                            f"Audio Stream: "
                            f"{codec_name} "
                            f"{sr}Hz {ch}ch")

        except Exception as e:
            print(f"[MEDIA] ffprobe error: {e}")
            failures.append(f"ffprobe could not read the container: {e}")

        # Step 2: Extract audio → transcribe
        if WHISPER_AVAILABLE:
            audio_tmp = os.path.join(
                temp_dir,
                f"video_audio_{os.getpid()}.wav")
            try:
                subprocess.run(
                    ['ffmpeg', '-i', tmp_path,
                     '-vn',
                     '-acodec', 'pcm_s16le',
                     '-ar', '16000',
                     '-ac', '1',
                     '-y', audio_tmp],
                    capture_output=True,
                    timeout=300
                )
                if os.path.exists(audio_tmp):
                    with open(audio_tmp, 'rb') as f:
                        audio_data = f.read()
                    if audio_data:
                        transcript = \
                            extract_audio_transcript(
                                audio_data,
                                "extracted_audio.wav",
                                temp_dir,
                                model_name=whisper_model,
                                use_gpu=whisper_gpu
                            )
                        if transcript:
                            parts.append(
                                "\n[Audio Transcript]")
                            parts.append(transcript)
            except Exception as e:
                print(
                    f"[MEDIA] Video audio "
                    f"extraction error: {e}")
                failures.append(
                    f"the audio track could not be extracted: {e}")

    except Exception as e:
        print(f"[MEDIA] Video extraction error: {e}")
        failures.append(f"the video could not be processed: {e}")
    finally:
        # Clean up temp files in all cases
        for p in [tmp_path, audio_tmp]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    # The tools ran and still produced nothing. That is a real measurement, and
    # it needs to reach the investigator too -- an artifact whose text is empty
    # reads as "nothing of interest here" rather than "we could not read it".
    if not parts:
        detail = ("; ".join(failures) if failures else
                  "ffprobe reported no streams and no audio track was found")
        parts.append(
            f"[Video file: {filename}. The video tools ran but produced "
            f"nothing: {detail}. The file is stored in full and is a supported "
            f"type, but nothing could be read from it. It may be corrupt, may "
            f"carry no audio stream, or may use a codec this build cannot "
            f"decode.]")

    return '\n'.join(parts), metadata


# ── Browser History extraction ──────────────

BROWSER_DB_NAMES = {
    'history': 'chrome_history',
    'places.sqlite': 'firefox_history',
    'history.db': 'safari_history',
    'webdata': 'chrome_webdata'
}

def extract_browser_history(
        data: bytes,
        filename: str,
        temp_dir: str) -> str:
    """
    Detects and extracts browser history
    from known browser SQLite database files.
    Returns formatted history text.
    """
    import sqlite3

    filename_lower = filename.lower()
    browser_type = None
    for known_name, btype in \
            BROWSER_DB_NAMES.items():
        if known_name in filename_lower:
            browser_type = btype
            break

    if not browser_type:
        return ""

    try:
        tmp = os.path.join(
            temp_dir,
            f"browser_tmp_{filename}")
        with open(tmp, 'wb') as f:
            f.write(data)

        conn = sqlite3.connect(tmp)
        parts = [
            f"[{browser_type.replace('_', ' ').title()} History]"
        ]

        if 'chrome' in browser_type:
            try:
                cur = conn.execute("""
                    SELECT url, title,
                           visit_count,
                           last_visit_time
                    FROM urls
                    ORDER BY last_visit_time
                    DESC LIMIT 500
                """)
                for row in cur.fetchall():
                    url, title, count, ts = row
                    # Chrome timestamp is
                    # microseconds since
                    # Jan 1, 1601
                    if ts:
                        import datetime
                        epoch_delta = (
                            datetime.datetime(
                                1601,1,1) -
                            datetime.datetime(
                                1970,1,1)
                        ).total_seconds()
                        real_ts = (
                            ts/1000000 +
                            epoch_delta
                        )
                        try:
                            dt = datetime\
                                .datetime\
                                .utcfromtimestamp(
                                -epoch_delta +
                                ts/1000000
                            )
                            ts_str = str(dt)[
                                :19]
                        except:
                            ts_str = str(ts)
                    else:
                        ts_str = "Unknown"
                    parts.append(
                        f"{ts_str} | "
                        f"Visits:{count} | "
                        f"{url} | {title or ''}"
                    )
            except Exception as e:
                parts.append(
                    f"Error: {e}")

        elif 'firefox' in browser_type:
            try:
                cur = conn.execute("""
                    SELECT url, title,
                           visit_count,
                           last_visit_date
                    FROM moz_places
                    WHERE visit_count > 0
                    ORDER BY last_visit_date
                    DESC LIMIT 500
                """)
                for row in cur.fetchall():
                    url, title, count, ts = row
                    if ts:
                        # Firefox: microseconds
                        # since epoch
                        dt_ts = ts / 1000000
                        try:
                            import datetime
                            dt = datetime\
                                .datetime\
                                .utcfromtimestamp(
                                dt_ts)
                            ts_str = str(dt)[
                                :19]
                        except:
                            ts_str = str(ts)
                    else:
                        ts_str = "Unknown"
                    parts.append(
                        f"{ts_str} | "
                        f"Visits:{count} | "
                        f"{url} | {title or ''}"
                    )
            except Exception as e:
                parts.append(
                    f"Error: {e}")

        conn.close()
        os.remove(tmp)
        return '\n'.join(parts)[:50000]

    except Exception as e:
        print(f"[MEDIA] Browser history "
              f"error: {e}")
        return ""


# ── Main dispatch ─────────────────────────

def extract_media(data: bytes,
                  filename: str,
                  temp_dir: str,
                  run_ocr: bool = True,
                  whisper_model: str = None,
                  whisper_gpu: bool = True) -> tuple:
    """
    Main entry point for multimedia extraction.
    Routes to the appropriate extractor based
    on file extension.

    run_ocr / whisper_model / whisper_gpu are supplied by the ingestion
    mode, so the 'fastest' profile skips OCR and the 'accurate' profile
    transcribes with a larger model, on the GPU when one is available.

    Returns:
        (extracted_text: str, media_type: str)

    media_type values:
        docx | xlsx | pptx |
        audio | video | ocr | email |
        exif | unsupported
    """
    ext = os.path.splitext(filename.lower())[1]

    # Office documents
    if ext in {'.docx', '.doc'}:
        return extract_docx(data), 'docx'

    if ext in {'.xlsx', '.xls'}:
        return extract_xlsx(data), 'xlsx'

    if ext in {'.pptx', '.ppt'}:
        return extract_pptx(data), 'pptx'

    # Email files
    if ext == '.eml':
        return extract_eml(data), 'email'

    if ext == '.msg':
        return extract_msg_file(
            data, temp_dir), 'email'

    # Audio files
    if ext in AUDIO_EXTENSIONS:
        return (
            extract_audio_transcript(
                data, filename, temp_dir,
                model_name=whisper_model,
                use_gpu=whisper_gpu),
            'audio'
        )

    # Video files
    if ext in VIDEO_EXTENSIONS:
        text, _meta = extract_video(
            data, filename, temp_dir,
            whisper_model=whisper_model,
            whisper_gpu=whisper_gpu)
        return text, 'video'

    # Images — OCR first, then EXIF fallback
    if ext in IMAGE_EXTENSIONS:
        if not run_ocr:
            return "", 'exif'   # caller handles EXIF
        ocr_text = extract_image_ocr(data)
        if ocr_text and len(
                ocr_text.strip()) > 20:
            return ocr_text, 'ocr'
        return "", 'exif'  # caller handles EXIF

    # Registry hive detection (by filename, not extension)
    if REGISTRY_PARSER_AVAILABLE and is_registry_hive(filename):
        return parse_registry_hive(data, filename, temp_dir)

    return "", 'unsupported'


def get_media_capabilities() -> dict:
    """
    Returns a dict indicating which media
    extraction features are currently active
    based on installed system libraries.
    Used by /api/media/capabilities endpoint.
    """
    return {
        "docx": DOCX_AVAILABLE,
        "xlsx": XLSX_AVAILABLE,
        "pptx": PPTX_AVAILABLE,
        "ocr_images": TESSERACT_AVAILABLE,
        "audio_transcription": WHISPER_AVAILABLE,
        "video_transcription": WHISPER_AVAILABLE,
        "email_eml": True,        # stdlib — always on
        "email_msg": MSG_AVAILABLE,
    }
