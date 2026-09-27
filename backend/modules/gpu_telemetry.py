"""
Live GPU utilisation and VRAM-used telemetry.

`hardware_probe` inventories *which* adapters exist (name, dedicated VRAM) from
the Windows registry or Linux sysfs. Neither source can say how **busy** an
adapter is, which is the number that matters while an ingestion is running: the
whole point of watching the hardware is to see whether Whisper went to the GPU
or quietly stayed on the CPU.

Design constraints, from AGENTS.md:
  * stdlib + `psutil` only. No new dependency - this ships in an air-gap kit
    where every wheel has to be pre-downloaded (see the `vendor/` note).
  * No shell calls, ever (AGENTS.md §9). That rules out `nvidia-smi`,
    `system_profiler` and `wmic`.

So NVIDIA is read through **NVML via ctypes**, which is the driver library
already on the machine, loaded directly rather than invoked.

────────────────────────────────────────────────────────────────────────────
THE TRAP: nvmlDeviceGetMemoryInfo silently returns nonsense on some drivers
────────────────────────────────────────────────────────────────────────────

Proven on this box (driver 582.66, GTX 1050 Ti), not assumed:

    nvmlDeviceGetMemoryInfo_v2  -> rc=2 (NOT_SUPPORTED), all fields 0
    nvmlDeviceGetMemoryInfo     -> rc=0, total=4096MB used=595MB   CORRECT
    nvmlDeviceGetMemoryInfo     -> rc=0, total=0MB    used=3501MB   with a
                                    struct whose fields are 32-bit

The third line is the dangerous one. It reports **success**. `nvmlMemory_t` is
three `unsigned long long`, so a 32-bit struct hands the callee a 12-byte
buffer for a 24-byte write; `total` reads 0 and `used` reads what is really
`free`. A return-code check passes and the caller displays confidently wrong
numbers.

And the same mistake has a nastier twin, one version along. `nvmlMemory_v2_t`
is a **different, larger** struct - `version, total, reserved, free, used`,
40 bytes - and this module originally passed the 24-byte v1 struct to the v2
entry point on the reasonable-sounding grounds that both return memory info.
That is a 16-byte write past the end of the buffer. It never fired on the dev
box purely because that driver declines v2; on a driver where v2 works it would
corrupt the stack, and the crash would surface somewhere unrelated to the call
that caused it. The lesson generalises past NVML: **a version suffix changes a
struct's layout, and a versioned struct is a request the caller must fill in,
not just a return value.** See `_NvmlMemoryV2`.

Three consequences, all encoded below:
  1. Each entry point is paired with its own struct. Never share one across an
     entry point and its `_vN` sibling. Sizes are asserted at import.
  2. The struct is 64-bit. Non-negotiable.
  3. Return code alone is insufficient. The values are validated - total must
     be positive, free and used must be in range, the fields must *reconcile*
     (`total == reserved + free + used`, checked in bytes so flooring cannot
     fake it), and total is cross-checked against the dedicated VRAM the
     registry already reported for that adapter.

────────────────────────────────────────────────────────────────────────────
A metric that cannot be measured is reported as None, never as 0
────────────────────────────────────────────────────────────────────────────

`None` renders as "—" in the UI. A fabricated `0` renders as "idle", and an idle
reading during a two-hour transcription is the exact lie this module exists to
prevent. Every failure path sets `gpu_telemetry_reason` so the UI can say why.
"""

import ctypes
import os
import re
import threading
import time
from ctypes import c_char_p, c_ulonglong, c_uint, c_void_p, byref

# Bytes in a megabyte, as NVML reports memory.
_MB = 1024 * 1024

# NVML_SUCCESS. Anything non-zero is an error, and several calls return
# NVML_ERROR_NOT_SUPPORTED (2) for perfectly healthy devices.
_NVML_SUCCESS = 0

# How far the NVML-reported VRAM total may differ from the dedicated VRAM the
# registry reported and still count as the same adapter. A driver that rounds
# or reserves a little memory is normal; a total of 0 MB is not.
_VRAM_TOLERANCE_MB = 64
_VRAM_TOLERANCE_FRACTION = 0.05

# How far the v2 reading may disagree with v1's before the v2 field layout is
# treated as wrong rather than merely live. The two reads are microseconds
# apart, so this only has to absorb an allocation landing between them - and a
# false alarm is harmless, because it falls back to v1, which is correct but
# carries no `reserved` field. So it is deliberately tight: the cost of a miss
# is displaying a wrong number, and the cost of a false positive is one extra
# call.
_LAYOUT_TOLERANCE_BYTES = 16 * _MB


# ── NVML structures ─────────────────────────────────────────────────────────
# Widths are load-bearing. See the module docstring.

