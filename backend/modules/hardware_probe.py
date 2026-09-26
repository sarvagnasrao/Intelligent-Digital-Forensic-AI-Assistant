"""
backend/modules/hardware_probe.py

Live hardware and device inventory for the machine the app is running on.

Everything here is re-detected on each call, because for a forensics
workstation the inventory is not static in practice:
  * evidence drives get attached and detached between cases
  * USB / removable volumes appear mid-session
  * external GPUs (eGPU) come and go over Thunderbolt
  * network interfaces change when a dongle is plugged in

A very short TTL (DEFAULT_TTL_SECONDS) exists only so that a UI polling
every few seconds does not re-walk the registry and the PCI tree each
time. Pass force=True, or call rescan_hardware(), after plugging something
in to pick it up immediately.

Design constraints (see AGENTS.md section 9):
  * stdlib + psutil only. No new third-party dependency, because this
    project ships as an air-gap install kit and every dependency has to be
    vendored.
  * No OS shell calls. Windows uses the registry via stdlib `winreg`,
    Linux reads /proc and /sys, macOS falls back to what `platform` gives
    us. Nothing is shelled out to.
"""

import os
import platform
import re
import threading
import time

import psutil

DEFAULT_TTL_SECONDS = 4.0

_cache = None
_cache_at = 0.0
_cache_key = None
_lock = threading.Lock()


def _decode(value):
    """Registry values arrive as bytes, sometimes UTF-16LE (Intel writes
    UTF-16, NVIDIA writes ASCII). Strip NULs and decode defensively."""
    if isinstance(value, bytes):
        if b"\x00" in value[:4]:
            text = value.decode("utf-16-le", errors="ignore")
        else:
            text = value.decode("ascii", errors="ignore")
        return text.replace("\x00", "").strip()
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    return value


# ── CPU ──────────────────────────────────────────────────────────────────────

def _reg_query(key, name):
    """Read one registry value, tolerating absence. winreg is imported
    here rather than at module scope so this stays a no-op off Windows."""
    import winreg
    try:
        return _decode(winreg.QueryValueEx(key, name)[0])
    except (OSError, ImportError):
        return None


def _cpu_model_windows():
    """ProcessorNameString lives under CentralProcessor\\<n>.

    Opening the '0' subkey by full path is unreliable (it intermittently
    reports zero values), so enumerate the parent's subkeys and take the
    first processor that names itself.
    """
    import winreg
    base = r"HARDWARE\DESCRIPTION\System\CentralProcessor"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return None
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                name = winreg.EnumKey(root, i)
                sub = winreg.OpenKey(root, name)
            except OSError:
                continue
            with sub:
                value = _reg_query(sub, "ProcessorNameString")
            if value:
                return value
    return None


def _cpu_model_linux():
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8",
                  errors="ignore") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _cpu_model():
    system = platform.system()
    if system == "Windows":
        model = _cpu_model_windows()
    elif system == "Linux":
        model = _cpu_model_linux()
    else:
        model = None
    return model or platform.processor() or "Unknown CPU"


def _cpu():
    out = {
        "cpu_model": _cpu_model(),
        "cpu_count_logical": psutil.cpu_count(logical=True) or 0,
        "cpu_count_physical": psutil.cpu_count(logical=False) or 0,
    }
    try:
        freq = psutil.cpu_freq()
    except Exception:
        freq = None
    if freq is not None:
        if getattr(freq, "current", None):
            out["cpu_freq_mhz"] = int(freq.current)
        if getattr(freq, "max", None):
            out["cpu_freq_max_mhz"] = int(freq.max)
    out.setdefault("cpu_freq_mhz", None)
    out.setdefault("cpu_freq_max_mhz", None)
    out["cpu_percent"] = psutil.cpu_percent(interval=0.3)
    return out


# ── GPU ──────────────────────────────────────────────────────────────────────

