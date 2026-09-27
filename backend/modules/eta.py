"""Live "time remaining" for a running ingestion job.

Pure logic: no database, no network, no imports from the rest of the
backend. That is deliberate. The estimator is the one part of the queue
UI that is genuinely unit-testable, and the moment it opens a session it
stops being testable at all. Everything impure around it lives in
job_worker, which owns the sockets and the rows.

WHY NOT `elapsed / percent * 100`
---------------------------------
`progress_percent` is not time-proportional. It is five weighted bands
(hash, extraction, chunking, embedding, entity graph) and the cost per
point is wildly uneven between them: a 635 MB disk image spends most of
its wall clock in step 1, a 2 MB text file spends most of its in step 3.
Extrapolating linearly from the percentage extrapolates the wrong
quantity, and it is wrong by the largest margin exactly where the
operator most needs an answer - disk images and long transcriptions.

So the prior is blended with observed throughput rather than being
discarded by the first measurement. The prior (estimated_seconds, from
time_estimator.estimate_ingestion_time) knows the *relative* cost of each
stage and is already profile- and throttle-aware; the observation knows
the *actual* rate on this machine. Neither alone is trustworthy:

  * below OBS_MIN_PERCENT the observation is not trusted at all and the
    number is the prior, and says so;
  * above it, the observation earns weight in proportion to how much of
    the job it has actually seen, capped at MAX_OBS_WEIGHT, so one
    mis-measured step cannot take the number over completely.

GOVERNOR PAUSES
---------------
A job throttled to a 40% CPU ceiling, or waiting on its RAM floor, spends
real wall clock in `time.sleep()` during which no work happens. Measuring
throughput over wall clock therefore reports a machine several times
slower than it is and the ETA creeps upwards for ever. So the pause time
is removed from the work rate.

The pause is still real to the operator - he is waiting through it - so it
is added back as a duty-cycle allowance on the *remaining* work, and only
on the observed term. The prior already carries the requested throttle
factor, so applying the allowance to it too would double-count.

NEVER A FAKE ZERO
-----------------
A metric that cannot be measured is None plus a reason, never 0 (see
AGENTS.md §16). A fabricated 0 renders as "idle" or "finished", and both
are lies. The single place this module emits 0 is `percent >= 100`, where
it is true, and `percent < 100` is floored at 1s so a sub-second remainder
cannot round down into a false "done".

`elapsed_seconds` is the one value that is always real: it is measured
wall clock, rounded to whole seconds because the column is an Integer, so
0 there means "under half a second", not "never started".
"""
import math
import time

# Below this percentage the observed throughput is not trusted. The first
# band of a job is unrepresentative of the whole (a 635 MB image hashes for
# minutes, a 2 MB text file finishes in seconds) and letting it set the ETA
# gives a confidently wrong number for the first fifth of the job.
OBS_MIN_PERCENT = 10

# Ceiling on the observation's share of the blend. The prior is rescaled,
# never thrown away.
MAX_OBS_WEIGHT = 0.75

# Progress frames arrive unevenly - a step boundary can be a fraction of a
# second, a transcription minutes - so the raw per-frame figures are
# unusable on their own and are smoothed.
#
# Smoothing is deliberately ASYMMETRIC, and that is the whole trick. The
# rate is already an EMA, so the remaining noise in the raw ETA is small;
# smoothing the ETA symmetrically on top of it is double-smoothing, and it
# lags in both directions. Measured on a 145s job with a 600s prior, a
# symmetric ETA EMA quoted 168s remaining at 95% - when 5s remained - and
# the lag was the dominant error rather than the prior. So a falling
# countdown (the normal case: work is being consumed) is followed almost
# directly, and only a rise is damped, where the real risk is a spike.
RATE_ALPHA = 0.3
ETA_ALPHA_RISE = 0.35
ETA_ALPHA_FALL = 0.8

# A countdown that jumps 5x between two frames reads as broken, so the
# smoothed ETA may grow by at most this factor per frame. A genuine
# slowdown is still shown - it just takes a few frames to appear, which is
# also what stops one stalled step from panicking the display.
MAX_RISE_FACTOR = 1.5

# A collapse is as much a lie as a spike: promising the job is nearly done
# when it is not is the same defect. So the fall is bounded too. Loose
# enough that a real "75% -> 100%, done" is not held back.
MAX_FALL_FACTOR = 0.35

# How much of wall clock may be governor pause before the allowance is
# capped. Uncapped, a job that spends 90% of its life waiting for its RAM
# floor yields a 10x ETA: arithmetically defensible, useless to read.
MAX_THROTTLE_DUTY = 0.8

CONFIDENCE_PRIOR = "prior"
CONFIDENCE_OBSERVED = "observed"
CONFIDENCE_BLENDED = "blended"


