"""
Guards the live GPU/CPU telemetry: NVML correctness, and the null-vs-zero
contract.

Everything asserted here is a class of failure that a return-code check does
NOT catch, which is why these bugs survived reading the code twice.

────────────────────────────────────────────────────────────────────────────
1. The NVML struct-width trap
────────────────────────────────────────────────────────────────────────────
Measured on this box (driver 582.66, GTX 1050 Ti), not assumed:

    nvmlDeviceGetMemoryInfo_v2 -> rc=2 (NOT_SUPPORTED), all fields 0
    nvmlDeviceGetMemoryInfo    -> rc=0, total=4096MB used=595MB   CORRECT
    nvmlDeviceGetMemoryInfo    -> rc=0, total=0MB    used=3501MB   when the
                                  ctypes struct fields are 32-bit

The third reports **success**. nvmlMemory_t is three `unsigned long long`, so
a 32-bit struct hands the callee a 12-byte buffer for a 24-byte write: total
reads 0 and "used" reads what is really free. So the guard is not the return
code, it is the values - total > 0, used <= total, and total cross-checked
against the dedicated VRAM the Windows registry already reported for that
adapter.

────────────────────────────────────────────────────────────────────────────
2. A metric that cannot be measured is None, never 0
────────────────────────────────────────────────────────────────────────────
None renders as an em dash. A fabricated 0 renders as "idle", and "idle"
during a two-hour transcription is the exact lie this exists to prevent. Most
of the assertions below exist to hold that line.

────────────────────────────────────────────────────────────────────────────
What is NOT asserted, and why
────────────────────────────────────────────────────────────────────────────
* Utilisation and VRAM-used are compared with a tolerance, never for exact
  equality against a separately-timed NVML read. They are live values on a
  jittering GPU; the ground truth here read 23% on one run and 0% on the next.
  An exact-match test would pass or fail on luck.
* vram_total_mb IS compared exactly, and that is the real proof the join landed
  on the right device - it is a stable per-adapter constant, and neither a
  mis-join nor a truncated struct can produce 4096 by accident.
* The AMD/Intel sysfs path and the Linux vendor-fallback join are exercised
  only structurally. This is a Windows box with one NVIDIA card, so those paths
  are unproven against real hardware and this file does not pretend otherwise.

Run:  PYTHONPATH=. python tests/verify_gpu_telemetry.py
"""
import os
import sys
import ctypes
import time
from ctypes import byref, c_uint, c_void_p, create_string_buffer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import psutil
from backend.modules.hardware_probe import scan_hardware, get_hardware_spec
from backend.modules import gpu_telemetry as gt
from backend.modules import hardware_probe as hp

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{'' if cond else '  -> ' + str(detail)}")
    return cond


# ── ground truth: a direct NVML read, independent of our join logic ────────

def direct_nvml():
    """Reads NVML the naive way, as a reference the probe is compared against."""
    if os.name != "nt":
        return None
    try:
        lib = ctypes.WinDLL("nvml.dll")
    except OSError:
        return None
    init = getattr(lib, "nvmlInit_v2", None) or getattr(lib, "nvmlInit", None)
    if init is None or init() != 0:
        return None

    count = c_uint()
    if lib.nvmlDeviceGetCount_v2(byref(count)) != 0:
        return None

    truth = {}
    for i in range(count.value):
        handle = c_void_p()
        if lib.nvmlDeviceGetHandleByIndex_v2(i, byref(handle)) != 0:
            continue
        name_buf = create_string_buffer(96)
        lib.nvmlDeviceGetName(handle, name_buf, 96)

        # Prefer v2, exactly as the module does, because the two are NOT
        # directly comparable: v1 folds the driver's reserved region into
        # `used`, v2 reports it separately. Comparing the probe's v2 reading
        # against a v1 ground truth showed a 92MB discrepancy on this box -
        # not a bug in either, just two different definitions of "used".
        mem = gt._NvmlMemoryV2()
        mem.version = gt._NVML_MEMORY_V2_VERSION
        rc = lib.nvmlDeviceGetMemoryInfo_v2(handle, byref(mem))
        if rc == 0:
            total, used = mem.total, mem.used
        else:
            mem1 = gt._NvmlMemory()
            if lib.nvmlDeviceGetMemoryInfo(handle, byref(mem1)) != 0:
                continue
            total, used = mem1.total, mem1.used

        util = gt._NvmlUtilization()
        lib.nvmlDeviceGetUtilizationRates(handle, byref(util))
        truth[name_buf.value.decode("utf-8", "replace")] = {
            "total": total // gt._MB,
            "used": used // gt._MB,
            "gpu": util.gpu,
        }
    return truth


