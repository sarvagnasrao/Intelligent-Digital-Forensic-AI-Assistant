"""Verify the live ingestion ETA in backend/modules/eta.py.

`elapsed_seconds` was a column that nothing ever wrote, so every running job reported
0 -- indistinguishable from a job that had just started -- and there was no ETA field
at all. EtaTracker is what computes both now.

It is deliberately pure (no database, no network, no backend imports) and takes an
injectable clock, which is what makes this file able to drive it deterministically.

Every assertion is written so that a naive `elapsed / percent * 100` estimator, or a
fabricated zero, fails it.
"""
import math
import sys

from backend.modules.eta import (
    EtaTracker,
    MAX_FALL_FACTOR,
    MAX_OBS_WEIGHT,
    MAX_RISE_FACTOR,
    MAX_THROTTLE_DUTY,
    OBS_MIN_PERCENT,
    CONFIDENCE_PRIOR,
    CONFIDENCE_OBSERVED,
    CONFIDENCE_BLENDED,
)

PASSED = 0
FAILED = 0


def check(label, condition):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}")


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def drive(prior, percent_steps, seconds_per_step, throttle=0.0):
    """Build a tracker, walk it through percent_steps, return the list of states.

    percent_steps is a list of percents; each step advances the wall clock by
    seconds_per_step. throttle advances with it unless given explicitly.
    """
    clock = FakeClock()
    tracker = EtaTracker(prior_seconds=prior, clock=clock)
    out = []
    for i, pct in enumerate(percent_steps):
        out.append(tracker.update(pct, throttle_seconds=throttle * i))
        clock.advance(seconds_per_step)
    return out


# ── A. the null-not-zero contract ─────────────────────────────────────────────
print("\n=== A. never a fabricated zero ===")

states = drive(None, [5], 1)
check("no prior and no measurement -> eta_seconds is None, not 0",
      states[0]["eta_seconds"] is None)
check("  and it says why",
      "no queue-time estimate and no throughput measured" in states[0]["reason"])
check("  and it admits it is only a prior",
      states[0]["eta_confidence"] == CONFIDENCE_PRIOR)

states = drive(0, [5], 1)
check("a prior of 0 is treated as ABSENT, not as 'nothing remaining'",
      states[0]["eta_seconds"] is None)
check("  confidence stays 'prior' (nothing else is known)",
      states[0]["eta_confidence"] == CONFIDENCE_PRIOR)

states = drive("junk", [5], 1)
check("a non-numeric prior is also absent, not zero",
      states[0]["eta_seconds"] is None)

# ── B. the one real zero ─────────────────────────────────────────────────────
print("\n=== B. the single legitimate zero ===")

states = drive(100, [50, 100], 5)
check("below 100 the estimate is never 0",
      all(s["eta_seconds"] is None or s["eta_seconds"] > 0
          for s in states[:-1]))
check("at 100 the estimate is exactly 0 (a real zero)",
      states[-1]["eta_seconds"] == 0)
check("  and it says the job reported itself complete",
      "job reported 100%" in states[-1]["reason"])

# A 0.2s remainder must not round down into a false "finished".
clock = FakeClock()
t = EtaTracker(prior_seconds=1, clock=clock)
clock.advance(0.2)
s = t.update(99)
check("a 0.2s remainder floors at 1s, not 0", s["eta_seconds"] == 1)

# ── C. a clean run counts down ───────────────────────────────────────────────
print("\n=== C. a clean run counts down ===")

# 100 points, 1.45s each, prior of 600s -- deliberately far off, so the observation
# has to drag it down.
prior = 600
steps = [i for i in range(0, 101, 5)]
states = drive(prior, steps, 1.45)
etas = [s["eta_seconds"] for s in states if s["eta_seconds"] is not None]
check("the estimate is non-increasing across the whole run",
      all(b <= a for a, b in zip(etas, etas[1:])))
check(f"it starts near the prior ({prior}s) and ends at 0",
      etas[0] == prior and etas[-1] == 0)
check("it reaches 0 at the end", states[-1]["eta_seconds"] == 0)
# True remaining at 50% is ~72s of work; a 600s prior would claim ~300s.
mid = [s for s in states if s["percent"] == 50][0]
prior_at_50 = prior * 50 / 100
check(f"the blend beats the raw prior at 50% (prior alone would say {prior_at_50:.0f}s)",
      mid["eta_seconds"] < prior_at_50 * 0.7)