class EtaTracker:
    """Estimates the seconds left on one running ingestion job.

    Construct with the queue-time estimate (seconds, may be None) and,
    optionally, a monotonic clock - tests pass a fake one, which is the
    only reason the clock is injectable rather than read from `time`.

    One tracker per job, created the moment the job is marked Running.
    Call `update(percent, throttle_seconds=...)` on every progress frame
    and read `elapsed()` on the terminal paths.
    """

    def __init__(self, prior_seconds=None, clock=None):
        self._clock = clock if clock is not None else time.monotonic
        self.prior_seconds = self._clean_prior(prior_seconds)
        self._started = self._clock()
        # Highest percent actually seen. Progress is meant to be monotonic
        # (§13) but the forensic path has historically reported 85 -> 75 ->
        # 90, so the tracker tolerates a regression instead of trusting it.
        self._max_percent = 0
        # Smoothed seconds of *work* per percentage point.
        self._rate = None
        self._last_rate_percent = 0
        self._work_at_last_rate = 0.0
        # Smoothed seconds remaining, None until there is something real.
        self._eta = None

    # ── public API ────────────────────────────────────────────────

    def update(self, percent, throttle_seconds=0.0):
        """Advance the estimate and return the full state dict.

        Never raises on bad input: a None percent, a string, a throttle
        counter that went backwards. The caller is the progress path of a
        running ingestion, and nothing about measuring it is worth
        interrupting it for.
        """
        elapsed = self.elapsed()
        throttle = self._clean_throttle(throttle_seconds)
        # The governor's counter is cumulative from when the *governor* was
        # built, which can predate the tracker, so it can exceed elapsed.
        work = max(0.0, elapsed - throttle)
        reported = self._clean_percent(percent)

        # A drop from 100 is a restart, not a band recompute. Reporting 0
        # would be a lie, and keeping the old rate would extrapolate from
        # work that is now being redone. Drop the observation and say
        # "unknown" until the job advances again.
        if reported < self._max_percent and self._max_percent >= 100:
            self._reset_observation()
            return self._result(
                eta=None, confidence=CONFIDENCE_PRIOR, elapsed=elapsed,
                work=work, throttle=throttle, percent=0,
                reported=reported, regressed=True,
                reason=("progress went backwards after 100% - treated as a "
                        "restart, so no estimate until it advances again"))

        # A regression below 100 keeps the high-water mark: the work behind
        # the higher percent has already been done, and a sub-step
        # recomputing its own band must not make the ETA jump.
        regressed = reported < self._max_percent
        percent_used = max(reported, self._max_percent)
        self._max_percent = percent_used
        self._update_rate(percent_used, work)

        eta, confidence, reason = self._estimate(percent_used, work,
                                                 elapsed, throttle)

        if eta is not None:
            eta = self._smooth(eta, percent_used)
        return self._result(
            eta=eta, confidence=confidence, elapsed=elapsed, work=work,
            throttle=throttle, percent=percent_used, reported=reported,
            regressed=regressed, reason=reason)

    def elapsed(self):
        """Wall clock seconds since construction. Always a real number."""
        try:
            return max(0.0, self._clock() - self._started)
        except Exception:
            return 0.0

    # ── internals ─────────────────────────────────────────────────

    @staticmethod
    def _clean_prior(prior_seconds):
        try:
            prior = float(prior_seconds) if prior_seconds is not None else None
        except (TypeError, ValueError):
            return None
        # A prior of 0 is not a zero-second estimate, it is a missing one.
        # estimate_ingestion_time floors at 10s, so anything <= 0 here is
        # absent data and must not be reported as "nothing remaining".
        return prior if (prior is not None and prior > 0) else None

    @staticmethod
    def _clean_throttle(throttle_seconds):
        try:
            return max(0.0, float(throttle_seconds or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clean_percent(percent):
        try:
            value = float(percent)
        except (TypeError, ValueError):
            return 0
        if value != value:      # NaN
            return 0
        return int(max(0, min(100, round(value))))

    def _reset_observation(self):
        self._max_percent = 0
        self._rate = None
        self._last_rate_percent = 0
        self._work_at_last_rate = 0.0
        self._eta = None

    def _update_rate(self, percent, work):
        """EMA of the seconds of work each percentage point is costing.

        Measured over the interval since the last *advance*, not
        cumulatively: a cumulative average is dragged by whatever the
        first step happened to cost, and the first step is exactly the
        unrepresentative one OBS_MIN_PERCENT exists to protect against.
        """
        if percent <= self._last_rate_percent or percent <= 0:
            return
        advanced_pct = percent - self._last_rate_percent
        advanced_work = work - self._work_at_last_rate
        # advanced_work <= 0 happens when the governor's pause counter
        # outran the wall clock across this frame, i.e. the frame carries
        # no usable throughput measurement. Skip it; the next frame
        # measures over the whole span.
        if advanced_work > 0:
            interval_rate = advanced_work / advanced_pct
            self._rate = (interval_rate if self._rate is None else
                          RATE_ALPHA * interval_rate +
                          (1 - RATE_ALPHA) * self._rate)
        self._last_rate_percent = percent
        self._work_at_last_rate = work

    def _estimate(self, percent, work, elapsed, throttle):
        """Raw (unsmoothed) remaining seconds, plus its provenance."""
        remaining_pct = 100.0 - percent
        prior_eta = (self.prior_seconds * remaining_pct / 100.0
                     if self.prior_seconds is not None else None)

        # Observed remaining work, then the throttle allowance. The prior
        # already carries the requested throttle factor, so the allowance
        # is applied here only.
        obs_eta = None
        if self._rate:
            obs_eta = remaining_pct * self._rate * _throttle_multiplier(
                throttle, elapsed)

        if percent >= 100:
            # A real zero: the job reported itself complete.
            return (0.0,
                    CONFIDENCE_BLENDED if self.prior_seconds is not None
                    else CONFIDENCE_OBSERVED,
                    "job reported 100% - nothing remains")

        if percent < OBS_MIN_PERCENT or obs_eta is None:
            if self.prior_seconds is None:
                # Neither a prior nor a measurement: say so, do not guess,
                # and do not return 0.
                return (None, CONFIDENCE_PRIOR,
                        "no queue-time estimate and no throughput measured "
                        "yet - remaining time is unknown")
            reason = (f"queue-time estimate only - too little progress "
                      f"({percent}%) measured to correct it yet")
            return (prior_eta, CONFIDENCE_PRIOR, reason)

        if prior_eta is None:
            return (obs_eta, CONFIDENCE_OBSERVED,
                    "measured throughput on this machine (no queue-time "
                    "estimate to blend with)")

        weight = min(MAX_OBS_WEIGHT, percent / 100.0)
        return ((1.0 - weight) * prior_eta + weight * obs_eta,
                CONFIDENCE_BLENDED,
                f"queue-time estimate rescaled by {weight:.0%} measured "
                f"throughput at {percent}%")

    def _smooth(self, eta, percent):
        """Damped on the way up, followed on the way down, bounded both ways.

        See the note on ETA_ALPHA_RISE / ETA_ALPHA_FALL for why this is not
        one symmetric coefficient: a lagging rise is a cosmetic problem, a
        lagging fall is a wrong answer.
        """
        if percent >= 100:
            self._eta = 0.0
            return 0.0
        if self._eta is None:
            self._eta = eta
            return eta
        if eta > self._eta:
            smoothed = ETA_ALPHA_RISE * eta + (1 - ETA_ALPHA_RISE) * self._eta
            if smoothed > self._eta * MAX_RISE_FACTOR:
                smoothed = self._eta * MAX_RISE_FACTOR
        else:
            smoothed = ETA_ALPHA_FALL * eta + (1 - ETA_ALPHA_FALL) * self._eta
            if smoothed < self._eta * MAX_FALL_FACTOR:
                smoothed = self._eta * MAX_FALL_FACTOR
        self._eta = smoothed
        return smoothed

    def _result(self, *, eta, confidence, elapsed, work, throttle, percent,
                reported, regressed, reason):
        if eta is None:
            eta_out = None
        elif percent >= 100:
            eta_out = 0
        else:
            # ceil + a floor of 1s: a 0.2s remainder must not round down to
            # 0, which is a fake "finished".
            eta_out = max(1, int(math.ceil(eta)))
        return {
            "eta_seconds": eta_out,
            "elapsed_seconds": int(round(elapsed)),
            "eta_confidence": confidence,
            "reason": reason,
            # Diagnostics. The UI ignores them; they are what makes the
            # headline number auditable, and what a test reads instead of
            # reverse-engineering the formula.
            "percent": percent,
            "reported_percent": reported,
            "regressed": regressed,
            "work_seconds": int(round(work)),
            "throttle_seconds": round(throttle, 1),
            "seconds_per_percent": (round(self._rate, 4)
                                    if self._rate else None),
        }


def _throttle_multiplier(throttle_seconds, elapsed_seconds):
    """Wall-clock cost of one second of work, given the pause duty cycle.

    duty/(1-duty) is the time spent paused per second of real work, so at a
    50% duty cycle a second of work costs two seconds of waiting - which is
    what the operator experiences and therefore what the ETA must quote.
    """
    if elapsed_seconds <= 0 or throttle_seconds <= 0:
        return 1.0
    duty = min(throttle_seconds / elapsed_seconds, MAX_THROTTLE_DUTY)
    return 1.0 + duty / (1.0 - duty)