def part_a_inventory_and_aggregates():
    print("\n=== A. the probe still reports what it always did ===")
    spec = scan_hardware()

    check("gpus list is present", bool(spec.get("gpus")), spec.get("gpus"))
    check("cpu_count_logical is sane", (spec.get("cpu_count_logical") or 0) > 0,
          spec.get("cpu_count_logical"))
    # The `mem.total / 1024 * 1024` precedence bug shipped once and made every
    # memory figure come back as raw bytes. Assert the MB range, not just
    # non-null, so it cannot come back.
    total_mb = spec.get("total_ram_mb") or 0
    check("total_ram_mb is megabytes, not raw bytes",
          256 < total_mb < 1024 * 4096, total_mb)
    check("ram_percent is measured", spec.get("ram_percent") is not None)

    check("cpu_percent is not None", spec.get("cpu_percent") is not None)
    # `x or -1` would be a bug here: an idle CPU reports 0, and `0 or -1` is -1.
    # The same falsy-zero confusion this module exists to prevent, so it is
    # worth being explicit rather than idiomatic here.
    cpu_pct = spec.get("cpu_percent")
    check("cpu_percent is a real percentage",
          cpu_pct is not None and 0 <= cpu_pct <= 100, cpu_pct)
    per_core = spec.get("cpu_per_core_percent")
    check("cpu_per_core_percent has one entry per logical core",
          isinstance(per_core, list)
          and len(per_core) == (spec.get("cpu_count_logical") or -1),
          per_core)
    check("every per-core figure is a real percentage",
          isinstance(per_core, list) and per_core
          and all(v is not None and 0 <= v <= 100 for v in per_core),
          per_core)

    for key in ("gpu_util_percent", "gpu_vram_used_mb", "gpu_util_available",
                "gpu_telemetry_source", "gpu_telemetry_reason"):
        check(f"aggregate key {key} exists", key in spec)

    # The inventory contract that predates all of this must not regress - the
    # ingestion budget, the volume list and the evidence-store check all read
    # this same dict.
    check("gpu_names still matches the gpus list",
          spec.get("gpu_names") == [g["name"] for g in spec["gpus"]])
    check("gpu_vram_total_mb is still computed",
          (spec.get("gpu_vram_total_mb") or 0) > 0)
    check("legacy cpu_count alias intact",
          spec.get("cpu_count") == spec.get("cpu_count_logical"))
    check("legacy platform alias intact", bool(spec.get("platform")))

    print("\n=== B. live values agree with a direct NVML read ===")
    truth = direct_nvml()
    if not truth:
        print("  SKIP  no NVML on this machine - nothing to compare against")
        return

    check("NVML is the telemetry source here",
          spec["gpu_telemetry_source"] == "nvml", spec["gpu_telemetry_source"])
    check("gpu_util_available is True", spec["gpu_util_available"] is True)
    check("gpu_util_percent is measured", spec["gpu_util_percent"] is not None)
    # `x or -1` would be a bug: an idle GPU reports 0 and `0 or -1` is -1. The
    # same falsy-zero confusion this module exists to prevent.
    gpu_pct = spec["gpu_util_percent"]
    check("gpu_util_percent is a real percentage",
          gpu_pct is not None and 0 <= gpu_pct <= 100, gpu_pct)
    # A measured GPU may still carry a *coverage* note - this box has an
    # integrated adapter with no counter. What must never appear is a note
    # that says the measurement itself failed.
    reason = spec["gpu_telemetry_reason"]
    check("a measured GPU reports no measurement-failure reason",
          reason is None or "busiest measured adapter" in str(reason), reason)
    check("coverage is reported explicitly",
          isinstance(spec.get("gpu_adapters_measured"), int)
          and isinstance(spec.get("gpu_adapters_total"), int),
          (spec.get("gpu_adapters_measured"), spec.get("gpu_adapters_total")))
    check("coverage never claims more adapters than exist",
          (spec.get("gpu_adapters_measured") or 0)
          <= (spec.get("gpu_adapters_total") or 0),
          (spec.get("gpu_adapters_measured"), spec.get("gpu_adapters_total")))

    for name, want in truth.items():
        card = next((g for g in spec["gpus"] if g["name"] == name), None)
        if not check(f"adapter row present for {name}",
                     card is not None, [g["name"] for g in spec["gpus"]]):
            continue
        # Exact: the stable per-adapter constant. This is the real evidence
        # the join found the right device.
        check(f"{name}: vram_total matches NVML exactly (device identity)",
              card["vram_total_mb"] == want["total"],
              f"{card['vram_total_mb']} vs {want['total']}")
        check(f"{name}: vram_used tracks NVML within 8MB",
              abs((card["vram_used_mb"] or 0) - want["used"]) <= 8,
              f"{card['vram_used_mb']} vs {want['used']}")
        check(f"{name}: vram_used does not exceed vram_total",
              (card["vram_used_mb"] or 0) <= (card["vram_total_mb"] or 0),
              card["vram_used_mb"])
        check(f"{name}: util is measured and in range",
              card["util_percent"] is not None
              and 0 <= card["util_percent"] <= 100, card["util_percent"])
        check(f"{name}: aggregate util equals the adapter's",
              spec["gpu_util_percent"] == card["util_percent"])
        check(f"{name}: aggregate vram_used equals the adapter's",
              spec["gpu_vram_used_mb"] == card["vram_used_mb"])


