import psutil
import time
import os
from typing import Optional

from backend.modules.hardware_probe import get_hardware_spec


def _clamp(value: float, low: float, high: float) -> float:
    """Kept local so the governor needs no import from ingestion_modes."""
    return max(low, min(high, value))


def get_system_info() -> dict:
    """
    Auto-detects system hardware specs.
    Returns current and total resources.

    Delegates the detection itself to hardware_probe, then keeps the
    original flat keys (cpu_count, platform, ...) that existing callers
    still read, alongside the richer spec.
    """
    spec = get_hardware_spec()

    # Backwards-compatible aliases for callers written before the richer
    # spec existed. cpu_count in particular is read by the Evidence page.
    spec["cpu_count"] = spec.get("cpu_count_logical") or 0
    spec["platform"] = spec.get("platform_machine") or "unknown"

    return spec

def suggest_resource_budget(total_ram_mb: int) -> dict:
    """
    Suggests a resource budget for this machine.

    Now a thin shim over ingestion_modes.suggest_budget, which reads the live
    probe. The old body branched on a fixed 8/16/32 GB ladder, so it reported
    8 GB-era advice on a 16 GB machine and never looked at core count,
    battery state or GPU presence at all.

    total_ram_mb is accepted for signature compatibility and ignored - the
    probe is the authority, not a stale number passed in by a caller.
    """
    from backend.modules.ingestion_modes import suggest_budget

    return suggest_budget()

