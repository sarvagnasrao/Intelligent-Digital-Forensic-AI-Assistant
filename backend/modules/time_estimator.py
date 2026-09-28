import os
from backend.modules.file_formats import category_for

# Seconds per MB for each file type
# Based on M1 Mac 8GB benchmarks
TIME_PER_MB = {
    # Fast text extraction
    '.txt':  0.05,
    '.log':  0.05,
    '.csv':  0.05,
    '.tsv':  0.05,
    '.xml':  0.1,
    '.json': 0.05,
    '.jsonl': 0.05,
    '.ndjson': 0.05,
    '.html': 0.1,
    '.htm': 0.1,
    '.xhtml': 0.1,
    '.eml':  0.1,
    '.msg':  0.2,

    # Medium — structured parsing
    '.pdf':  6.0,   # pdfminer is slow
    '.rtf':  0.1,
    '.docx': 0.5,
    '.doc':  0.8,
    '.xlsx': 0.4,
    '.xls':  0.6,
    '.pptx': 0.5,
    '.ppt':  0.7,

    # Slow — AI processing
    '.jpg':  2.0,   # Tesseract OCR
    '.jpeg': 2.0,
    '.png':  2.0,
    '.tiff': 3.0,
    '.tif':  3.0,
    '.bmp':  2.5,
    '.gif':  2.5,   # single frame is all we OCR
    '.webp': 2.0,

    # Very slow — Whisper transcription
    # Audio: roughly 15 sec per minute
    # of audio = 0.25x realtime
    '.mp3':  15.0,
    '.wav':  12.0,
    '.m4a':  15.0,
    '.flac': 12.0,
    '.ogg':  15.0,
    '.aac':  15.0,
    '.wma':  15.0,
    '.aiff': 12.0,

    # Video: extract audio + transcribe
    '.mp4':  18.0,
    '.avi':  20.0,
    '.mov':  18.0,
    '.mkv':  20.0,
    '.wmv':  22.0,
    '.flv':  22.0,
    '.webm': 18.0,
    '.m4v':  18.0,
}

# Categories whose files are read as text or parsed cheaply, so an extension
# missing from TIME_PER_MB above still gets a realistic rate. Without this a
# .sql or .yaml fell to the 1.0 s/MB default and was quoted at 20x the .txt
# sitting beside it, for work that is a single decode.
_CHEAP_CATEGORIES = {
    'document', 'text', 'data', 'markup', 'config',
    'code', 'subtitle', 'database', 'email', 'office',
}

# Disk images: seconds per GB
# (filesystem scan + content extraction)
TIME_PER_GB_DISK_IMAGE = 1800
# 30 minutes per GB — conservative

DISK_IMAGE_EXTENSIONS = {
    '.e01', '.001', '.dd',
    '.raw', '.img'
}

# Embedding overhead: seconds per MB
# of extracted text (Qdrant + nomic)
EMBEDDING_OVERHEAD_PER_MB = 2.0