def part_b_the_struct_width_trap():
    print("\n=== C. the 32-bit struct misread is refused, not displayed ===")
    if os.name != "nt":
        print("  SKIP  NVML is Windows-only in this suite")
        return
    try:
        lib = ctypes.WinDLL("nvml.dll")
        if lib.nvmlInit_v2() != 0:
            print("  SKIP  NVML init failed")
            return
        count = c_uint()
        lib.nvmlDeviceGetCount_v2(byref(count))
        if count.value == 0:
            print("  SKIP  no NVML device")
            return
        handle = c_void_p()
        lib.nvmlDeviceGetHandleByIndex_v2(0, byref(handle))
        real_name_buf = create_string_buffer(96)
        lib.nvmlDeviceGetName(handle, real_name_buf, 96)
        real_name = real_name_buf.value.decode("utf-8", "replace")
    except OSError as e:
        print(f"  SKIP  cannot load nvml.dll: {e}")
        return

    class MemU32(ctypes.Structure):
        _fields_ = [("total", c_uint), ("free", c_uint), ("used", c_uint)]

    bad = MemU32()
    rc32 = lib.nvmlDeviceGetMemoryInfo(handle, byref(bad))
    # Establish that the trap is real on this driver. If a future driver stops
    # exhibiting it these two fail loudly rather than the guard looking
    # decorative.
    check("the u32 struct really does report success", rc32 == 0, rc32)
    check("the u32 struct really does report total=0",
          int(bad.total // gt._MB) == 0, bad.total)

    good = gt._NvmlMemory()
    lib.nvmlDeviceGetMemoryInfo(handle, byref(good))
    want_total = good.total // gt._MB

    total, used, why = gt._SESSION._memory(handle, want_total)
    check("our _memory returns the true total, not the u32 misread",
          total == want_total, f"{total} vs {want_total}")
    check("our _memory reports no failure for a healthy card", why is None, why)

    # An adapter whose registry VRAM disagrees with NVML is either a mis-join or
    # a driver reporting nonsense. Either way it must not be displayed.
    total, used, why = gt._SESSION._memory(handle, 999999)
    check("a VRAM total that disagrees with the registry is refused",
          total is None and used is None, (total, used))
    check("the refusal explains the disagreement",
          bool(why) and "disagrees" in str(why), why)

    # A registry total of 0 means "unknown", not "zero VRAM" - it must skip the
    # cross-check rather than fail it. The name must be the real one, or the
    # join cannot match and the reading lands on an appended adapter instead.
    adapters, _agg = gt.attach_gpu_telemetry(
        [{"name": real_name, "vram_total_mb": 0, "shared_memory": False}],
        "Windows")
    check("an inventory total of 0 skips the cross-check",
          len(adapters) == 1
          and (adapters[0]["vram_total_mb"] or 0) == want_total,
          [(a["name"], a["vram_total_mb"]) for a in adapters])
    check("and the reading is still attached to that one adapter",
          len(adapters) == 1 and adapters[0]["vram_used_mb"] is not None,
          [(a["name"], a["vram_used_mb"]) for a in adapters])


def _force_unavailable(reason):
    """
    Makes the NVML session report itself unusable.

    The timestamp matters: failure is no longer terminal, so a simulated
    failure with no `_failed_at` is a failure whose backoff has already
    expired, and the very next sample would quietly re-initialise NVML and
    succeed. Set it to "now" so this is a *recent* failure - which is the
    state the unmeasurable paths are actually about.
    """
    gt._SESSION.state = "unavailable"
    gt._SESSION.reason = reason
    gt._SESSION.lib = None
    gt._SESSION._fn = {}
    gt._SESSION._failed_at = time.monotonic()


def _save_session():
    return (gt._SESSION.state, gt._SESSION.reason, gt._SESSION.lib,
            dict(gt._SESSION._fn), gt._SESSION._failed_at)


def _restore_session(saved):
    (gt._SESSION.state, gt._SESSION.reason, gt._SESSION.lib,
     gt._SESSION._fn, gt._SESSION._failed_at) = saved


def part_c_null_never_zero():
    print("\n=== D. unmeasurable degrades to None + a reason, never 0 ===")
    saved = _save_session()
    try:
        for label, why in (
            ("no library", "NVML library not found"),
            ("init failed", "NVML init returned 9"),
            ("no functions", "NVML exports no device-enumeration functions"),
        ):
            _force_unavailable(why)
            adapters, agg = gt.attach_gpu_telemetry(
                [{"name": "NVIDIA GeForce GTX 1080", "vram_total_mb": 8192,
                  "shared_memory": False}], "Windows")
            card = adapters[0]
            check(f"[{label}] aggregate util is None, not 0",
                  agg["gpu_util_percent"] is None, agg["gpu_util_percent"])
            check(f"[{label}] gpu_util_available is False",
                  agg["gpu_util_available"] is False)
            check(f"[{label}] aggregate vram_used is None, not 0",
                  agg["gpu_vram_used_mb"] is None, agg["gpu_vram_used_mb"])
            check(f"[{label}] no source is claimed",
                  agg["gpu_telemetry_source"] is None)
            check(f"[{label}] a reason is reported",
                  bool(agg["gpu_telemetry_reason"]),
                  agg["gpu_telemetry_reason"])
            check(f"[{label}] per-adapter util is None, not 0",
                  card["util_percent"] is None, card["util_percent"])
            check(f"[{label}] per-adapter vram_used is None, not 0",
                  card["vram_used_mb"] is None, card["vram_used_mb"])
            check(f"[{label}] per-adapter carries a reason",
                  bool(card["gpu_telemetry_reason"]))
            # The inventory must survive: the budget, the volume list and the
            # evidence-store check all read this same dict.
            check(f"[{label}] adapter name preserved",
                  card["name"] == "NVIDIA GeForce GTX 1080", card["name"])
            check(f"[{label}] inventory VRAM preserved",
                  card["vram_total_mb"] == 8192, card["vram_total_mb"])

        # A machine with an iGPU only: nothing discrete to complain about, and
        # still no invented zero.
        _force_unavailable("NVML library not found")
        adapters, agg = gt.attach_gpu_telemetry(
            [{"name": "Intel(R) UHD Graphics 620", "vram_total_mb": 0,
              "shared_memory": True}], "Windows")
        check("integrated-only reports util None, not 0",
              agg["gpu_util_percent"] is None, agg["gpu_util_percent"])
        check("integrated-only still explains itself",
              bool(agg["gpu_telemetry_reason"]), agg["gpu_telemetry_reason"])
        check("integrated-only explains itself per adapter too",
              bool(adapters[0]["gpu_telemetry_reason"]),
              adapters[0]["gpu_telemetry_reason"])

        # No GPU at all.
        adapters, agg = gt.attach_gpu_telemetry([], "Darwin")
        check("no GPU reports util None", agg["gpu_util_percent"] is None)
        check("no GPU reports vram_used None", agg["gpu_vram_used_mb"] is None)
        check("no GPU claims no source", agg["gpu_telemetry_source"] is None)
        check("no GPU still explains itself",
              bool(agg["gpu_telemetry_reason"]), agg["gpu_telemetry_reason"])
    finally:
        _restore_session(saved)


def part_d_failures_are_contained():
    print("\n=== E. a telemetry failure degrades the panel, nothing more ===")
    saved_session = gt._SESSION

    class _Boom(gt._NvmlSession):
        # The signature must match: ensure_ready is called with force=, and a
        # stub that does not accept it raises TypeError, which would look like
        # a product bug rather than a stale test double.
        def ensure_ready(self, force=False):
            raise RuntimeError("simulated NVML explosion")

    gt._SESSION = _Boom()
    try:
        adapters, agg = gt.attach_gpu_telemetry(
            [{"name": "NVIDIA GeForce GTX 1080", "vram_total_mb": 8192,
              "shared_memory": False}], "Windows")
        check("a raising session degrades to None, not 0",
              agg["gpu_util_percent"] is None, agg["gpu_util_percent"])
        check("the exception is named in the reason",
              "RuntimeError" in str(agg["gpu_telemetry_reason"]),
              agg["gpu_telemetry_reason"])
        check("the inventory survives a raising session",
              adapters[0]["name"] == "NVIDIA GeForce GTX 1080")
    finally:
        gt._SESSION = saved_session

    # The worse case: the telemetry module itself is broken. hardware_probe
    # feeds the ingestion budget, the volume list and the evidence-store check,
    # so a metrics read must never be able to take down an inventory read.
    real_attach = hp.attach_gpu_telemetry

    def _explode(*a, **k):
        raise RuntimeError("attach exploded")

    hp.attach_gpu_telemetry = _explode
    try:
        spec = scan_hardware()
        check("scan_hardware survives a raising telemetry module",
              spec.get("gpu_util_percent") is None,
              spec.get("gpu_util_percent"))
        check("scan_hardware reports why telemetry is missing",
              bool(spec.get("gpu_telemetry_reason")))
        check("scan_hardware still returns the adapter inventory",
              bool(spec.get("gpus")) and bool(spec["gpus"][0].get("name")))
        check("scan_hardware still returns the CPU",
              (spec.get("cpu_count_logical") or 0) > 0)
        check("scan_hardware still returns RAM - the budget depends on it",
              256 < (spec.get("total_ram_mb") or 0) < 1024 * 4096)
        check("scan_hardware still returns the volume list",
              isinstance(spec.get("volumes"), list))
    finally:
        hp.attach_gpu_telemetry = real_attach

    # The cache must still work, or the 8s UI poll becomes a full re-walk.
    a = get_hardware_spec(force=True)
    b = get_hardware_spec()
    check("a second get_hardware_spec() is served from cache", a is b)


# ── the _vN struct rule ─────────────────────────────────────────────────────

def part_e_the_v2_struct_rule():
    """
    Each NVML entry point must be called with its OWN struct.

    This is the fix for a real latent buffer overflow, not a style point. The
    v2 entry point was being handed the 24-byte v1 struct, so a driver that
    supports v2 would have written 40 bytes through it - 16 past the end.

    It stayed dormant here only because an uninitialised `version` field made
    the driver reject the malformed request (rc=2) before it wrote anything,
    and the code then read that rejection as "v2 unsupported". So the masked
    bug and the masking are the same fact: the code believed v2 was
    unavailable when in fact it was being called wrongly.
    """
    print("\n=== F. each entry point gets its own struct ===")
    check("nvmlMemory_t is 24 bytes", ctypes.sizeof(gt._NvmlMemory) == 24,
          ctypes.sizeof(gt._NvmlMemory))
    check("nvmlUtilization_t is 8 bytes",
          ctypes.sizeof(gt._NvmlUtilization) == 8,
          ctypes.sizeof(gt._NvmlUtilization))
    # 40 = version(4) + abiPad(4) + total + reserved + free + used, all 64-bit.
    check("nvmlMemory_v2_t is 40 bytes, NOT the v1 layout",
          ctypes.sizeof(gt._NvmlMemoryV2) == 40,
          ctypes.sizeof(gt._NvmlMemoryV2))
    check("v2 is strictly larger than v1 - sharing a struct would overflow",
          ctypes.sizeof(gt._NvmlMemoryV2) > ctypes.sizeof(gt._NvmlMemory))
    # Modelled the way the C header declares it, not as one 64-bit field that
    # happens to land on the same offsets on this platform.
    check("the version word is 32-bit, as the C declaration has it",
          gt._NvmlMemoryV2.version.size == 4,
          gt._NvmlMemoryV2.version.size)
    check("the ABI pad occupies the next 4 bytes",
          gt._NvmlMemoryV2._abi_pad.offset == 4
          and gt._NvmlMemoryV2.total.offset == 8,
          (gt._NvmlMemoryV2._abi_pad.offset, gt._NvmlMemoryV2.total.offset))
    check("the 64-bit fields start 8-byte aligned",
          all(getattr(gt._NvmlMemoryV2, f).offset % 8 == 0
              for f in ("total", "reserved", "free", "used")),
          [getattr(gt._NvmlMemoryV2, f).offset
           for f in ("total", "reserved", "free", "used")])
    # NVML_STRUCT_VERSION: sizeof(struct) | (ver << 24)
    check("the v2 version handshake is sizeof|2<<24",
          gt._NVML_MEMORY_V2_VERSION
          == (ctypes.sizeof(gt._NvmlMemoryV2) | (2 << 24)),
          gt._NVML_MEMORY_V2_VERSION)

    if os.name != "nt":
        print("  SKIP  NVML is Windows-only in this suite")
        return
    try:
        lib = ctypes.WinDLL("nvml.dll")
        if lib.nvmlInit_v2() != 0:
            print("  SKIP  NVML init failed")
            return
        handle = c_void_p()
        lib.nvmlDeviceGetHandleByIndex_v2(0, byref(handle))
    except OSError as e:
        print(f"  SKIP  cannot load nvml.dll: {e}")
        return

    # Called correctly, with the version field filled in as the driver expects.
    good = gt._NvmlMemoryV2()
    good.version = gt._NVML_MEMORY_V2_VERSION
    rc = lib.nvmlDeviceGetMemoryInfo_v2(handle, byref(good))
    if rc != 0:
        print(f"  SKIP  this driver declines v2 (rc={rc}) - "
              f"the struct assertions above still applied")
        return

    check("v2 called with its own struct succeeds", rc == 0, rc)
    check("v2 reports the real VRAM total",
          (good.total // gt._MB) > 0, good.total)
    # The decisive check: the old code called v2 with a 24-byte struct and no
    # version, got rc=2, and concluded v2 was unsupported. If a correct call
    # now succeeds, the earlier rc=2 was our own malformed request.
    check("a correctly-built v2 call works, so the old rc=2 was a bad request",
          rc == 0,
          "if this ever returns 2, the struct or version handshake is wrong")
    check("v2 reconciles as total == reserved + free + used",
          abs(good.total - (good.reserved + good.free + good.used)) <= gt._MB,
          f"delta={good.total - (good.reserved + good.free + good.used)}")
    check("v1's formula would have wrongly rejected a correct v2 reading",
          abs(good.total - (good.free + good.used)) > gt._MB,
          "if this is false, the two layouts are indistinguishable here")

    # And the real code path must take the v2 branch and agree with it.
    total, used, why = gt._SESSION._memory(handle, None)
    check("_memory accepts a correct v2 reading", why is None, why)
    check("_memory's total matches the direct v2 read",
          total == good.total // gt._MB, f"{total} vs {good.total // gt._MB}")
    check("_memory's used matches the direct v2 read",
          used == good.used // gt._MB, f"{used} vs {good.used // gt._MB}")

    # The conservation check cannot see a field-order error, because a sum is
    # order-independent. v1 is the independent witness, so assert the identity
    # the witness depends on actually holds on this driver - if a future driver
    # changes the relationship, the guard must fail loudly rather than quietly
    # reject every v2 reading.
    v1raw = gt._NvmlMemory()
    lib.nvmlDeviceGetMemoryInfo(handle, byref(v1raw))
    check("v1.used == v2.used + v2.reserved on this driver (the witness holds)",
          abs(v1raw.used - (good.used + good.reserved))
          <= gt._LAYOUT_TOLERANCE_BYTES,
          f"v1.used={v1raw.used} vs v2 {good.used}+{good.reserved}")
    witness = gt._SESSION._memory_v1_witness(handle)
    check("the witness helper returns v1's used", witness == v1raw.used,
          (witness, v1raw.used))
    check("the witness agrees with the v2 reading it is meant to confirm",
          witness is not None
          and abs(witness - (good.used + good.reserved))
          <= gt._LAYOUT_TOLERANCE_BYTES, witness)

    # And the guard must actually fire: make the session's v2 struct declare the
    # fields in a different order, which is precisely the mistake conservation
    # cannot catch, and require the reading to be refused rather than displayed.
    #
    # NOTE: this must be a STANDALONE Structure, not a subclass. ctypes
    # *appends* a subclass's _fields_ to the base class's, so subclassing
    # _NvmlMemoryV2 yields an 80-byte struct - the driver's 40-byte write lands
    # in the base fields and the subclass's own fields stay zero. The first
    # version of this test did that and silently simulated nothing.
    saved_v2 = gt._NvmlMemoryV2

    class _Misordered(ctypes.Structure):
        """Same 40 bytes, but read as (version, total, free, used, reserved)."""
        _fields_ = [("version", gt.c_ulonglong), ("total", gt.c_ulonglong),
                    ("free", gt.c_ulonglong), ("used", gt.c_ulonglong),
                    ("reserved", gt.c_ulonglong)]

    check("the misordered stand-in is the same size as the real v2 struct",
          ctypes.sizeof(_Misordered) == ctypes.sizeof(saved_v2),
          (ctypes.sizeof(_Misordered), ctypes.sizeof(saved_v2)))
    check("and really does put `reserved` where `free` is",
          _Misordered.reserved.offset != saved_v2.reserved.offset,
          (_Misordered.reserved.offset, saved_v2.reserved.offset))

    gt._NvmlMemoryV2 = _Misordered
    try:
        mis_total, _mis_free, mis_used = gt._SESSION._memory(handle, None)
        v1_used = int(v1raw.used) // gt._MB
        misread_used = int(good.free) // gt._MB     # what a wrong order shows
        # Either the misread is refused outright, or the witness catches it and
        # we fall back to v1. What must never happen is v2's misread being
        # displayed - so the assertion pins the *value*, not just non-None.
        check("a misordered v2 struct never yields v2's misread",
              mis_used is None or abs(mis_used - misread_used) > 8,
              f"used={mis_used} (misread would be {misread_used}, "
              f"truth {good.used // gt._MB}, v1 {v1_used})")
        check("a misordered v2 struct is refused or downgraded to v1",
              mis_used is None or abs(mis_used - v1_used) <= 8,
              f"used={mis_used} vs v1 {v1_used}")
    finally:
        gt._NvmlMemoryV2 = saved_v2

    # With the correct struct restored, the same call must succeed again.
    ok_total, ok_used, ok_why = gt._SESSION._memory(handle, None)
    check("the correct struct is accepted again afterwards",
          ok_total == good.total // gt._MB and ok_why is None,
          (ok_total, ok_why))


def part_f_failure_is_not_terminal():
    """
    A failed NVML init must not be permanent for the life of the process.

    The driver can be absent when the backend starts and present later, and an
    eGPU gets plugged into a dock mid-session. With "unavailable" as a terminal
    state the panel would show a permanent em dash for a working GPU, and
    Rescan would not help - which is the opposite of what Rescan is for.
    """
    print("\n=== G. a failed session recovers ===")
    saved = _save_session()
    try:
        _force_unavailable("NVML library not found")
        gt._SESSION._failed_at = time.monotonic()

        # Inside the backoff window, a plain attempt must not hammer the load.
        check("a recent failure is not retried immediately",
              gt._SESSION.ensure_ready() is False)
        check("the reason survives the backoff",
              "not found" in gt._SESSION.reason, gt._SESSION.reason)

        # An operator pressing Rescan must not have to wait out the interval.
        check("force=True bypasses the backoff",
              gt._SESSION.ensure_ready(force=True) is True,
              gt._SESSION.reason)
        check("a successful retry clears the failure reason",
              gt._SESSION.reason == "", gt._SESSION.reason)
        check("a successful retry records no failure time",
              gt._SESSION._failed_at is None, gt._SESSION._failed_at)

        # And success stays cached, so this is not a per-poll NVML init.
        check("success is cached, not re-initialised every sample",
              gt._SESSION.ensure_ready() is True)

        # The backoff itself must expire even without a rescan.
        _force_unavailable("NVML library not found")
        gt._SESSION._failed_at = time.monotonic() - (gt._SESSION._RETRY_SECONDS + 1)
        check("an expired backoff retries on its own",
              gt._SESSION.ensure_ready() is True, gt._SESSION.reason)
    finally:
        _restore_session(saved)

    # The flag has to actually reach the telemetry. An earlier version of this
    # file spied on `sample_matched` and asserted it received force=True - which
    # would have passed even if the rescan path were never wired to it, because
    # it tested the plumbing rather than the outcome. Assert the outcome.
    saved_for_rescan = _save_session()
    try:
        _force_unavailable("NVML library not found")
        spec = hp.get_hardware_spec(force=True, ttl=0)
        check("a forced re-scan revives a failed NVML session",
              spec.get("gpu_util_available") is True,
              (spec.get("gpu_util_available"), spec.get("gpu_telemetry_reason")))
        check("and the revived session measures the card",
              spec.get("gpu_util_percent") is not None,
              spec.get("gpu_util_percent"))
    finally:
        _restore_session(saved_for_rescan)

    # Behavioural check of the same flag, without the hardware_probe path.
    saved2 = _save_session()
    try:
        _force_unavailable("NVML library not found")
        _adapters, agg = gt.attach_gpu_telemetry(
            [{"name": "NVIDIA GeForce GTX 1050 Ti", "vram_total_mb": 4096,
              "shared_memory": False}], "Windows", force=False)
        check("an ordinary poll inside the backoff stays dark",
              agg["gpu_util_available"] is False, agg["gpu_util_available"])
        _adapters, agg = gt.attach_gpu_telemetry(
            [{"name": "NVIDIA GeForce GTX 1050 Ti", "vram_total_mb": 4096,
              "shared_memory": False}], "Windows", force=True)
        check("force=True revives it",
              agg["gpu_util_available"] is True,
              (agg["gpu_util_available"], agg["gpu_telemetry_reason"]))
    finally:
        _restore_session(saved2)

    # NVML init is refcounted and this module never shuts down, so a probe that
    # initialised again after a success would leak a reference for the life of
    # the process. Success must therefore be latched.
    #
    # Count `_load_nvml`, not `ensure_ready`: wrapping ensure_ready would just
    # record that it was *called*, which says nothing about whether it did any
    # work. `_load_nvml` is reached only when a probe actually happens.
    saved3 = _save_session()
    try:
        loads = []
        real_load = gt._load_nvml

        def _counting_load():
            loads.append(1)
            return real_load()

        gt._load_nvml = _counting_load
        try:
            check("a ready session reports ready without probing",
                  gt._SESSION.ensure_ready() is True)
            check("a forced call on a ready session also skips the probe",
                  gt._SESSION.ensure_ready(force=True) is True)
            check("a ready session never re-initialises NVML",
                  loads == [], f"{len(loads)} library loads")
        finally:
            gt._load_nvml = real_load
    finally:
        _restore_session(saved3)


def part_g_sysfs_units():
    """
    sysfs reports bytes; the field it feeds is named vram_total_**mb**.

    Passing sysfs' byte count through unconverted produced "8192 GB" and a VRAM
    percentage of effectively zero - a wrong number that still looked like a
    measurement, which is the worst kind. Exercised against a real directory
    of fake sysfs nodes, because this is a Windows box and the live path
    cannot run here.
    """
    print("\n=== H. sysfs byte values are converted to MB ===")
    import tempfile
    with tempfile.TemporaryDirectory() as dev:
        def _write(name, value):
            with open(os.path.join(dev, name), "w", encoding="utf-8") as fh:
                fh.write(str(value))

        eight_gib = 8 * 1024 * 1024 * 1024
        _write("gpu_busy_percent", 37)
        _write("mem_info_vram_used", 2 * 1024 * 1024 * 1024)   # 2 GiB in bytes
        _write("mem_info_vram_total", eight_gib)

        card = {"name": "AMD GPU (0x1002:0x1636)", "vram_total_mb": 0,
                "vendor": "0x1002", "_sysfs_device": dev}
        readings = gt.sample_sysfs_gpus([card])
        hit = readings.get(card["name"])
        if not check("a sysfs card produces a reading", hit is not None, readings):
            return

        check("busy percent is read as given", hit["util_percent"] == 37,
              hit["util_percent"])
        check("VRAM used is converted from bytes to MB",
              hit["vram_used_mb"] == 2048, hit["vram_used_mb"])
        check("VRAM total is converted from bytes to MB, not passed through",
              hit["vram_total_mb"] == 8192, hit["vram_total_mb"])
        # The whole bug in one assertion: unconverted, this total dwarfs the
        # used figure and the ratio collapses to ~0.00002%.
        check("used/total is a real ratio, not a units artefact",
              abs((hit["vram_used_mb"] / hit["vram_total_mb"]) * 100 - 25.0) < 0.1,
              (hit["vram_used_mb"] / hit["vram_total_mb"]) * 100)
        check("an unmeasurable total is None, not 0",
              hit["vram_total_mb"] is not None, hit["vram_total_mb"])

    # No sysfs total at all: fall back to the inventory's own MB figure.
    with tempfile.TemporaryDirectory() as dev:
        with open(os.path.join(dev, "mem_info_vram_used"), "w",
                  encoding="utf-8") as fh:
            fh.write(str(1024 * 1024 * 1024))
        card = {"name": "AMD GPU (0x1002:0x1636)", "vram_total_mb": 4096,
                "vendor": "0x1002", "_sysfs_device": dev}
        hit = gt.sample_sysfs_gpus([card])[card["name"]]
        check("a missing sysfs total falls back to the inventory, in MB",
              hit["vram_total_mb"] == 4096, hit["vram_total_mb"])
        check("and used is still converted from bytes",
              hit["vram_used_mb"] == 1024, hit["vram_used_mb"])

    # A card with no counter at all must not invent a zero.
    with tempfile.TemporaryDirectory() as dev:
        card = {"name": "Intel GPU (0x8086:0x9a49)", "vram_total_mb": 0,
                "vendor": "0x8086", "_sysfs_device": dev}
        hit = gt.sample_sysfs_gpus([card])[card["name"]]
        check("a card exposing no busy percent reports None, not 0",
              hit["util_percent"] is None, hit["util_percent"])
        check("a card exposing no VRAM reports None, not 0",
              hit["vram_used_mb"] is None, hit["vram_used_mb"])
        check("and explains itself",
              "busy percent" in (hit["reason"] or ""), hit["reason"])


def part_h_coverage_and_unknown_totals():
    """
    A number must not imply the whole machine was measured, and an unknown
    VRAM total must not become zero.
    """
    print("\n=== I. partial coverage is stated, unknown totals stay None ===")
    saved = _save_session()
    real_sample = gt._SESSION.sample_matched
    try:
        # Simulate a measured reading arriving for a device the inventory never
        # listed - the "extra" path - with an unknown VRAM total, alongside an
        # integrated card nothing can measure.
        def _fake_sample(gpus, force=False):
            return {}, [{"name": "NVIDIA GeForce RTX 4090",
                         "util_percent": 44, "memory_util_percent": 12,
                         "vram_used_mb": 1024, "vram_total_mb": None,
                         "reason": None}]
        gt._SESSION.sample_matched = _fake_sample
        adapters, agg = gt.attach_gpu_telemetry(
            [{"name": "Intel(R) UHD Graphics 630", "vram_total_mb": 0,
              "shared_memory": True}], "Windows")

        check("the extra adapter is shown rather than hidden",
              len(adapters) == 2, [a["name"] for a in adapters])
        extra = adapters[1]
        check("an unknown VRAM total stays None, not 0",
              extra["vram_total_mb"] is None, extra["vram_total_mb"])
        check("its measured utilisation is carried through",
              extra["util_percent"] == 44, extra["util_percent"])
        check("coverage counts it as measured",
              agg["gpu_adapters_measured"] == 1, agg["gpu_adapters_measured"])
        check("coverage counts the unmeasured iGPU too",
              agg["gpu_adapters_total"] == 2, agg["gpu_adapters_total"])
        # The whole point: a number exists, but the machine was not fully read.
        check("a partial measurement still reports a reason",
              bool(agg["gpu_telemetry_reason"]), agg["gpu_telemetry_reason"])
        check("and the reason says how many were missed",
              "1 of 2" in str(agg["gpu_telemetry_reason"]),
              agg["gpu_telemetry_reason"])
    finally:
        gt._SESSION.sample_matched = real_sample
        _restore_session(saved)

    # With everything measured, there is no partial-coverage caveat.
    try:
        def _all_measured(gpus, force=False):
            return {0: {"name": gpus[0]["name"], "util_percent": 10,
                        "memory_util_percent": 5, "vram_used_mb": 100,
                        "vram_total_mb": 4096, "reason": None}}, []
        gt._SESSION.sample_matched = _all_measured
        _adapters, agg = gt.attach_gpu_telemetry(
            [{"name": "NVIDIA GeForce GTX 1050 Ti", "vram_total_mb": 4096,
              "shared_memory": False}], "Windows")
        check("full coverage reports no partial caveat",
              agg["gpu_telemetry_reason"] is None, agg["gpu_telemetry_reason"])
        check("full coverage counts one of one",
              agg["gpu_adapters_measured"] == 1
              and agg["gpu_adapters_total"] == 1,
              (agg["gpu_adapters_measured"], agg["gpu_adapters_total"]))
    finally:
        gt._SESSION.sample_matched = real_sample
        _restore_session(saved)


def part_i_used_conventions():
    """
    `used` may or may not include the driver's reserved region. Accept both.

    NVIDIA's reference describes nvmlMemory_v2_t.used as INCLUDING `reserved`;
    the driver on this box measures as EXCLUDING it (total == reserved + free +
    used, delta 0, while total == free + used is off by exactly the 92 MB
    reservation). Pinning one identity means a driver using the other has
    perfectly good data rejected and silently downgraded to v1 - which reports a
    different `used` again. Exercised synthetically because the live driver can
    only ever produce one of the two.
    """
    print("\n=== J. both `used` conventions are accepted and normalised ===")
    MB = gt._MB
    total = 4096 * MB
    reserved = 92 * MB
    app_used = 500 * MB
    free = total - reserved - app_used

    # A: used EXCLUDES reserved (what this driver does).
    used_a, conv, why = gt._reconcile_memory(total, free, app_used, reserved)
    check("convention A is accepted", why is None, why)
    check("convention A is detected as 'separate'", conv == "separate", conv)
    check("convention A reports used unchanged", used_a == app_used, used_a)

    # B: used INCLUDES reserved (what the docs describe).
    used_b, conv, why = gt._reconcile_memory(
        total, free, app_used + reserved, reserved)
    check("convention B is accepted, not rejected", why is None, why)
    check("convention B is detected as 'inclusive'", conv == "inclusive", conv)
    check("convention B is normalised to the same figure as A",
          used_b == app_used, (used_b, app_used))
    check("A and B converge on one meaning for `used`",
          used_a // MB == used_b // MB, (used_a // MB, used_b // MB))

    # A driver that satisfies neither is a genuine inconsistency, and must be
    # refused rather than displayed.
    _u, conv, why = gt._reconcile_memory(total, free // 2, app_used, 0)
    check("fields reconciling under neither convention are refused",
          why is not None and "neither convention" in why, why)

    # Ranges, still refused.
    for label, args in (("total=0", (0, 0, 0, 0)),
                        ("used > total", (total, free, total + MB, 0)),
                        ("free > total", (total, total + MB, 0, 0)),
                        ("negative used", (total, free, -1, 0))):
        _u, _c, why = gt._reconcile_memory(*args)
        check(f"{label} is refused", _u is None and why is not None,
              (args, why))

    # reserved == 0: the two conventions coincide and must not misfire.
    _u, conv, why = gt._reconcile_memory(total, total - app_used, app_used, 0)
    check("a zero reservation is not a special case", _u == app_used,
          (_u, why))
    check("and is still detected as a valid reading", why is None, why)

    # Sub-megabyte slack must be tolerated, not treated as a violation.
    slack = total - (reserved + (free + 512) + app_used)
    _u, _c, why = gt._reconcile_memory(total, free + 512, app_used, reserved)
    check("sub-megabyte driver slack is tolerated", why is None,
          f"delta={slack}: {why}")


def part_j_vram_ratio_denominator():
    """
    The VRAM percentage must divide by a total covering the same adapters as
    the numerator.

    `gpu_vram_total_mb` is summed over every card in the inventory; the used
    figure only sums the cards that were actually measurable. Pairing them is a
    ratio of two different populations, which silently understates usage.
    """
    print("\n=== K. the VRAM ratio uses a matching denominator ===")
    saved = _save_session()

    def _mixed(gpus, force=False):
        # Only the discrete card reports memory; the iGPU never does.
        return {1: {"name": gpus[1]["name"], "util_percent": 55,
                    "memory_util_percent": 40, "vram_used_mb": 1024,
                    "vram_total_mb": 4096, "reason": None}}, []

    real = gt._SESSION.sample_matched
    try:
        gt._SESSION.sample_matched = _mixed
        adapters, agg = gt.attach_gpu_telemetry(
            [{"name": "Intel(R) UHD Graphics 630", "vram_total_mb": 0,
              "shared_memory": True},
             {"name": "NVIDIA GeForce GTX 1050 Ti", "vram_total_mb": 4096,
              "shared_memory": False}], "Windows")
    finally:
        gt._SESSION.sample_matched = real
        _restore_session(saved)

    check("used VRAM sums the measured adapter", agg["gpu_vram_used_mb"] == 1024,
          agg["gpu_vram_used_mb"])
    check("a measured-only denominator is published",
          agg["gpu_vram_measured_total_mb"] == 4096,
          agg["gpu_vram_measured_total_mb"])
    # Here the unmeasured adapter has vram_total_mb = 0, so it contributes to
    # neither the inventory total nor the measured total and the two coincide.
    # That means this scenario CANNOT discriminate the denominator - the
    # scenario below is the one that can. Asserted so the limitation is on the
    # record rather than mistaken for coverage.
    check("with a 0-total unmeasured card the two denominators coincide",
          agg["gpu_vram_measured_total_mb"] == 0 + 4096,
          agg["gpu_vram_measured_total_mb"])

    # THE DISCRIMINATING CASE: an unmeasured adapter that has a real dedicated
    # total. This is the only shape in which the two denominators differ, and
    # therefore the only one that can prove the aggregate is not using the
    # inventory-wide figure.
    def _one_of_two(gpus, force=False):
        return {0: {"name": gpus[0]["name"], "util_percent": 70,
                    "memory_util_percent": 50, "vram_used_mb": 1024,
                    "vram_total_mb": 4096, "reason": None}}, []

    try:
        gt._SESSION.sample_matched = _one_of_two
        adapters, agg2 = gt.attach_gpu_telemetry(
            [{"name": "NVIDIA GeForce GTX 1050 Ti", "vram_total_mb": 4096,
              "shared_memory": False},
             # Dedicated, with a real total, but no counter on this driver.
             {"name": "AMD Radeon RX 6800", "vram_total_mb": 16384,
              "shared_memory": False}], "Windows")
    finally:
        gt._SESSION.sample_matched = real
        _restore_session(saved)

    inventory_total = 4096 + 16384
    check("the inventory-wide total really is larger here",
          inventory_total == 20480, inventory_total)
    check("the published denominator covers only the measured adapter",
          agg2["gpu_vram_measured_total_mb"] == 4096,
          agg2["gpu_vram_measured_total_mb"])
    check("so the two denominators demonstrably differ",
          agg2["gpu_vram_measured_total_mb"] != inventory_total,
          (agg2["gpu_vram_measured_total_mb"], inventory_total))
    correct = (agg2["gpu_vram_used_mb"]
               / agg2["gpu_vram_measured_total_mb"]) * 100
    naive = (agg2["gpu_vram_used_mb"] / inventory_total) * 100
    check("the published denominator gives the true ratio", abs(correct - 25.0) < 0.1,
          correct)
    check("the inventory-wide total would have understated it 5x",
          abs(naive - 5.0) < 0.1 and abs(correct / naive - 5.0) < 0.01,
          f"naive {naive} vs correct {correct}")
    check("the unmeasured dedicated card is still counted as an adapter",
          agg2["gpu_adapters_measured"] == 1
          and agg2["gpu_adapters_total"] == 2,
          (agg2["gpu_adapters_measured"], agg2["gpu_adapters_total"]))
    check("and the partial-coverage caveat is present",
          "1 of 2" in str(agg2["gpu_telemetry_reason"]),
          agg2["gpu_telemetry_reason"])

    # With nothing measured for VRAM there is no denominator to publish.
    def _no_vram(gpus, force=False):
        return {0: {"name": gpus[0]["name"], "util_percent": 3,
                    "memory_util_percent": 0, "vram_used_mb": None,
                    "vram_total_mb": 4096, "reason": "no counter"}}, []

    try:
        gt._SESSION.sample_matched = _no_vram
        _adapters, agg3 = gt.attach_gpu_telemetry(
            [{"name": "NVIDIA GeForce GTX 1050 Ti", "vram_total_mb": 4096,
              "shared_memory": False}], "Windows")
    finally:
        gt._SESSION.sample_matched = real
        _restore_session(saved)

    check("no VRAM figures at all means no denominator", 
          agg3["gpu_vram_measured_total_mb"] is None,
          agg3["gpu_vram_measured_total_mb"])
    check("and no used figure either", agg3["gpu_vram_used_mb"] is None,
          agg3["gpu_vram_used_mb"])


def main():
    for fn in (part_a_inventory_and_aggregates, part_b_the_struct_width_trap,
               part_c_null_never_zero, part_d_failures_are_contained,
               part_e_the_v2_struct_rule, part_f_failure_is_not_terminal,
               part_g_sysfs_units, part_h_coverage_and_unknown_totals,
               part_i_used_conventions, part_j_vram_ratio_denominator):
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
