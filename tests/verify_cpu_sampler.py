"""
Guards that the CPU/RAM figures the monitor shows actually track the machine.

The panel previously slept 300 ms inside hardware_probe's module lock on every
cache miss - psutil.cpu_percent(interval=0.3) - so the Evidence page's budget
request, the Queue page's poll and the ingestion worker's governor all
serialised behind a quarter-second pause to produce one number. It is now
non-blocking and primed at import, which is correct but *unverifiable by
reading*: a primed sampler that silently returned 0.0 forever would look
exactly like an idle machine. So this loads the machine and requires the
reported figure to move.

Run:  PYTHONPATH=. python tests/verify_cpu_sampler.py

Saturates every logical core for ~4 s. Run it on an otherwise idle box; on a
busy one the load phase may not reach the threshold and the test will say so.
"""
import os
import sys
import time
import threading
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import psutil
from backend.modules import hardware_probe as hp

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{'' if cond else '  -> ' + str(detail)}")
    return cond


BURN_SECONDS = 4.0

# The load generator must be separate PROCESSES, not threads. Pure-Python
# threads are serialised by the GIL to roughly one core, so eight of them peg
# the machine to about 12% and prove nothing - a 28% reading from a "full load"
# is a property of the generator, not of the sampler. subprocess rather than
# multiprocessing, because Windows spawn re-imports __main__ and would demand
# a freeze_support guard that a test script should not need.
BURNER = (
    "import time\n"
    "end = time.perf_counter() + %f\n"
    "x = 0\n"
    "while time.perf_counter() < end:\n"
    "    x = (x * 31 + 7) & 0xFFFFFFFF\n"
) % BURN_SECONDS


def part_a_tracks_load():
    print("\n=== A. the reported figure follows the machine ===")
    burners = [subprocess.Popen([sys.executable, "-c", BURNER])
               for _ in range(max(2, psutil.cpu_count()))]
    try:
        # Prime immediately before the load, so the window measured is the load
        # itself rather than a mixture of load and idle.
        hp.get_hardware_spec(force=True)
        time.sleep(BURN_SECONDS)
        loaded = hp.get_hardware_spec(force=True)
    finally:
        for p in burners:
            try:
                p.wait(timeout=15)
            except Exception:
                p.kill()

    time.sleep(0.5)
    idle = hp.get_hardware_spec(force=True)

    print(f"  loaded: cpu_percent={loaded['cpu_percent']} "
          f"per-core max={max(loaded['cpu_per_core_percent'])}")
    print(f"  idle:   cpu_percent={idle['cpu_percent']} "
          f"per-core max={max(idle['cpu_per_core_percent'])}")

    check("cpu_percent is measured under load", loaded["cpu_percent"] is not None)
    check("cpu_percent climbs under a full-core load - the sampler tracks",
          (loaded["cpu_percent"] or 0) > 50, loaded["cpu_percent"])
    check("cpu_percent falls again once the load stops",
          (idle["cpu_percent"] or 0) < (loaded["cpu_percent"] or 0),
          f"{idle['cpu_percent']} vs {loaded['cpu_percent']}")
    check("per-core figures show the load too",
          max(loaded["cpu_per_core_percent"]) > 50,
          max(loaded["cpu_per_core_percent"]))
    check("one per-core entry per logical core",
          len(idle["cpu_per_core_percent"]) == psutil.cpu_count(),
          len(idle["cpu_per_core_percent"]))
    check("every per-core figure is a real percentage",
          all(0 <= v <= 100 for v in idle["cpu_per_core_percent"]),
          idle["cpu_per_core_percent"])


def part_b_no_lock_stall():
    print("\n=== B. the 300 ms lock stall is gone ===")
    # The old code slept inside the module lock on every cache miss, so a
    # concurrent caller queued behind a guaranteed 300 ms pause. Generous
    # threshold: the point is to catch a regression to a hard sleep on every
    # call, not to benchmark the host.
    worst = [0.0]
    hits = [0]
    stop = threading.Event()

    def hammer():
        while not stop.is_set():
            t0 = time.perf_counter()
            hp.get_hardware_spec(force=True)   # force = always a cache miss
            elapsed = time.perf_counter() - t0
            if elapsed > worst[0]:
                worst[0] = elapsed
            hits[0] += 1
            time.sleep(0.01)

    h = threading.Thread(target=hammer, daemon=True)
    h.start()
    time.sleep(2.0)
    stop.set()
    h.join(timeout=5)

    print(f"  forced re-scan worst case: {worst[0] * 1000:.0f} ms "
          f"over {hits[0]} scans")
    check("the concurrency probe actually ran", hits[0] > 20, hits[0])
    check("a forced re-scan is no longer stalled by a 300 ms sleep",
          worst[0] < 0.30, f"{worst[0] * 1000:.0f} ms")

    t0 = time.perf_counter()
    hp.get_hardware_spec()
    cached_ms = (time.perf_counter() - t0) * 1000
    check("a cached call is essentially free", cached_ms < 20, f"{cached_ms:.1f} ms")


def main():
    for fn in (part_a_tracks_load, part_b_no_lock_stall):
        try:
            fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")

    print(f"\n{'=' * 60}")
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"    FAILED: {f}")
    print(f"{'=' * 60}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