def _gpus_windows():
    """Adapter name and dedicated VRAM from the video controller registry.

    Each physical adapter appears once per output (0000, 0001, ...) and a
    multi-GPU box has one GUID per adapter, so results are de-duplicated by
    name, keeping the largest VRAM seen for that name.
    """
    import winreg
    base = r"SYSTEM\CurrentControlSet\Control\Video"
    found = {}
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return []
    with root:
        guid_count = winreg.QueryInfoKey(root)[0]
        for i in range(guid_count):
            try:
                guid = winreg.EnumKey(root, i)
                sub = winreg.OpenKey(root, guid)
            except OSError:
                continue
            with sub:
                instances = winreg.QueryInfoKey(sub)[0]
                for j in range(instances):
                    try:
                        inst = winreg.EnumKey(sub, j)
                        key = winreg.OpenKey(sub, inst)
                    except OSError:
                        continue
                    with key:
                        name = _reg_query(key, "HardwareInformation.AdapterString")
                        if not name:
                            name = _reg_query(key, "DriverDesc")
                        if not name:
                            continue
                        vram = 0
                        for field in ("HardwareInformation.qwMemorySize",
                                      "HardwareInformation.MemorySize"):
                            try:
                                vram = max(vram, int(winreg.QueryValueEx(
                                    key, field)[0]))
                            except (OSError, TypeError, ValueError):
                                pass
                    # Integrated adapters report the shared system frame
                    # buffer size here, not dedicated VRAM. Flag it so the
                    # UI can say "shared" rather than implying dedicated
                    # memory that does not exist. Arc is a real discrete
                    # part despite the "Intel(R) ... Graphics" wording.
                    shared = bool(
                        re.search(r"(?i)intel.*(hd|uhd|iris)", name)
                        and not re.search(r"(?i)\barc\b", name))
                    prev = found.get(name)
                    if prev is None or vram > prev["vram_total_mb"]:
                        found[name] = {
                            "name": name,
                            "vram_total_mb":
                                vram // (1024 * 1024) if vram else 0,
                            "shared_memory": shared,
                        }
    return list(found.values())


def _gpus_linux():
    """Vendor/device ids and VRAM from sysfs."""
    cards = []
    base = "/sys/class/drm"
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return cards
    for entry in entries:
        if not re.match(r"^card\d+$", entry):
            continue
        dev = os.path.join(base, entry, "device")
        if not os.path.isdir(dev):
            continue  # connector entry, not a real device
        vendor = (_read_first(os.path.join(dev, "vendor")) or "?").lower()
        device = _read_first(os.path.join(dev, "device")) or "?"
        label = {"0x10de": "NVIDIA", "0x1002": "AMD",
                 "0x8086": "Intel"}.get(vendor, "GPU")
        vram = 0
        for field in ("mem_info_vram_total", "mem_info_vram"):
            raw = _read_first(os.path.join(dev, field))
            if raw and raw.isdigit():
                vram = int(raw) // (1024 * 1024)
                break
        cards.append({
            "name": "%s GPU (%s:%s)" % (label, vendor, device),
            "vram_total_mb": vram,
            "shared_memory": vram == 0,
        })
    return cards