class ResourceGovernor:
    """
    Monitors system resources during
    ingestion and throttles processing
    to stay within configured limits.
    """

    def __init__(
            self,
            min_free_ram_mb: int = 512,
            cpu_throttle_percent: int = 100,
            check_interval: int = 5,
            force_override: bool = False):
        self.min_free_ram_mb = min_free_ram_mb
        self.cpu_throttle_percent = cpu_throttle_percent
        self.check_interval = check_interval
        self.force_override = force_override
        self._last_check = 0
        self._pause_count = 0
        # How long a job will sit waiting for its RAM floor before it
        # decides to continue anyway. Bounded on purpose: an unbounded wait
        # turns a busy machine into a queue that never drains.
        self.ram_wait_seconds = 120
        # Set as the loop runs so the UI can explain *why* a job is slow.
        self.last_reason = ""
        self.total_throttle_seconds = 0.0

    def update_limits(self, min_free_ram_mb=None, cpu_throttle_percent=None):
        """
        Applies new limits to a governor that is already running.

        This is what makes "changes apply on the next batch" true. The
        worker keeps a live reference to the governor of the running job, so
        a PATCH to the job row reaches the loop that is actually sleeping
        on the old numbers.
        """
        if min_free_ram_mb is not None:
            self.min_free_ram_mb = int(min_free_ram_mb)
        if cpu_throttle_percent is not None:
            self.cpu_throttle_percent = int(cpu_throttle_percent)
        return {
            "min_free_ram_mb": self.min_free_ram_mb,
            "cpu_throttle_percent": self.cpu_throttle_percent,
        }

    def get_sleep_seconds(self, cpu_percent=None) -> float:
        """
        Seconds to sleep between batches.

        When the live CPU reading is available the sleep is derived from how
        far actual usage is *above* the operator's ceiling, instead of the
        old four fixed buckets. That matters because the buckets made
        "70%" behave exactly like "100%": anything at or above 75% slept
        0.5s, so a 70% setting throttled by the same amount as none at all
        and 100% never slept regardless of how loaded the box already was.

        Returns 0.0 when under the ceiling, ramping to 2.0s when the
        machine is saturated.
        """
        ceiling = max(10, min(100, self.cpu_throttle_percent))

        if cpu_percent is None:
            # No reading available: fall back to a conservative static
            # schedule derived from the ceiling alone.
            if ceiling >= 100:
                return 0.0
            return round(_clamp((100 - ceiling) / 100 * 2.0, 0.0, 2.0), 3)

        # Scale so the ceiling means "this share of the machine".
        target = 100.0 * (ceiling / 100.0)
        excess = cpu_percent - target
        if excess <= 0:
            return 0.0
        # 20 points over the ceiling -> 0.5s, 60+ over -> 2.0s.
        return round(_clamp(excess / 40.0, 0.0, 2.0), 3)

    def _snapshot(self):
        """Cheap combined CPU + RAM reading, in the units the limits use."""
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
        except Exception:
            cpu_percent = None
        try:
            mem = psutil.virtual_memory()
            available_mb = int(mem.available / 1024 / 1024)
        except Exception:
            available_mb = None
        return cpu_percent, available_mb

    def check_and_throttle(self, stop_check=None):
        """
        Called between processing batches.
        Sleeps if CPU throttle requires it.
        Pauses if RAM is too low.
        Raises StopIteration if stop_check() returns True.
        Returns True if safe to continue.
        """
        _check = stop_check or getattr(self, '_stop_check', None)

        # Check stop signal first so a stop is honoured even mid-pause.
        if _check and _check():
            raise StopIteration("Ingestion stopped by user")

        # A genuine override is the only thing that skips resource checks.
        # This used to be an unconditional "self.force_override = True",
        # which silently disabled every limit below for every job.
        if self.force_override:
            self.last_reason = "override"
            return True

        now = time.time()

        # Throttle on every batch: the sleep is 0 when there is headroom, so
        # the cost is one psutil call.
        cpu_percent, available_mb = self._snapshot()
        sleep_time = self.get_sleep_seconds(cpu_percent)
        if sleep_time > 0:
            time.sleep(sleep_time)
            self.total_throttle_seconds += sleep_time
            self.last_reason = f"CPU {cpu_percent:.0f}% above {self.cpu_throttle_percent}% ceiling"
        else:
            self.last_reason = ""

        # RAM is only polled on the slower interval.
        if now - self._last_check >= self.check_interval:
            self._last_check = now
            if available_mb is None:
                return True

            if available_mb < self.min_free_ram_mb:
                self._pause_count += 1
                print(
                    f"[GOVERNOR] RAM low: {available_mb}MB available, "
                    f"need {self.min_free_ram_mb}MB free. Pausing..."
                )
                self.last_reason = f"RAM {available_mb}MB < {self.min_free_ram_mb}MB floor"

                if not self._wait_for_ram(_check, available_mb):
                    return True

                # Report what it settled on so the step text is truthful.
                try:
                    mem = psutil.virtual_memory()
                    self.last_reason = (
                        f"resumed at {int(mem.available / 1024 / 1024)}MB free"
                    )
                except Exception:
                    self.last_reason = "resumed"

        return True

    def _wait_for_ram(self, _check, available_mb: int) -> bool:
        """
        Blocks until the RAM floor is satisfied, the stop signal fires, or
        the grace period expires. Returns True if RAM recovered.

        Waits in short slices so a stop request is honoured promptly instead
        of after a fixed 30s block, and gives up after a bounded time so a
        machine that never frees memory still finishes the job rather than
        hanging forever.
        """
        deadline = time.time() + self.ram_wait_seconds
        while time.time() < deadline:
            # 2 second slices: responsive to stop, cheap to poll.
            time.sleep(2)
            if _check and _check():
                raise StopIteration("Ingestion stopped by user during RAM pause")
            try:
                mem = psutil.virtual_memory()
                available_mb = int(mem.available / 1024 / 1024)
            except Exception:
                return False
            if available_mb >= self.min_free_ram_mb:
                print(
                    f"[GOVERNOR] RAM recovered: {available_mb}MB available"
                )
                return True
        print(
            f"[GOVERNOR] Still only {available_mb}MB free after "
            f"{self.ram_wait_seconds}s - continuing anyway rather than "
            f"stalling the queue."
        )
        return False

    @property
    def total_pauses(self) -> int:
        return self._pause_count

    @property
    def total_pauses(self) -> int:
        return self._pause_count
