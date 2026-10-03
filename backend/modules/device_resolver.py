"""
Device resolver for SentenceTransformer embeddings.

Why this module exists
----------------------
`vector_store._load_embed_model()` used to construct `SentenceTransformer`
with NO device= argument, defaulting to CPU even where a GPU exists. It also
called `torch.set_num_threads(os.cpu_count())` at import time — hardcoding
the logical core count, ignoring that hyperthreaded siblings can hurt BLAS
throughput on some hardware, and fighting the resource governor.

This module provides a single, measured, cached decision:
  * Detect available devices (CUDA, ROCm, MPS, CPU)
  * Benchmark encode throughput on each (one-time, at first use)
  * Pick the fastest configuration
  * Return (device_string, thread_count) for the embedder load

The decision is cached per-process because device topology doesn't change
at runtime. A forced re-benchmark is available for tests.

Key design points:
  * CUDA and ROCm both appear as `torch.cuda` devices; ROCm is identified by
    `torch.version.hip` being set. The device string is `cuda:0` for both.
  * MPS requires `PYTORCH_ENABLE_MPS_FALLBACK=1` for op coverage at small
    batch sizes, and is often SLOWER than CPU on small batches — we benchmark
    it rather than assuming.
  * CPU thread count is benchmarked at 1, physical cores, and logical cores;
    the fastest wins. Physical core count is estimated as logical // 2.
  * The benchmark uses 700-char chunks at the production stride (580) and
    batch_size=64 to match the real ingestion path.
  * Results are cached in memory; a corrupt/absent cache falls back to a
    conservative CPU default rather than failing.
"""
from __future__ import annotations

import os
import platform
import time
from functools import lru_cache
from typing import Optional, Tuple

import torch

# Module-level cache for the resolved device config
_resolved_device: Optional[Tuple[str, int]] = None
_resolve_failed = False