def _read_first(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _gpu():
    system = platform.system()
    if system == "Windows":
        cards = _gpus_windows()
    elif system == "Linux":
        cards = _gpus_linux()
    else:
        # macOS exposes no stdlib GPU API. Do not shell out to
        # system_profiler (see module docstring); report nothing rather
        # than a wrong number.
        cards = []
    discrete = [g for g in cards if not g["shared_memory"]]
    return {
        "gpus": cards,
        "gpu_count": len(cards),
        "gpu_names": [g["name"] for g in cards],
        "gpu_vram_total_mb": sum(g["vram_total_mb"] for g in cards),
        "gpu_discrete_count": len(discrete),
        "gpu_vram_shared_only": bool(cards) and not discrete,
    }


# ── Storage devices ──────────────────────────────────────────────────────────
# The important dynamic inventory for a forensics box: every mounted
# volume, whether it is fixed or removable, how full it is, and whether it
# is writable. Evidence arrives on USB drives.

def _evidence_root():
    return (os.environ.get("IDFAI_DATA_DIR")
            or os.path.join(os.getcwd(), "data"))


def _volume_is_removable(opts):
    return "removable" in (opts or "")


def _storage():
    volumes = []
    seen = set()
    # all=True so USB / network volumes are included - that is exactly the
    # case an investigator cares about.
    for part in psutil.disk_partitions(all=True):
        key = (part.device, part.mountpoint)
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "device": part.device,
            "mountpoint": part.mountpoint,
            "fstype": part.fstype or "unknown",
            "opts": part.opts or "",
            "removable": _volume_is_removable(part.opts),
            "writable": "rw" in (part.opts or ""),
        }
        try:
            usage = psutil.disk_usage(part.mountpoint)
            entry["total_mb"] = usage.total // (1024 * 1024)
            entry["free_mb"] = usage.free // (1024 * 1024)
            entry["percent"] = usage.percent
        except (OSError, PermissionError):
            # Optical drives and disconnected volumes raise here.
            entry["total_mb"] = 0
            entry["free_mb"] = 0
            entry["percent"] = 0
        volumes.append(entry)

    # The store the evidence actually lands on, flagged so the UI can
    # highlight it rather than making the operator hunt. The store is a
    # directory *inside* a volume, so test containment, not equality.
    root = _evidence_root()
    root_abs = os.path.abspath(root) if os.path.exists(root) else None
    for v in volumes:
        v["is_evidence_store"] = False
        if not root_abs:
            continue
        mount = os.path.abspath(v["mountpoint"])
        try:
            same = os.path.commonpath([mount, root_abs]) == mount
        except ValueError:
            # Different drives (C: vs D:) - commonpath raises.
            same = False
        v["is_evidence_store"] = same
    evidence_volume = next(
        (v["device"] for v in volumes if v["is_evidence_store"]), None)

    total = sum(v["total_mb"] for v in volumes)
    free = sum(v["free_mb"] for v in volumes)
    percent = round((total - free) / total * 100, 1) if total else 0.0

    out = {
        "volumes": volumes,
        "volume_count": len(volumes),
        "removable_count": sum(1 for v in volumes if v["removable"]),
        "disk_total_mb": total,
        "disk_free_mb": free,
        "disk_percent": percent,
        "evidence_store": root_abs or root,
        "evidence_store_volume": evidence_volume,
        # Space on the volume holding the evidence store specifically,
        # which is the number that matters when deciding whether to accept
        # a 600 GB disk image.
        "evidence_free_mb": next(
            (v["free_mb"] for v in volumes if v["is_evidence_store"]), 0),
        "evidence_total_mb": next(
            (v["total_mb"] for v in volumes if v["is_evidence_store"]), 0),
    }

    try:
        io = psutil.disk_io_counters()
        if io is not None:
            out["disk_read_mb"] = io.read_bytes // (1024 * 1024)
            out["disk_write_mb"] = io.write_bytes // (1024 * 1024)
    except Exception:
        pass
    return out


# ── Network ──────────────────────────────────────────────────────────────────

def _network():
    adapters = []
    stats = {}
    try:
        stats = psutil.net_if_stats()
    except Exception:
        pass
    for name, addrs in psutil.net_if_addrs().items():
        mac = None
        ips = []
        for addr in addrs:
            if addr.family == getattr(psutil, "AF_LINK", None) and not mac:
                mac = addr.address
            elif addr.family == getattr(psutil, "AF_INET", None):
                ips.append(addr.address)
        st = stats.get(name)
        adapters.append({
            "name": name,
            "mac": mac,
            "ips": ips,
            "up": bool(st.isup) if st else True,
            "speed_mbps": st.speed if st else 0,
            # Virtual adapters (Hyper-V, VirtualBox, WSL) are noise in a
            # hardware panel; mark rather than hide so nothing is hidden
            # without the operator knowing.
            "virtual": bool(re.match(
                r"(?i)(loopback|pseudo|virtual|vmware|hyper-v|bluetooth|"
                r"local area connection\*|tap-|docker|wsll)", name)),
        })
    return {
        "network_adapters": adapters,
        "network_count": len(adapters),
        "network_physical_count": sum(
            1 for a in adapters if not a["virtual"]),
    }


# ── Power / machine ──────────────────────────────────────────────────────────

