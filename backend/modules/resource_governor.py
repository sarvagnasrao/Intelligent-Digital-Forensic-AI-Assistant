import psutil
import time
import os
from typing import Optional

from backend.modules.hardware_probe import get_hardware_spec

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
    Suggests sensible default resource
    budget based on total RAM.
    """
    if total_ram_mb <= 8192:
        # 8GB
        return {
            "min_free_ram_mb": 512,
            "cpu_throttle_percent": 90,
            "batch_size": 50,
            "description": "Balanced (8GB RAM)"
        }
    elif total_ram_mb <= 16384:
        # 16GB
        return {
            "min_free_ram_mb": 512,
            "cpu_throttle_percent": 95,
            "batch_size": 100,
            "description": "Performance (16GB RAM)"
        }
    else:
        # 32GB+
        return {
            "min_free_ram_mb": 512,
            "cpu_throttle_percent": 100,
            "batch_size": 200,
            "description": "Maximum Performance (32GB+ RAM)"
        }

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

    def get_sleep_seconds(self) -> float:
        """
        Returns sleep time between batches
        based on CPU throttle setting.
        100% = 0s, 75% = 0.5s,
        50% = 1s, 25% = 3s
        """
        if self.cpu_throttle_percent >= 100:
            return 0.0
        elif self.cpu_throttle_percent >= 75:
            return 0.5
        elif self.cpu_throttle_percent >= 50:
            return 1.0
        elif self.cpu_throttle_percent >= 25:
            return 3.0
        else:
            return 5.0

    def check_and_throttle(self, stop_check=None):
        """
        Called between processing batches.
        Sleeps if CPU throttle requires it.
        Pauses if RAM is too low.
        Raises StopIteration if stop_check() returns True.
        Returns True if safe to continue,
        False if should abort.
        """
        # Use stored stop_check if none provided
        _check = stop_check or getattr(self, '_stop_check', None)

        # Check stop signal first
        if _check and _check():
            raise StopIteration("Ingestion stopped by user")

        # Force-override: skip ALL resource checks
        self.force_override = True
        if self.force_override:
            return True

        now = time.time()

        # CPU throttle sleep
        sleep_time = self.get_sleep_seconds()
        if sleep_time > 0:
            time.sleep(sleep_time)

        # Check RAM every N seconds
        if now - self._last_check >= self.check_interval:
            self._last_check = now
            mem = psutil.virtual_memory()
            available_mb = int(mem.available / 1024 / 1024)

            if available_mb < self.min_free_ram_mb:
                print(
                    f"[GOVERNOR] RAM low: {available_mb}MB "
                    f"available, need {self.min_free_ram_mb}MB free. "
                    f"Pausing 30 seconds..."
                )
                self._pause_count += 1
                # During pause, check stop signal every 5s
                for _ in range(6):
                    time.sleep(5)
                    if _check and _check():
                        raise StopIteration("Ingestion stopped by user during RAM pause")

                # Check again after pause
                mem = psutil.virtual_memory()
                available_mb = int(mem.available / 1024 / 1024)
                if available_mb < self.min_free_ram_mb * 0.8:
                    # Still too low after waiting
                    print("[GOVERNOR] RAM still critical. Waiting 60s more...")
                    for _ in range(12):
                        time.sleep(5)
                        if _check and _check():
                            raise StopIteration("Ingestion stopped by user during RAM pause")

        return True

    @property
    def total_pauses(self) -> int:
        return self._pause_count