def _estimate_physical_cores() -> int:
    """Estimate physical core count. Fallback to logical // 2."""
    logical = os.cpu_count() or 2
    # Windows: try to get physical count from WMI via psutil if available
    try:
        import psutil
        return psutil.cpu_count(logical=False) or (logical // 2)
    except Exception:
        return max(1, logical // 2)


def _build_benchmark_chunks() -> list[str]:
    """Build ~73 chunks at 700/120 stride like the real ingestion corpus."""
    seed = (
        "2024-11-03T09:14:22Z 198.51.100.47 ALLOW tcp 443 10.20.14.9 "
        "employee-badge-nightowl session-opened; approver A. Tanaka; "
        "transfer T-90333 duplicate reversed Halcyon Freight LLC 1.25M\n"
    )
    text = (seed * 1000)[:42273]
    chunks, start = [], 0
    while start < len(text):
        piece = text[start:start + 700]
        if len(piece.strip()) > 20:
            chunks.append(piece)
        start += 580
    return chunks


def _benchmark_device(device_str: str, threads: Optional[int] = None) -> float:
    """
    Benchmark encode throughput on a device. Returns chunks/second.
    Raises on failure.
    """
    from sentence_transformers import SentenceTransformer

    device = torch.device(device_str)
    if device.type == "cpu" and threads:
        torch.set_num_threads(threads)

    model = SentenceTransformer("all-MiniLM-L6-v2", device=device)

    chunks = _build_benchmark_chunks()

    # Warm-up
    model.encode(chunks[:8], batch_size=8, show_progress_bar=False)

    # Timed runs (3, take best)
    best = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        model.encode(chunks, batch_size=64, convert_to_numpy=True,
                     normalize_embeddings=True, show_progress_bar=False)
        elapsed = time.perf_counter() - t0
        if elapsed < best:
            best = elapsed

    return len(chunks) / best


def _detect_available_devices() -> list[tuple[str, str]]:
    """
    Returns list of (device_string, label) for available devices.
    Order is the preference order for benchmarking.
    """
    devices = []

    # CUDA (NVIDIA)
    if torch.cuda.is_available():
        devices.append(("cuda:0", "CUDA"))

    # ROCm (AMD) - appears as CUDA devices but with hip version
    if getattr(torch.version, "hip", None) and torch.cuda.is_available():
        # Already added as cuda:0 above; just note it's ROCm
        pass

    # MPS (Apple Silicon)
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        devices.append(("mps", "MPS"))

    # CPU - always available, benchmarked last as fallback
    devices.append(("cpu", "CPU"))

    return devices


def _benchmark_cpu_thread_counts() -> tuple[int, float]:
    """
    Benchmark CPU at 1 thread, physical cores, and logical cores.
    Returns (best_thread_count, best_chunks_per_sec).
    """
    logical = os.cpu_count() or 2
    physical = _estimate_physical_cores()

    candidates = [1, physical, logical]
    # Deduplicate and keep order
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    best_cps = 0.0
    best_threads = unique[-1]  # default to logical
    chunks = _build_benchmark_chunks()

    for threads in unique:
        try:
            torch.set_num_threads(threads)
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

            # Warm-up
            model.encode(chunks[:8], batch_size=8, show_progress_bar=False)

            best = float("inf")
            for _ in range(3):
                t0 = time.perf_counter()
                model.encode(chunks, batch_size=64, convert_to_numpy=True,
                             normalize_embeddings=True, show_progress_bar=False)
                elapsed = time.perf_counter() - t0
                if elapsed < best:
                    best = elapsed

            cps = len(chunks) / best
            print(f"[device_resolver] CPU threads={threads}: {cps:.1f} chunks/s")
            if cps > best_cps:
                best_cps = cps
                best_threads = threads
        except Exception as e:
            print(f"[device_resolver] CPU threads={threads} failed: {e}")

    return best_threads, best_cps


def resolve_device(force_rebenchmark: bool = False) -> tuple[str, int]:
    """
    Resolve the best device and thread count for SentenceTransformer.

    Returns (device_string, thread_count) where:
      - device_string: "cuda:0", "mps", or "cpu"
      - thread_count: int for torch.set_num_threads (ignored for non-CPU)

    The result is cached per-process. Set force_rebenchmark=True to re-run
    the benchmarks (used by tests).
    """
    global _resolved_device, _resolve_failed

    if _resolved_device is not None and not force_rebenchmark:
        return _resolved_device

    if _resolve_failed and not force_rebenchmark:
        # Previous resolution failed; return conservative default
        return "cpu", _estimate_physical_cores()

    print("[device_resolver] Detecting available devices...")
    available = _detect_available_devices()
    print(f"[device_resolver] Available: {[label for _, label in available]}")

    best_device = "cpu"
    best_threads = _estimate_physical_cores()
    best_cps = 0.0

    # Benchmark each non-CPU device
    for device_str, label in available:
        if device_str == "cpu":
            continue

        # MPS needs fallback env for op coverage at small batch
        if device_str == "mps":
            os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

        try:
            print(f"[device_resolver] Benchmarking {label} ({device_str})...")
            cps = _benchmark_device(device_str)
            print(f"[device_resolver]   {label}: {cps:.1f} chunks/s")
            if cps > best_cps:
                best_cps = cps
                best_device = device_str
        except Exception as e:
            print(f"[device_resolver]   {label} FAILED: {e}")

    # Benchmark CPU thread counts
    print("[device_resolver] Benchmarking CPU thread counts...")
    cpu_threads, cpu_cps = _benchmark_cpu_thread_counts()
    print(f"[device_resolver]   CPU best: {cpu_cps:.1f} chunks/s at {cpu_threads} threads")

    if cpu_cps > best_cps:
        best_cps = cpu_cps
        best_device = "cpu"
        best_threads = cpu_threads

    _resolved_device = (best_device, best_threads)
    print(f"[device_resolver] >>> SELECTED: {best_device} with {best_threads} threads ({best_cps:.1f} chunks/s)")
    return _resolved_device


def get_resolved_device() -> tuple[str, int]:
    """Get the cached resolution without re-benchmarking."""
    if _resolved_device is None:
        return resolve_device()
    return _resolved_device


def apply_device_config(device_str: str, threads: int) -> None:
    """Apply the resolved device config (set_num_threads for CPU)."""
    if device_str == "cpu":
        torch.set_num_threads(threads)
    # For CUDA/MPS, thread count is not applicable


# For testing: clear the cache
def _reset_cache_for_testing() -> None:
    global _resolved_device, _resolve_failed
    _resolved_device = None
    _resolve_failed = False