def estimate_ingestion_time(
        filename: str,
        file_size_bytes: int,
        cpu_throttle_percent: int = 100,
        mode_key: str = None
) -> dict:
    """
    Estimates ingestion time for a file.
    Returns dict with seconds estimate
    and human-readable breakdown.

    mode_key selects an ingestion profile ('fastest' | 'normal' |
    'accurate'). It scales the estimate so the number the operator sees
    reflects the mode they actually picked, rather than always quoting the
    balanced case.
    """
    from backend.modules.ingestion_modes import (
        get_mode, MODE_TIME_FACTOR, DEFAULT_MODE)

    mode = get_mode(mode_key or DEFAULT_MODE)
    mode_key = mode["key"]
    mode_factor = MODE_TIME_FACTOR.get(mode_key, 1.0)

    ext = os.path.splitext(filename.lower())[1]
    size_mb = file_size_bytes / (1024 * 1024)
    size_gb = size_mb / 1024

    # The format category comes from the shared policy module, so a newly
    # accepted media format is estimated as media on the day it is added
    # rather than silently falling through to the document branch. The old
    # hardcoded sets here omitted .gif, .webp, .tif, .wma, .aiff, .flv,
    # .webm and .m4v - so an 80 MB webm was quoted as if it would produce
    # 64 MB of transcript to embed, which is a fabricated number rather than
    # a rough one.
    category_key = category_for(filename)

    # Calculate base extraction time
    if category_key == 'disk_image':
        # Disk images: per-GB rate
        extraction_seconds = size_gb * TIME_PER_GB_DISK_IMAGE
        # Assume ~10% of disk is text content
        estimated_text_mb = size_mb * 0.1
        category = "disk_image"
    else:
        if ext in TIME_PER_MB:
            rate = TIME_PER_MB[ext]
        elif category_key in _CHEAP_CATEGORIES:
            rate = 0.05
        else:
            rate = 1.0
        extraction_seconds = size_mb * rate
        # Estimate text output as fraction of input size
        if category_key in ('audio', 'video'):
            # Only the audio track is transcribed, and a transcript is a
            # tiny fraction of the file's bytes.
            estimated_text_mb = size_mb * 0.05
            category = "media"
        elif category_key == 'image':
            estimated_text_mb = size_mb * 0.02
            category = "image"
        else:
            estimated_text_mb = size_mb * 0.8
            category = "document"

    # Embedding time based on estimated text output
    embedding_seconds = estimated_text_mb * EMBEDDING_OVERHEAD_PER_MB

    # Graph building (roughly half of embedding time)
    graph_seconds = embedding_seconds * 0.5

    total_seconds = (
        extraction_seconds +
        embedding_seconds +
        graph_seconds)

    # Scale for the chosen profile. The per-MB table above is calibrated
    # against the 'normal' profile, so 'fastest' genuinely does less work
    # (no OCR, larger chunks, tiny transcription model) and 'accurate' does
    # more (deleted-file recovery, GPU transcription, small overlapping
    # chunks). Without this the estimate was identical for all three and an
    # operator picking 'accurate' had no idea what they were signing up for.
    total_seconds *= mode_factor

    # Apply throttle factor
    throttle_factor = (
        100 / max(cpu_throttle_percent, 10))
    total_seconds *= throttle_factor

    # Add minimum 10 seconds overhead
    total_seconds = max(10, total_seconds)

    return {
        "file": filename,
        "size_mb": round(size_mb, 1),
        "category": category,
        "ingestion_mode": mode_key,
        "mode_factor": mode_factor,
        "chunk_size": mode["chunk_size"],
        "extraction_seconds": round(
            extraction_seconds * throttle_factor * mode_factor),
        "embedding_seconds": round(
            embedding_seconds * throttle_factor * mode_factor),
        "graph_seconds": round(
            graph_seconds * throttle_factor * mode_factor),
        "total_seconds": round(total_seconds),
        "human_readable": _format_duration(round(total_seconds)),
        "throttle_applied": throttle_factor > 1.0,
        "note": (
            "Estimate is relative, not absolute: it scales the extracted "
            "text volume, the transcription model and the chunk count for "
            f"the '{mode_key}' profile. A machine already under load will "
            "also stretch it."
        )
    }

def estimate_queue_total(
        files: list[dict],
        cpu_throttle_percent: int = 100,
        mode_key: str = None
) -> dict:
    """
    Estimates total time for a list of
    files queued for ingestion.
    files: list of {filename, file_size_bytes}
    mode_key: a single profile applied to the whole batch, or None for the
    default. Per-file modes are summed correctly when every entry carries
    its own 'ingestion_mode' key.
    """
    estimates = []
    total_seconds = 0

    for f in files:
        est = estimate_ingestion_time(
            f["filename"],
            f["file_size_bytes"],
            cpu_throttle_percent,
            mode_key=f.get("ingestion_mode") or mode_key
        )
        estimates.append(est)
        total_seconds += est["total_seconds"]

    return {
        "files": estimates,
        "total_seconds": round(total_seconds),
        "total_human_readable": _format_duration(round(total_seconds)),
        "file_count": len(files),
        "recommendation": _get_recommendation(total_seconds, cpu_throttle_percent)
    }

def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"

def _get_recommendation(
        total_seconds: int,
        throttle: int) -> str:
    if total_seconds < 300:
        return "Quick ingestion — should complete in minutes."
    elif total_seconds < 3600:
        return "Medium ingestion — start when you have 30-60 minutes free."
    elif total_seconds < 14400:
        return "Long ingestion — consider running overnight or during a break."
    else:
        return (
            "Very long ingestion — strongly recommend running overnight "
            "with the screen saver on. Do not close the terminal or app."
        )
