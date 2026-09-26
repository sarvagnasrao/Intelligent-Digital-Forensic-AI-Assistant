"""
Ingestion profiles: three quality/time trade-offs, and a resource budget
that is derived from the machine actually running the job.

Why this module exists
----------------------
The queue used to carry only two knobs (cpu_throttle_percent and
min_free_ram_mb) whose defaults were hardcoded: a 2 GB RAM floor, a 70%
CPU ceiling and a "suggested budget" that branched on three hardcoded
tiers (8 / 16 / 32 GB). None of that described the machine in front of
the operator, and there was no way to ask for a slower-but-more-complete
pass over evidence.

Two things live here:

1. ``MODES`` - the three ingestion profiles. One definition each, read by
   the worker, the estimator and the UI, so a mode can never mean one
   thing on the backend and another in the browser.

2. ``suggest_budget`` - replaces the old tiered function. Everything is
   computed from the live probe: available RAM, physical/logical cores,
   whether the box is a laptop running on battery, and whether a discrete
   GPU is present. It also returns the *bounds* the RAM-floor control
   should use, which is what keeps the "Min Free RAM" slider in sync with
   the current device instead of being pinned to a hardcoded 8 GB.

Nothing here imports torch, and nothing here performs I/O beyond the
probe, so it stays cheap to call from a request handler.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from backend.modules.hardware_probe import get_hardware_spec


# ---------------------------------------------------------------------------
# The three ingestion modes
# ---------------------------------------------------------------------------
# Every field is consumed somewhere. Keeping them in one dict means adding a
# knob is a single edit and the UI can render whatever the mode says instead
# of hardcoding labels that drift out of sync.
#
#   chunk_size      characters per chunk fed to the vector store. Larger =
#                  fewer chunks to embed (faster) but coarser retrieval.
#   chunk_overlap   characters repeated between adjacent chunks so a
#                  sentence spanning a boundary is still retrievable.
#   embed_batch     chunks per embedding round-trip. Larger = better
#                  throughput, more peak RAM.
#   ocr             run Tesseract over images.
#   whisper_model   openai-whisper size: tiny | base | small | medium.
#   whisper_gpu     try to put Whisper on the GPU. Ignored when torch has
#                  no CUDA build, in which case extraction falls back to
#                  CPU automatically.
#   include_deleted forensic disk-image walk includes deleted entries.
#                  Substantially slower, materially more complete.
#   max_parallel    upper bound on files ingested at once by the worker.

MODES: Dict[str, Dict[str, Any]] = {
    "fastest": {
        "key": "fastest",
        "label": "Fastest",
        "tagline": "Quick triage",
        "description": (
            "No OCR, no deleted-file recovery and the smallest "
            "transcription model. Chunks are large, so there is less to "
            "embed. Use this to see what a piece of evidence contains "
            "before committing to a full pass."
        ),
        "accuracy": "Lowest",
        "speed": "Fastest",
        "chunk_size": 30000,
        "chunk_overlap": 0,
        "embed_batch": 256,
        "ocr": False,
        "whisper_model": "tiny",
        "whisper_gpu": False,
        "include_deleted": False,
        "max_parallel": 2,
    },
    "normal": {
        "key": "normal",
        "label": "Normal",
        "tagline": "Balanced",
        "description": (
            "OCR on, standard transcription model, no deleted-file "
            "recovery. This is the default and the right choice for "
            "routine casework."
        ),
        "accuracy": "Balanced",
        "speed": "Balanced",
        "chunk_size": 20000,
        "chunk_overlap": 0,
        "embed_batch": 128,
        "ocr": True,
        "whisper_model": "base",
        "whisper_gpu": True,
        "include_deleted": False,
        "max_parallel": 1,
    },
    "accurate": {
        "key": "accurate",
        "label": "Accurate",
        "tagline": "Forensic depth",
        "description": (
            "Adds deleted-file recovery from disk images, the large "
            "transcription model on the GPU, and small overlapping "
            "chunks for precise citation. Markedly slower, and the most "
            "complete result. Use before producing a report."
        ),
        "accuracy": "Highest",
        "speed": "Slowest",
        "chunk_size": 8000,
        "chunk_overlap": 400,
        "embed_batch": 64,
        "ocr": True,
        "whisper_model": "small",
        "whisper_gpu": True,
        "include_deleted": True,
        "max_parallel": 1,
    },
}

DEFAULT_MODE = "normal"

# Rough multipliers against the per-megabyte baseline in time_estimator.
# These are calibrated against the bundled model sizes rather than measured
# per-device, so they stay stable when the machine changes.
MODE_TIME_FACTOR: Dict[str, float] = {
    "fastest": 0.55,
    "normal": 1.0,
    "accurate": 2.6,
}


def mode_keys() -> list:
    return list(MODES.keys())


def get_mode(name: Optional[str]) -> Dict[str, Any]:
    """
    Returns a copy of the named mode, falling back to DEFAULT_MODE for
    anything unrecognised (including None and legacy rows written before
    the column existed).
    """
    key = (name or DEFAULT_MODE).strip().lower()
    mode = MODES.get(key)
    if mode is None:
        mode = MODES[DEFAULT_MODE]
    return dict(mode)


def describe_modes() -> list:
    """
    Mode list shaped for the UI: the knobs plus the prose the frontend
    renders, so the browser never hardcodes a label.
    """
    out = []
    for key in MODES:
        m = MODES[key]
        out.append({
            "key": m["key"],
            "label": m["label"],
            "tagline": m["tagline"],
            "description": m["description"],
            "accuracy": m["accuracy"],
            "speed": m["speed"],
            "time_factor": MODE_TIME_FACTOR.get(m["key"], 1.0),
            "includes_deleted_files": bool(m["include_deleted"]),
            "runs_ocr": bool(m["ocr"]),
            "whisper_model": m["whisper_model"],
        })
    return out


# ---------------------------------------------------------------------------
# Device-derived budget
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def suggest_budget(spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Derives ingestion limits from the live hardware probe.

    Replaces the previous implementation, which branched on three fixed RAM
    tiers and so reported "8GB" style advice on a 16 GB machine - and
    ignored battery state, core count and GPU presence entirely.

    Returns the legacy keys (``min_free_ram_mb``, ``cpu_throttle_percent``,
    ``batch_size``, ``description``) so existing callers keep working, plus
    the extra keys the UI needs.
    """
    spec = spec or get_hardware_spec()

    total_mb = int(spec.get("total_ram_mb") or 0)
    avail_mb = int(spec.get("available_ram_mb") or 0)
    phys_cores = int(spec.get("cpu_count_physical") or 0)
    log_cores = int(spec.get("cpu_count_logical") or 0)
    is_laptop = bool(spec.get("is_laptop"))
    on_ac = spec.get("on_ac")
    discrete_gpu = int(spec.get("gpu_discrete_count") or 0) > 0
    vram_mb = int(spec.get("gpu_vram_total_mb") or 0)

    if total_mb <= 0:                      # probe failed; be conservative
        total_mb = 8192
    if avail_mb <= 0:
        avail_mb = max(512, int(total_mb * 0.25))

    cores = phys_cores or max(1, log_cores // 2) or 1

    # ── RAM floor ────────────────────────────────────────────────────────
    # Keep a quarter of what is currently free, but never promise more than
    # 40% of installed RAM (a floor above that stalls the job forever on a
    # machine that is already under pressure).
    floor_mb = int(_clamp(avail_mb * 0.25, 512, total_mb * 0.40))
    floor_mb = max(256, (floor_mb // 256) * 256)      # round to 256 MB

    # ── CPU ceiling ───────────────────────────────────────────────────────
    # More cores -> more headroom before the machine feels loaded. A laptop
    # on battery is throttled by the OS anyway, so back off hard.
    if is_laptop and on_ac is False:
        cpu_pct = 50
    elif cores >= 8:
        cpu_pct = 100
    elif cores >= 4:
        cpu_pct = 90
    elif cores >= 2:
        cpu_pct = 75
    else:
        cpu_pct = 60

    # ── Embedding batch size ─────────────────────────────────────────────
    # Driven by free RAM first (this is what actually spikes), then cores.
    if avail_mb >= 8192 and cores >= 4:
        batch = 256
    elif avail_mb >= 4096:
        batch = 128
    else:
        batch = 64
    batch = max(32, min(256, batch))

    # ── Parallel file workers ────────────────────────────────────────────
    # Each concurrent file can hold a whole document plus its embedding
    # batch in memory, so gate on ~3 GB of headroom per worker.
    by_ram = int(avail_mb // 3072)
    by_cores = max(1, cores // 4)
    parallel = int(_clamp(min(by_ram, by_cores), 1, 4))

    # ── Controls the UI should offer ─────────────────────────────────────
    # The slider must never be able to express a floor above the RAM the
    # machine can actually give, and it needs to be able to express 0
    # (override, no floor) at the other end.
    ram_floor_max_mb = int(max(1024, min(avail_mb, total_mb) // 1024 * 1024))
    ram_floor_max_mb = max(1024, min(ram_floor_max_mb, 64 * 1024))
    ram_default_mb = int(_clamp(floor_mb, 0, ram_floor_max_mb))

    # ── Human-readable summary ───────────────────────────────────────────
    if is_laptop and on_ac is False:
        health = "laptop on battery - ingestion will be slow and may suspend"
    elif avail_mb < 1024:
        health = "very low free RAM - close other applications first"
    elif avail_mb < 2048:
        health = "low free RAM - ingestion may pause waiting for memory"
    elif not discrete_gpu and log_cores <= 4:
        health = "no discrete GPU - transcription runs on the CPU"
    else:
        health = "healthy"

    if discrete_gpu:
        accel = f"{spec.get('gpu_names', ['GPU'])[0]} ({vram_mb} MB VRAM)"
    else:
        accel = "CPU only"

    return {
        # legacy keys
        "min_free_ram_mb": ram_default_mb,
        "cpu_throttle_percent": cpu_pct,
        "batch_size": batch,
        "description": (
            f"{_pretty_ram(total_mb)} RAM, {cores}C/{log_cores}T, {accel}"
        ),
        # richer keys
        "health": health,
        "max_parallel_files": parallel,
        "ram_floor_min_mb": 0,
        "ram_floor_max_mb": ram_floor_max_mb,
        "ram_floor_default_mb": ram_default_mb,
        "cpu_min_percent": 10,
        "cpu_max_percent": 100,
        "total_ram_mb": total_mb,
        "available_ram_mb": avail_mb,
        "cpu_count_physical": cores,
        "cpu_count_logical": log_cores,
        "gpu_acceleration": accel,
        "has_discrete_gpu": discrete_gpu,
        "is_laptop": is_laptop,
        "on_ac": on_ac,
    }


def _pretty_ram(total_mb: int) -> str:
    if total_mb >= 1024 * 40:
        return f"{total_mb // 1024} GB"
    return f"{total_mb / 1024:.1f} GB"


# ── Transcription device ───────────────────────────────────────
# A GPU being present in the hardware inventory is not the same thing as
# torch being able to use it. A CPU-only torch build is the normal case on
# a fresh Windows install, and asking it for 'cuda' raises rather than
# falling back. So the flag a profile advertises has to come from torch,
# not from the device list, or the UI promises GPU transcription that will
# silently never happen.
_TRANSCRIPTION_DEVICE: Optional[str] = None


def transcription_device() -> Optional[str]:
    """
    'cuda' when torch reports a usable CUDA device, else 'cpu'.

    Probed once and cached. The extraction path and the profile preview
    both call this, so the badge the operator sees and the device the job
    actually uses cannot disagree.
    """
    global _TRANSCRIPTION_DEVICE
    if _TRANSCRIPTION_DEVICE is not None:
        return _TRANSCRIPTION_DEVICE
    try:
        import torch
        _TRANSCRIPTION_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        print(f"[MODES] torch CUDA probe failed ({e}) - no acceleration.")
        _TRANSCRIPTION_DEVICE = "cpu"
    return _TRANSCRIPTION_DEVICE


def resolve_mode_for_device(
        mode_name: Optional[str],
        spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns the effective mode after applying hard device limits.

    The only downgrade applied here is Whisper size when the machine cannot
    host it: a 16 GB box asking for "accurate" would otherwise stall for
    the whole job loading a model it cannot page in. Chunking, OCR and
    deleted-file recovery are never silently dropped - the operator asked
    for them and they are what makes the pass accurate.
    """
    mode = get_mode(mode_name)
    spec = spec or get_hardware_spec()

    avail_mb = int(spec.get("available_ram_mb") or 0)
    warnings: list = []

    # Whisper model sizes need roughly this much RAM to stay responsive.
    whisper_floor = {"tiny": 1024, "base": 2048, "small": 4096, "medium": 8192}
    need = whisper_floor.get(mode["whisper_model"], 2048)
    if avail_mb and avail_mb < need:
        for candidate in ("base", "tiny"):
            if whisper_floor.get(candidate, 99999) <= avail_mb:
                warnings.append(
                    f"Only {avail_mb} MB RAM free, so transcription dropped "
                    f"from '{mode['whisper_model']}' to '{candidate}'."
                )
                mode["whisper_model"] = candidate
                break

    # A parallel worker that cannot fit gets clamped rather than OOM-killed.
    budget = suggest_budget(spec)
    if mode["max_parallel"] > budget["max_parallel_files"]:
        warnings.append(
            f"Clamped to {budget['max_parallel_files']} concurrent file(s) "
            f"to stay within {avail_mb} MB free RAM."
        )
        mode["max_parallel"] = budget["max_parallel_files"]

    if not budget["has_discrete_gpu"] and mode["whisper_gpu"]:
        mode["whisper_gpu"] = False
        warnings.append(
            "No discrete GPU detected, so transcription runs on the CPU."
        )
    elif mode["whisper_gpu"] and transcription_device() != "cuda":
        # A discrete GPU exists but torch cannot drive it (the usual cause is
        # a CPU-only torch build). Say so, rather than showing a "(GPU)" tag
        # that turns out to be false the first time an audio file is queued.
        mode["whisper_gpu"] = False
        warnings.append(
            f"{budget['gpu_acceleration']} is present but torch reports no "
            f"usable CUDA device, so transcription runs on the CPU. "
            f"Install a CUDA build of torch to enable GPU transcription."
        )

    mode["warnings"] = warnings
    mode["time_factor"] = MODE_TIME_FACTOR.get(mode["key"], 1.0)
    return mode