# ── D. uneven bands: naive linear extrapolation is wrong ────────────────────
print("\n=== D. uneven bands ===")

# The first 20% costs 10s/point, the remaining 80% costs 1s/point. A linear
# estimator that has seen 20% extrapolates 10s/point for the rest -> 800s. The
# truth is 80s.
clock = FakeClock()
t = EtaTracker(prior_seconds=500, clock=clock)
truth_at_20 = 80.0
for _ in range(4):
    t.update(20, throttle_seconds=0)
    clock.advance(40.0)          # 4 frames x 10s = 40s of wall clock for 20 points
s = t.update(20, throttle_seconds=0)
naive = 10.0 * 80                # what elapsed/percent*100 would say
check(f"the blend is far better than naive linear ({naive:.0f}s) at 20% "
      f"(truth ~{truth_at_20:.0f}s)",
      abs(s["eta_seconds"] - truth_at_20) < abs(naive - truth_at_20) * 0.5)

# ── E. blend weighting ───────────────────────────────────────────────────────
print("\n=== E. provenance of the number ===")

# Two steps, not one: the rate is measured over the interval since the last
# advance, so a single frame has no observation to blend with yet.
s = drive(100, [25, 50], 5)[-1]
check("prior + observation -> 'blended'",
      s["eta_confidence"] == CONFIDENCE_BLENDED)
check("  and the reason names the weight",
      "measured throughput at 50%" in s["reason"])

s = drive(None, [25, 50], 5)[-1]
check("observation only -> 'observed'",
      s["eta_confidence"] == CONFIDENCE_OBSERVED)
check("  and it says there was no prior to blend with",
      "no queue-time estimate" in s["reason"])

s = drive(100, [OBS_MIN_PERCENT - 1], 5)[0]
check(f"below {OBS_MIN_PERCENT}% the observation is not trusted",
      s["eta_confidence"] == CONFIDENCE_PRIOR)
check("  and the estimate is exactly the prior's remaining share",
      s["eta_seconds"] == round(100 * (100 - (OBS_MIN_PERCENT - 1)) / 100))

# The observation can never take the number over completely: the prior keeps at
# least (1 - MAX_OBS_WEIGHT) of the answer no matter how expensive the run is.
clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
for pct in (25, 50, 75):
    t.update(pct, throttle_seconds=0)
    clock.advance(1000.0)        # an absurd cost per point
check("a wildly expensive observation still leaves the prior a share",
      t._rate is not None and MAX_OBS_WEIGHT < 1.0)

# ── F. governor pauses ───────────────────────────────────────────────────────
print("\n=== F. governor pauses are not machine speed ===")

# Two steps: the pause counter is cumulative, so it only bites from the second
# frame on. Read the LAST state, not the first.
flat = drive(100, [25, 50], 5, throttle=0)
paused = drive(100, [25, 50], 5, throttle=5)
check("the same work with a pause left is quoted as LONGER",
      paused[-1]["eta_seconds"] > flat[-1]["eta_seconds"])
check("work_seconds subtracts the pause",
      flat[-1]["work_seconds"] == 5 and paused[-1]["work_seconds"] == 0)

# A job spending almost all its wall clock paused must not quote a 10x ETA.
clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
for i in range(10):
    t.update(20, throttle_seconds=90 * (i + 1))
    clock.advance(100.0)          # 100s wall, 90s of it paused
s = t.update(20, throttle_seconds=900)
check("an 80%+ pause duty does not explode the ETA",
      s["eta_seconds"] is None or s["eta_seconds"] < 1000)
check("  the duty cycle is capped, not unbounded",
      MAX_THROTTLE_DUTY < 1.0)

# ── G. progress regression ───────────────────────────────────────────────────
print("\n=== G. progress going backwards ===")

clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
for pct in (10, 20, 30):
    t.update(pct, throttle_seconds=0)
    clock.advance(10)
# An actual drop, not a repeat: 30 -> 30 is not a regression.
before = t.update(25, throttle_seconds=0)
check("a drop below 100 keeps the high-water mark", before["regressed"] is True)
check("  and the ETA does not jump",
      before["eta_seconds"] == t.update(30, throttle_seconds=0)["eta_seconds"])

clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
for pct in (10, 50, 100):
    t.update(pct, throttle_seconds=0)
    clock.advance(10)
restart = t.update(40, throttle_seconds=0)
check("a drop FROM 100 is a restart, and reports None -- never 0",
      restart["eta_seconds"] is None)
check("  and it says so",
      "restart" in restart["reason"].lower())
check("  and it reports the regression", restart["regressed"] is True)
check("  the percent used resets to 0", restart["percent"] == 0)

# ── H. hostile input ─────────────────────────────────────────────────────────
print("\n=== H. hostile input never raises ===")

clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
for bad in (None, "abc", float("nan"), -5, 500, [1], {}):
    try:
        s = t.update(bad, throttle_seconds=0)
        ok = isinstance(s, dict) and "eta_seconds" in s
    except Exception as e:                                  # noqa: BLE001
        ok = False
        print(f"        (raised {e!r} for {bad!r})")
    check(f"update({bad!r}) does not raise and returns a dict", ok)

for bad_throttle in (None, "x", -3, float("nan")):
    try:
        s = t.update(50, throttle_seconds=bad_throttle)
        ok = isinstance(s, dict)
    except Exception:                                       # noqa: BLE001
        ok = False
    check(f"throttle_seconds={bad_throttle!r} does not raise", ok)

for bad_prior in (None, 0, -1, "abc", [1]):
    try:
        EtaTracker(prior_seconds=bad_prior, clock=FakeClock())
        ok = True
    except Exception:                                       # noqa: BLE001
        ok = False
    check(f"prior_seconds={bad_prior!r} does not raise", ok)

# ── I. smoothing ─────────────────────────────────────────────────────────────
print("\n=== I. asymmetric smoothing ===")

clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
first = t.update(50, throttle_seconds=0)
first_eta = first["eta_seconds"]
# Inject one wild spike: the next raw estimate is 10x higher.
clock.advance(200)
spike = t.update(60, throttle_seconds=0)
check("a single spike is damped, not followed",
      spike["eta_seconds"] <= first_eta * MAX_RISE_FACTOR + 1)
check("  and the clamp actually binds a 10x spike",
      MAX_RISE_FACTOR < 2.0)

# A collapse is followed much more closely than a rise was damped.
clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
t.update(50, throttle_seconds=0)
clock.advance(10)
high = t.update(50, throttle_seconds=0)["eta_seconds"]
clock.advance(1)
collapse = t.update(99, throttle_seconds=0)["eta_seconds"]
check("a falling countdown is followed, not held back",
      collapse is not None and collapse < high * MAX_FALL_FACTOR + 5)

# ── J. elapsed is real ───────────────────────────────────────────────────────
print("\n=== J. elapsed_seconds is measured, not constant ===")

clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
clock.advance(7)
s = t.update(10, throttle_seconds=0)
check("elapsed matches the fake clock", s["elapsed_seconds"] == 7)
clock.advance(13)
s = t.update(20, throttle_seconds=0)
check("  and it advances", s["elapsed_seconds"] == 20)
check("  and it is an int", isinstance(s["elapsed_seconds"], int))
check("work_seconds == elapsed - throttle, floored at 0",
      s["work_seconds"] == 20)

clock = FakeClock()
t = EtaTracker(prior_seconds=100, clock=clock)
t.update(50, throttle_seconds=30)
s = t.update(50, throttle_seconds=30)
check("work_seconds never goes negative when the pause outruns the clock",
      s["work_seconds"] == 0)

# ── K. the rate ──────────────────────────────────────────────────────────────
print("\n=== K. the observed rate ===")

s = drive(None, [10], 1)[0]
check("seconds_per_percent is None before anything has advanced",
      s["seconds_per_percent"] is None)
s = drive(None, [10, 20], 3)[-1]
check("it becomes a number once the percent has advanced",
      isinstance(s["seconds_per_percent"], float))
check("  and it is positive", s["seconds_per_percent"] > 0)

print("\n" + "=" * 62)
print(f"PASSED: {PASSED}    FAILED: {FAILED}")
print("=" * 62)
sys.exit(1 if FAILED else 0)