class _NvmlUtilization(ctypes.Structure):
    """nvmlUtilization_t: two unsigned ints, 8 bytes."""
    _fields_ = [("gpu", c_uint), ("memory", c_uint)]


class _NvmlMemory(ctypes.Structure):
    """nvmlMemory_t: three unsigned long long, 24 bytes.

    Declared 64-bit deliberately. The 32-bit variant returns SUCCESS while
    reporting total=0 and used=free, because the driver then writes 24 bytes
    through a 12-byte buffer.
    """
    _fields_ = [("total", c_ulonglong), ("free", c_ulonglong),
                ("used", c_ulonglong)]


class _NvmlMemoryV2(ctypes.Structure):
    """
    nvmlMemory_v2_t: five unsigned long long, 40 bytes - NOT interchangeable
    with nvmlMemory_t.

    This struct exists because of a bug that reading the code did not reveal.
    The v2 entry point was originally called with the 24-byte v1 struct above,
    on the reasonable-sounding grounds that the two return "memory info". The
    driver therefore wrote 40 bytes into a 24-byte buffer - 16 bytes past the
    end of it. It stayed dormant on the box this was written on only because
    that driver answers `NOT_SUPPORTED` for v2 and writes nothing. On any
    driver where v2 *is* supported, the same code corrupts the stack, and the
    failure would be a crash somewhere else entirely, long after the call that
    caused it.

    Two rules, and they generalise to any versioned NVML call:
      1. Never share a struct between an entry point and its `_vN` sibling.
         The version suffix changes the layout, not just the name.
      2. A versioned struct is a *request* as well as a return value. The
         caller sets `version` to `sizeof(struct) | (ver << 24)`, which is how
         the driver knows how much space it is being given. An uninitialised
         version is not a default, it is a malformed request.

    Asserted at import - a struct that is the wrong size is not something to
    discover at run time on someone else's machine.

    The version word is `unsigned int` plus an explicit `unsigned int` pad, not
    one 64-bit field. The C declaration is
        unsigned int version;
        unsigned int abiPad;
        unsigned long long total, reserved, free, used;
    and on this platform the 64-bit spelling happens to produce identical
    offsets. It is modelled the way the header declares it anyway: an ABI layout
    is a fact to be transcribed, not one to be reverse-engineered from a size
    that came out right.
    """
    _fields_ = [("version", c_uint),
                ("_abi_pad", c_uint),
                ("total", c_ulonglong),
                ("reserved", c_ulonglong),
                ("free", c_ulonglong),
                ("used", c_ulonglong)]


# NVML_STRUCT_VERSION(DataType, DataVer) is
#   sizeof(DataType) | ((unsigned int)DataVer << 24)
# and the driver reads it to learn how much space it has been handed. See
# _NvmlMemoryV2 for why this is a request and not decoration.
_NVML_STRUCT_VERSION_SHIFT = 24
_NVML_MEMORY_V2_VERSION = (
    ctypes.sizeof(_NvmlMemoryV2) | (2 << _NVML_STRUCT_VERSION_SHIFT))

# Fail loudly at import rather than corrupt a stack frame later. These are ABI
# facts, not runtime conditions, so there is nothing to gain by deferring.
assert ctypes.sizeof(_NvmlMemoryV2) == 40, \
    f"nvmlMemory_v2_t must be 40 bytes, got {ctypes.sizeof(_NvmlMemoryV2)}"
assert ctypes.sizeof(_NvmlMemory) == 24, \
    f"nvmlMemory_t must be 24 bytes, got {ctypes.sizeof(_NvmlMemory)}"
assert ctypes.sizeof(_NvmlUtilization) == 8, \
    f"nvmlUtilization_t must be 8 bytes, got {ctypes.sizeof(_NvmlUtilization)}"


# ── Library loading ─────────────────────────────────────────────────────────

# Where nvml.dll lives when it is not on the default search path. The driver
# drops a copy in System32 on most installs; the NVSMI folder is the fallback
# for driver-only installs.
_WINDOWS_NVML_PATHS = (
    "nvml.dll",
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                 "System32", "nvml.dll"),
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                 "SysWOW64", "nvml.dll"),
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll",
)

_LINUX_NVML_PATHS = (
    "libnvidia-ml.so.1",
    "libnvidia-ml.so",
    "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
    "/usr/lib/aarch64-linux-gnu/libnvidia-ml.so.1",
    "/usr/lib64/libnvidia-ml.so.1",
)


def _load_nvml():
    """
    Loads the NVML shared library, or returns None.

    ctypes.WinDLL / ctypes.CDLL are used for the platform's native calling
    convention. No shell out, no subprocess - AGENTS.md §9.
    """
    is_windows = os.name == "nt"
    loader = ctypes.WinDLL if is_windows else ctypes.CDLL
    paths = _WINDOWS_NVML_PATHS if is_windows else _LINUX_NVML_PATHS
    for path in paths:
        try:
            return loader(path)
        except OSError:
            continue
    return None