def _battery():
    try:
        bat = psutil.sensors_battery()
    except Exception:
        return {}
    if bat is None:
        return {"battery_percent": None, "on_ac": None, "is_laptop": False}
    return {
        "battery_percent": int(bat.percent) if bat.percent is not None else None,
        "on_ac": bool(bat.power_plugged),
        "is_laptop": True,
    }


def _machine():
    out = {
        "machine_manufacturer": None,
        "machine_model": None,
        "machine_sku": None,
        "bios_version": None,
        "hostname": platform.node() or None,
    }
    if platform.system() == "Windows":
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\BIOS")
        except OSError:
            return out
        with k:
            out["machine_manufacturer"] = _reg_query(k, "SystemManufacturer")
            out["machine_model"] = _reg_query(k, "SystemProductName")
            out["machine_sku"] = _reg_query(k, "SystemSKU")
            version = _reg_query(k, "BIOSVersion")
            if version:
                # HP and friends store "F.24, 07/05/2021, ..." - keep build.
                out["bios_version"] = version.split(",")[0].strip()
    return out


# ── Public API ───────────────────────────────────────────────────────────────

def scan_hardware() -> dict:
    """
    Full live re-scan. No cache involved - walks the registry, sysfs,
    partitions and NICs every time. Use this after attaching a drive or an
    eGPU, or from a "Rescan devices" button.
    """
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    spec = {}
    spec.update(_cpu())
    spec.update(_gpu())
    spec.update(_storage())
    spec.update(_network())
    spec.update(_machine())
    spec.update(_battery())

    spec["total_ram_mb"] = int(mem.total / 1024 / 1024)
    spec["available_ram_mb"] = int(mem.available / 1024 / 1024)
    spec["used_ram_mb"] = int(mem.used / 1024 / 1024)
    spec["ram_percent"] = mem.percent
    spec["swap_total_mb"] = int(swap.total / 1024 / 1024)
    spec["swap_used_mb"] = int(swap.used / 1024 / 1024)

    spec["platform_system"] = platform.system()
    spec["platform_release"] = platform.release()
    spec["platform_machine"] = platform.machine()
    spec["python_version"] = platform.python_version()
    spec["boot_time"] = int(psutil.boot_time())
    spec["scanned_at"] = int(time.time())

    # Backwards-compatible aliases for callers written before the richer
    # spec existed. EvidencePage and friends still read these.
    spec["cpu_count"] = spec["cpu_count_logical"]
    spec["platform"] = spec["platform_machine"] or "unknown"

    return spec


def get_hardware_spec(force: bool = False,
                      ttl: float = DEFAULT_TTL_SECONDS) -> dict:
    """
    Hardware + device inventory, re-scanned at most every `ttl` seconds.

    The TTL exists purely so a UI polling every few seconds does not walk
    the video registry and every NIC on each tick. It is deliberately
    short: hot-plugged evidence drives and eGPUs show up within seconds.
    Call with force=True (or rescan_hardware) to bypass it entirely.
    """
    global _cache, _cache_at, _cache_key

    with _lock:
        now = time.time()
        # Key the cache on a cheap fingerprint of the things that change
        # what is attached, so a plugged-in drive invalidates it even if
        # the TTL has not elapsed.
        fingerprint = _device_fingerprint()
        fresh = (_cache is not None
                  and now - _cache_at < ttl
                  and _cache_key == fingerprint)
        if fresh and not force:
            return _cache

        spec = scan_hardware()
        _cache, _cache_at, _cache_key = spec, now, fingerprint
        return spec


def rescan_hardware() -> dict:
    """Force an immediate re-scan and refresh the cache. Use after the
    operator attaches evidence media or an external GPU."""
    return get_hardware_spec(force=True, ttl=0)


def _device_fingerprint():
    """Cheap change-detector for attached devices: partition list and
    interface list. If either changes, the cached inventory is stale."""
    try:
        parts = psutil.disk_partitions(all=True)
        part_sig = tuple(sorted(p.device for p in parts))
    except Exception:
        part_sig = ()
    try:
        net_sig = tuple(sorted(psutil.net_if_addrs().keys()))
    except Exception:
        net_sig = ()
    return (part_sig, net_sig)