def _has(lib, name):
    """True when the loaded library exports `name`."""
    try:
        return getattr(lib, name) is not None
    except AttributeError:
        return False


# ── The NVML session ────────────────────────────────────────────────────────

def _reconcile_memory(total, free, used, reserved):
    """
    Resolve which `used` convention this driver uses, and normalise it.

    Returns (used_excluding_reserved, convention, reason). `convention` is
    "separate" (A: `used` excludes the driver reservation) or "inclusive"
    (B: `used` includes it); `reason` is set only when neither reconciles.

    ── Why this is a function and not three lines inline ──
    NVIDIA's reference for `nvmlMemory_v2_t` describes `used` as INCLUDING
    `reserved`. The driver on this box measures as EXCLUDING it:

        total == reserved + free + used    delta = 0       <- A, observed
        total ==           free + used    delta = 92 MB   <- B, per the docs

    Pinning one identity is precisely how valid data ends up rejected: the
    reading fails its own check and the code silently falls back to v1, which
    reports a different `used` again. A refusal that quietly becomes a different
    answer is the same defect as a silent success, one layer down. So both are
    accepted, and the result is normalised so the number means the same thing
    on every driver: application VRAM, excluding the driver reservation. Under
    B the raw `used` would overstate by `reserved` (92 MB, 2.2% of a 4 GB card).

    Bytes throughout, so flooring into MB cannot manufacture or hide a
    violation.
    """
    if total <= 0:
        return None, None, f"total={total}"
    if free < 0 or used < 0 or free > total or used > total:
        return None, None, (f"out-of-range fields (free={free} used={used} "
                            f"total={total})")
    # A is tried first: when reserved is 0 the two coincide, and there is no
    # reason to prefer B.
    if abs(total - (reserved + free + used)) <= _MB:
        return used, "separate", None
    if used >= reserved and abs(total - (free + used)) <= _MB:
        return used - reserved, "inclusive", None
    return None, None, (f"fields reconcile under neither convention: "
                        f"total={total}, reserved={reserved} free={free} "
                        f"used={used} (off by "
                        f"{min(abs(total - (reserved + free + used)), abs(total - (free + used)))} "
                        f"bytes)")


class _NvmlSession:
    """
    Process-wide NVML handle, initialised once.

    `nvmlInit` is process-global and `nvmlShutdown` would tear the library down
    for every other holder in the process, so this never shuts down. The handles
    are re-resolved on each sample instead of cached: a handle is invalidated by
    a GPU reset or a hot-unplug, and a forensics box gets eGPUs and docking
    stations plugged in mid-session. Re-resolving costs a couple of microseconds
    against an 8-second poll.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.lib = None
        self.state = "unprobed"      # unprobed | ready | unavailable
        self.reason = ""
        self.driver_version = None
        self._fn = {}
        self._failed_at = None

    # How long an unavailable session waits before probing NVML again.
    #
    # Success is cached for the life of the process, but failure is NOT
    # terminal. A forensics box is not a static machine: the NVIDIA driver may
    # not be loaded when the backend starts, a machine can be suspended and
    # resumed, and an eGPU gets plugged into a dock mid-session. With a
    # terminal "unavailable", the panel would show a permanent em dash for a
    # GPU that is right there and working - and pressing Rescan would not even
    # help, which is the opposite of what Rescan is for. So failure expires,
    # and an explicit rescan bypasses the wait entirely.
    _RETRY_SECONDS = 30.0

    def _fail(self, reason):
        self.state = "unavailable"
        self.reason = reason
        self.lib = None
        self._fn = {}
        self._failed_at = time.monotonic()
        return False

    def ensure_ready(self, force=False):
        """
        Loads and initialises NVML once. Idempotent, and safe to call from any
        thread. Returns True when telemetry is possible.

        `force` skips the failure backoff - used when the operator has just
        plugged something in and asked for a re-scan.
        """
        with self.lock:
            if self.state == "ready":
                return True
            if self.state == "unavailable" and not force:
                waited = time.monotonic() - (self._failed_at or 0.0)
                if waited < self._RETRY_SECONDS:
                    return False

            lib = _load_nvml()
            if lib is None:
                return self._fail(
                    "NVML library not found - no NVIDIA telemetry on this "
                    "machine")

            # Prefer the _v2 initialiser, fall back to v1 for older drivers.
            init = None
            for name in ("nvmlInit_v2", "nvmlInit"):
                if _has(lib, name):
                    init = getattr(lib, name)
                    break
            if init is None:
                return self._fail("NVML present but exports no init function")

            try:
                rc = init()
            except Exception as e:
                return self._fail(f"NVML init raised {type(e).__name__}: {e}")
            if rc != _NVML_SUCCESS:
                return self._fail(
                    f"NVML init returned {rc} - the NVIDIA driver may not be "
                    f"loaded or is not accessible to this process")

            # Resolve the entry points actually needed. Absent ones are fine;
            # the sample functions below degrade to None per metric.
            self._fn = {}
            for name in ("nvmlDeviceGetCount_v2", "nvmlDeviceGetCount",
                         "nvmlDeviceGetHandleByIndex_v2",
                         "nvmlDeviceGetHandleByIndex",
                         "nvmlDeviceGetName",
                         "nvmlDeviceGetUtilizationRates",
                         "nvmlDeviceGetMemoryInfo",
                         "nvmlDeviceGetMemoryInfo_v2",
                         "nvmlSystemGetDriverVersion"):
                self._fn[name] = getattr(lib, name) if _has(lib, name) else None

            self.lib = lib
            self.state = "ready"
            self.reason = ""
            self._failed_at = None

            version = self._fn.get("nvmlSystemGetDriverVersion")
            if version is not None:
                try:
                    buf = ctypes.create_string_buffer(96)
                    if version(buf, 96) == _NVML_SUCCESS:
                        self.driver_version = \
                            buf.value.decode("utf-8", "replace")
                except Exception:
                    self.driver_version = None
            return True

    # -- device enumeration --------------------------------------------------

    def _devices(self):
        """
        Yields (index, handle) for each physical device, or [] plus a reason.

        _v2 handles are 64-bit on some drivers and a plain handle on others;
        c_void_p is correct for both.
        """
        count_fn = self._fn.get("nvmlDeviceGetCount_v2") \
            or self._fn.get("nvmlDeviceGetCount")
        handle_fn = self._fn.get("nvmlDeviceGetHandleByIndex_v2") \
            or self._fn.get("nvmlDeviceGetHandleByIndex")
        if count_fn is None or handle_fn is None:
            return [], "NVML exports no device-enumeration functions"

        try:
            count = c_uint(0)
            if count_fn(byref(count)) != _NVML_SUCCESS:
                return [], f"NVML device count failed ({count.value})"
            out = []
            for index in range(count.value):
                handle = c_void_p()
                if handle_fn(index, byref(handle)) == _NVML_SUCCESS \
                        and handle.value:
                    out.append((index, handle))
            return out, None
        except Exception as e:
            return [], f"NVML enumeration raised {type(e).__name__}: {e}"

    # -- per-device metrics --------------------------------------------------

    def _utilization(self, handle):
        """GPU and memory-controller busy percent, or (None, None, reason)."""
        fn = self._fn.get("nvmlDeviceGetUtilizationRates")
        if fn is None:
            return None, None, "NVML exports no utilization function"
        try:
            util = _NvmlUtilization()
            rc = fn(handle, byref(util))
        except Exception as e:
            return None, None, f"utilization read raised {type(e).__name__}"
        if rc != _NVML_SUCCESS:
            return None, None, f"utilization read returned {rc}"
        # A driver that answers success with nonsense must not be trusted into
        # a "0% busy" reading.
        if not (0 <= util.gpu <= 100) or not (0 <= util.memory <= 100):
            return None, None, f"utilization out of range ({util.gpu}%)"
        return int(util.gpu), int(util.memory), None

    def _memory_v1_witness(self, handle):
        """
        v1's `used` in bytes, as an independent witness of the v2 field layout.

        Returns None when v1 is unavailable or declines, which is not an error:
        on such a driver the v2 layout simply goes unconfirmed.

        The identity is `v1.used == v2.used + v2.reserved`, verified on this
        driver. It holds because NVML folds the reserved region into v1's `used`
        and breaks it out in v2 - so the two calls have to agree, and a field
        order we got wrong cannot make them agree by accident.
        """
        fn = self._fn.get("nvmlDeviceGetMemoryInfo")
        if fn is None:
            return None
        try:
            mem = _NvmlMemory()
            if fn(handle, byref(mem)) != _NVML_SUCCESS:
                return None
            if mem.total <= 0 or mem.used < 0 or mem.used > mem.total:
                return None
            return int(mem.used)
        except Exception:
            return None

    def _memory(self, handle, expected_total_mb):
        """
        VRAM total and used in MB, or (None, None, reason).

        Tries v2 then v1 and validates the result. Each entry point is paired
        with its OWN struct - see _NvmlMemoryV2, sharing the v1 struct with the
        v2 call is a 16-byte buffer overflow that is dormant only on drivers
        that decline v2.

        Validation is layered, and every layer is a failure the return code
        cannot see on its own:
          * the values must be internally consistent - total > 0,
            free <= total, used <= total, and total == free + used (plus
            `reserved` on v2), checked in **bytes** so that integer flooring
            into MB cannot manufacture a violation;
          * the total must agree with the dedicated VRAM the registry reported
            for this adapter, within a tolerance;
          * on v2, the field layout is confirmed against v1 as an independent
            witness - see below, because the conservation check has a real hole.

        ── Why the conservation check is necessary but NOT sufficient ──
        A conservation sum is order-independent. If the true layout were
        (version, total, free, used, reserved) rather than the one declared
        here, every field still lands in range, the three still sum to total,
        and total still matches the registry - all four checks pass, and the
        panel confidently displays `free` as though it were `used`. Measured on
        this box: 3459 MB shown against a true 544 MB.

        So v2 is cross-checked against v1, which is a genuinely independent
        witness because NVML folds the reserved region into v1's `used` and
        reports it separately in v2. Verified on this driver:
        `v1.used == v2.used + v2.reserved` exactly (636 == 544 + 92). A wrong
        field order breaks that identity, so this catches what conservation
        cannot. v1 is absent on some drivers, in which case v2 stands on its
        own checks - a degraded guarantee, not a wrong one.
        """
        reasons = []
        # v2 first: it is the correct call where it is supported, and
        # unsupported means it declines, not that it lies.
        for symbol, is_v2 in (("nvmlDeviceGetMemoryInfo_v2", True),
                              ("nvmlDeviceGetMemoryInfo", False)):
            fn = self._fn.get(symbol)
            if fn is None:
                reasons.append(f"{symbol} absent")
                continue
            try:
                if is_v2:
                    mem = _NvmlMemoryV2()
                    mem.version = _NVML_MEMORY_V2_VERSION
                else:
                    mem = _NvmlMemory()
                rc = fn(handle, byref(mem))
            except Exception as e:
                reasons.append(f"{symbol} raised {type(e).__name__}")
                continue
            if rc != _NVML_SUCCESS:
                reasons.append(f"{symbol} returned {rc}")
                continue

            # In bytes, so no flooring error can look like a violation.
            total, free, used = int(mem.total), int(mem.free), int(mem.used)
            reserved = int(mem.reserved) if is_v2 else 0

            if total <= 0:
                reasons.append(f"{symbol} reported total=0")
                continue

            used_excl_reserved, convention, why = _reconcile_memory(
                total, free, used, reserved)
            if used_excl_reserved is None:
                reasons.append(f"{symbol} {why}")
                continue

            if is_v2:
                witness = self._memory_v1_witness(handle)
                # The witness relation depends on the convention, so it is
                # checked against the one just established - which keeps it
                # sharp instead of accepting either and proving nothing.
                expected_witness = used + reserved \
                    if convention == "separate" else used
                if witness is None:
                    # v1 unavailable. v2's own checks stand; the layout is
                    # unconfirmed rather than wrong.
                    pass
                elif abs(witness - expected_witness) > _LAYOUT_TOLERANCE_BYTES:
                    reasons.append(
                        f"{symbol} field layout disagrees with v1: our reading "
                        f"implies used{'+reserved' if convention == 'separate' else ''}"
                        f"={expected_witness} but v1 reports {witness}")
                    # Fall through to v1 rather than trusting a layout we have
                    # just been shown we may have wrong.
                    continue

            total_mb = total // _MB
            used_mb = used_excl_reserved // _MB

            # Cross-check against the registry. This is the guard that catches
            # the 32-bit-struct misread even if a future driver returns rc=0
            # for it, because that misread reports total=0 - and, more usefully,
            # catches us being handed a handle for a different device than the
            # adapter we think we are sampling.
            if expected_total_mb:
                slack = max(_VRAM_TOLERANCE_MB,
                            int(expected_total_mb * _VRAM_TOLERANCE_FRACTION))
                if abs(total_mb - expected_total_mb) > slack:
                    reasons.append(
                        f"{symbol} total {total_mb}MB disagrees with the "
                        f"registry's {expected_total_mb}MB by more than {slack}MB")
                    continue
            return total_mb, used_mb, None

        return None, None, "; ".join(reasons) or "no usable memory call"

    def _device_name(self, handle, index):
        """The adapter's marketing name, or a stable placeholder."""
        fn = self._fn.get("nvmlDeviceGetName")
        if fn is None:
            return f"NVIDIA GPU {index}"
        try:
            buf = ctypes.create_string_buffer(96)
            if fn(handle, buf, 96) == _NVML_SUCCESS and buf.value:
                return buf.value.decode("utf-8", "replace")
        except Exception:
            pass
        return f"NVIDIA GPU {index}"

    def sample_matched(self, gpus, force=False):
        """
        Samples every device and joins it to the inventory list.

        Returns (readings, extras) where:
          readings is {index into `gpus`: reading}
          extras   is [reading, ...] for devices the inventory never listed

        The inventory is a parameter rather than being matched afterwards
        because the registry's dedicated VRAM is what validates the NVML
        numbers - see _memory. Doing it in one pass also means the join
        cannot be done twice and drift.

        `force` bypasses the NVML-init backoff after a failure, so an operator
        who just attached hardware does not have to wait out the interval.
        """
        readings, extras = {}, []
        if not self.ensure_ready(force=force):
            return readings, extras

        devices, err = self._devices()
        if err:
            # A transient enumeration failure is not a load failure, so the
            # session stays ready and the next poll retries.
            self.reason = err
            return readings, extras

        # Inventory entries still waiting for a device. Cards with no NVML
        # counterpart (Intel iGPU, AMD without the driver loaded) drop out on
        # their own and are reported as unmeasured by the caller.
        unclaimed = list(range(len(gpus)))

        for index, handle in devices:
            name = self._device_name(handle, index)
            target = None
            expected_total = None

            # Pass 1: a confident name match.
            for pos in unclaimed:
                if _adapters_match(gpus[pos].get("name"), name):
                    target = pos
                    break
            # Pass 2: vendor only. Linux names its cards "NVIDIA GPU
            # (0x10de:0x1c82)", so names can never line up there, and appending
            # instead would show the operator a phantom second GPU.
            if target is None:
                for pos in unclaimed:
                    vendor = (gpus[pos].get("vendor") or "").lower()
                    if vendor in _NVML_VENDOR_IDS and _looks_nvidia(name):
                        target = pos
                        break

            reading = {"name": name, "util_percent": None,
                       "memory_util_percent": None, "vram_used_mb": None,
                       "vram_total_mb": None, "reason": None}

            util, mem_util, why = self._utilization(handle)
            reading["util_percent"] = util
            reading["memory_util_percent"] = mem_util
            if why:
                reading["reason"] = why

            if target is not None:
                unclaimed.remove(target)
                expected_total = gpus[target].get("vram_total_mb") or None
                reading["name"] = gpus[target].get("name") or name

            total_mb, used_mb, why = self._memory(handle, expected_total)
            reading["vram_total_mb"] = total_mb
            reading["vram_used_mb"] = used_mb
            if why and not reading["reason"]:
                # Both metrics failing is the notable case; one failing is not.
                if util is None and total_mb is None:
                    reading["reason"] = why

            if target is None:
                extras.append(reading)
            else:
                readings[target] = reading

        return readings, extras


# One process-wide session. NVML init is process-global.
_SESSION = _NvmlSession()


# ── Non-NVIDIA telemetry: Linux sysfs ───────────────────────────────────────

def _read_int(path):
    """
    Reads a sysfs integer, or None. Amd/Intel expose utilisation as
    gpu_busy_percent / gt_busy_percent; VRAM as mem_info_vram_used.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def sample_sysfs_gpus(linux_cards):
    """
    Telemetry for the AMD/Intel cards hardware_probe already listed from
    /sys/class/drm. Best-effort per metric: a card that exposes VRAM but not
    busy percent yields VRAM used and None for utilisation, not a false 0.
    """
    out = {}
    for card in linux_cards:
        # _gpus_linux stashes the sysfs device directory on the card for this.
        dev = card.get("_sysfs_device")
        if not dev or not os.path.isdir(dev):
            continue

        util = None
        for field in ("gpu_busy_percent", "gt_busy_percent"):
            value = _read_int(os.path.join(dev, field))
            if value is not None and 0 <= value <= 100:
                util = value
                break

        # UNITS. Everything amdgpu/xe publishes under mem_info_vram_* is in
        # **bytes**, while hardware_probe's inventory field is already in MB.
        # Reading sysfs' total and handing it on as `vram_total_mb` produced an
        # 8-gigabyte-looking "8192 GB" and a VRAM percentage of effectively
        # zero - a silent wrong answer that still looked like a measurement.
        # So both figures are normalised to MB here, and neither is mixed with
        # the other one's units.
        used_bytes = _read_int(os.path.join(dev, "mem_info_vram_used"))
        total_bytes = _read_int(os.path.join(dev, "mem_info_vram_total"))

        used_mb = used_bytes // _MB if used_bytes is not None else None
        if total_bytes is not None:
            total_mb = total_bytes // _MB
        else:
            # No sysfs total: the inventory's own figure is already in MB.
            total_mb = card.get("vram_total_mb") or None

        out[card["name"]] = {
            "util_percent": util,
            "memory_util_percent": None,
            "vram_used_mb": used_mb,
            "vram_total_mb": total_mb,
            "reason": None if util is not None
                      else "driver does not expose GPU busy percent on sysfs",
        }
    return out


# ── Joining telemetry onto the inventory ────────────────────────────────────

def _normalise(name):
    """Lowercase and drop everything non-alphanumeric, for tolerant matching."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _adapters_match(registry_name, telemetry_name):
    """
    True when a registry adapter and a telemetry device are the same hardware.

    Containment rather than equality: the registry is authoritative for names
    and typically says "NVIDIA GeForce GTX 1050 Ti", while NVML says
    "GeForce GTX 1050 Ti" on some driver versions.
    """
    a, b = _normalise(registry_name), _normalise(telemetry_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


# PCI vendor id for NVIDIA, as sysfs spells it.
_NVML_VENDOR_IDS = ("0x10de", "10de")


def _looks_nvidia(name):
    """True for an NVML device name. NVML only ever enumerates NVIDIA parts."""
    return "nvidia" in _normalise(name) or "geforce" in _normalise(name)


# ── Known limitation of the join, stated rather than implied ────────────────
#
# The registry/sysfs inventory and the NVML device list are two independent
# enumerations, and they are joined by name (then by vendor id as a fallback).
# That is a *guess*, not an identity. A box with two identical cards - or a
# hybrid-GPU laptop where the same silicon appears twice - can bind a reading
# to the wrong physical device, and the VRAM cross-check in _memory will not
# catch it when both cards have the same amount of memory.
#
# Making it authoritative means matching PCI location: NVML exposes
# nvmlDeviceGetPciInfo_v3's busId, and the registry carries the adapter's PCI
# path too. That is a larger change than it looks (it needs a Windows-side PCI
# enumeration), so it is not done here. What matters for now is that the join is
# documented as best-effort rather than allowed to read as exact.


def attach_gpu_telemetry(gpus, platform_system, force=False):
    """
    Attaches live utilisation to an inventory list, in place per adapter, and
    returns (adapters, aggregate) where aggregate carries the top-level keys
    the UI reads.

    `gpus` is the list hardware_probe already built (name, vram_total_mb,
    shared_memory). Each entry gains util_percent / vram_used_mb when
    measurable, and gpu_telemetry_reason when not.

    `force` bypasses the NVML-init backoff, for an operator-initiated re-scan.

    Never raises: a telemetry failure must degrade the panel, not fail the
    whole hardware scan, which also feeds the ingestion budget.

    Mutates `gpus` in place (and may append to it, for adapters the inventory
    missed) while also returning it. It is therefore not idempotent if called
    twice on the same list - safe today because _gpu() builds a fresh list per
    scan, but worth knowing before reusing it.
    """
    source = None
    reason = None
    readings = {}
    extras = []

    # Default every field first. A card that never gets a reading is then
    # "unmeasured" by construction rather than by a missing key, which is what
    # stops the UI from rendering an absent value as 0%.
    for card in gpus:
        card.setdefault("util_percent", None)
        card.setdefault("vram_used_mb", None)
        card.setdefault("vram_total_mb", None)
        card.setdefault("gpu_telemetry_reason", None)

    try:
        readings, extras = _SESSION.sample_matched(gpus, force=force)
        if readings or extras:
            source = "nvml"
        else:
            reason = _SESSION.reason
    except Exception as e:
        reason = f"GPU telemetry raised {type(e).__name__}: {e}"

    # sysfs is a Linux-only path, and only worth trying when NVML gave us
    # nothing - it covers the AMD and Intel cards NVML cannot see at all.
    if not readings and not extras and platform_system == "Linux":
        try:
            sysfs = sample_sysfs_gpus(gpus)
            if sysfs:
                source = "sysfs"
                for pos, card in enumerate(gpus):
                    hit = sysfs.get(card.get("name"))
                    if hit:
                        readings[pos] = hit
        except Exception as e:
            reason = f"sysfs GPU telemetry raised {type(e).__name__}: {e}"

    # A discrete GPU is present but nothing can measure it. Say so plainly -
    # "0% GPU" while a transcription quietly runs on the CPU is the exact lie
    # this module exists to prevent.
    has_discrete = any(not g.get("shared_memory") for g in gpus)
    if not readings and not extras:
        if reason is None and has_discrete:
            reason = ("a discrete GPU is present but this machine exposes no "
                      "utilisation source for it")
        elif reason is None:
            reason = "no GPU on this machine reports utilisation"

    best_util = None
    vram_used_total = 0
    vram_seen = False
    # The total of the adapters that ACTUALLY contributed a used figure. The
    # inventory-wide total (`gpu_vram_total_mb`, summed by hardware_probe over
    # every card) is a different denominator and pairing the two produces a
    # wrong ratio: on a box with a measurable 4 GB card and an unmeasurable
    # integrated one, 500 MB of 8 GB reads as 6% when the real figure is 12%.
    # That is a silently wrong number, which outranks a missing one.
    vram_measured_total = 0

    def _accumulate(reading):
        """Folds one reading into the aggregates. Returns nothing."""
        nonlocal best_util, vram_used_total, vram_seen, vram_measured_total
        if reading.get("util_percent") is not None:
            best_util = reading["util_percent"] if best_util is None \
                else max(best_util, reading["util_percent"])
        if reading.get("vram_used_mb") is not None:
            vram_used_total += reading["vram_used_mb"]
            vram_seen = True
            total_mb = reading.get("vram_total_mb")
            if total_mb:
                vram_measured_total += total_mb

    for pos, reading in readings.items():
        card = gpus[pos]
        card["util_percent"] = reading.get("util_percent")
        card["vram_used_mb"] = reading.get("vram_used_mb")
        if reading.get("vram_total_mb"):
            card["vram_total_mb"] = reading["vram_total_mb"]
        card["gpu_telemetry_reason"] = reading.get("reason")
        _accumulate(reading)

    # Cards that no source could measure, so the UI can say why per adapter
    # rather than only in aggregate. The reason has to be card-specific: a
    # shared-memory iGPU that NVML cannot enumerate is a different situation
    # from a discrete card no source recognised, and both are different from
    # telemetry being broken machine-wide.
    for pos, card in enumerate(gpus):
        if pos in readings or card.get("util_percent") is not None:
            continue
        if card.get("gpu_telemetry_reason") is None:
            if source is None:
                card["gpu_telemetry_reason"] = reason
            elif card.get("shared_memory"):
                card["gpu_telemetry_reason"] = (
                    "integrated adapter - no utilisation counter is exposed "
                    "for it on this platform")
            else:
                card["gpu_telemetry_reason"] = (
                    f"no {source} telemetry source matched this adapter")

    # Adapters the inventory missed but telemetry knows about. Better to show a
    # GPU the registry walk skipped than to hide real hardware.
    for reading in extras:
        card = {
            "name": reading.get("name") or "GPU",
            # None, not 0. An unknown VRAM total is not a zero-VRAM card, and
            # `or 0` here quietly converted the first into the second - which
            # is the exact substitution this module exists to refuse. The UI
            # already treats a missing total as "shared / unknown".
            "vram_total_mb": reading.get("vram_total_mb"),
            "shared_memory": False,
            "util_percent": reading.get("util_percent"),
            "vram_used_mb": reading.get("vram_used_mb"),
            "gpu_telemetry_reason": reading.get("reason"),
        }
        gpus.append(card)
        _accumulate(reading)

    # How much of the inventory we actually managed to measure. Reported even
    # when the headline number exists, because a single measured adapter on a
    # mixed machine makes the aggregate look complete when it is not.
    measured = sum(1 for c in gpus if c.get("util_percent") is not None)
    total_cards = len(gpus)

    if best_util is None:
        # A utilisation figure was never obtained. The reason matters, and the
        # UI shows it in place of a number.
        if reason is None:
            reason = "GPU utilisation is not measurable on this machine"
    elif measured < total_cards:
        # A number exists, but it is the *busiest measured* adapter, not a
        # reading of the whole machine. Saying so is the difference between
        # "the GPU is idle" and "the one adapter I could measure is idle" -
        # and on a box where the unmeasured card is the one doing the work,
        # that difference is the whole answer.
        unmeasured = total_cards - measured
        reason = (f"{unmeasured} of {total_cards} adapters expose no "
                  f"utilisation counter on this machine - the figure shown is "
                  f"the busiest measured adapter")

    aggregate = {
        # The busiest adapter, so a multi-GPU box shows the one doing the work
        # rather than an average that hides it.
        "gpu_util_percent": best_util,
        "gpu_vram_used_mb": vram_used_total if vram_seen else None,
        # The denominator that actually matches the numerator above. The UI must
        # prefer this over the inventory-wide `gpu_vram_total_mb` whenever it
        # is present, or the percentage it renders is a ratio of two different
        # populations. None when no adapter reported both figures.
        "gpu_vram_measured_total_mb": vram_measured_total or None,
        "gpu_util_available": best_util is not None,
        "gpu_telemetry_source": source,
        "gpu_telemetry_reason": reason,
        # Explicit coverage, so the UI can qualify the number instead of
        # implying the whole machine was measured.
        "gpu_adapters_measured": measured,
        "gpu_adapters_total": total_cards,
    }
    if _SESSION.driver_version:
        aggregate["gpu_driver_version"] = _SESSION.driver_version
    return gpus, aggregate
