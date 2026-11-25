"""Live hardware monitoring for Oracle (Windows).

NOT monitor.py — that is the self-improvement monitor. This module
reads live PC sensors for the Hardware panel in the GUI (Lorenza,
2026-11-24): CPU temp / clock / pump / utilisation, GPU temp /
core + memory clock / fan / utilisation / power, RAM load, network
speed, refreshed about every 2 seconds.

Panel rows (corrected 2026-11-24 21:58 EST — there is NO CPU fan;
the NZXT Kraken Elite 360 AIO cools with a PUMP, wired to the
CPU_FAN/AIO_PUMP header):
  CPU temp, CPU clock, Pump speed, CPU load, GPU temp, GPU core
  clock, GPU mem clock, GPU fan, GPU load, GPU power, RAM load,
  Network down/up.

Sources (her PC: Ryzen 9 9950X3D, RTX 4080 Super, driver 621.40):
  * GPU — ``nvidia-smi`` (already proven working on her PC).
  * CPU clock + utilisation + RAM + network — ``psutil``.
  * CPU temperature — LibreHardwareMonitor (LHM) via its WMI
    namespace ``root\\LibreHardwareMonitor``. LHM reads the same
    CPU sensors NZXT CAM reads, so its number should match CAM's
    display within a degree or two (verified live, side by side,
    by the PC worker). If LHM is not running, this module starts
    a bundled portable copy automatically (see
    ``ensure_lhm_running``) — she never has to start anything by
    hand. Fallback: ``MSAcpi_ThermalZoneTemperature`` (root\\wmi),
    flagged as possibly a chipset sensor, not the CPU.
  * NZXT CAM itself — honest finding (2026-11-24): CAM exposes
    monitoring data ONLY to web integrations, as the JavaScript
    ``window.nzxt.v1.onMonitoringDataUpdate`` callback inside
    CAM's own embedded browser (CAM 4.50.0+, per NZXT's developer
    docs). There is NO documented local HTTP/REST endpoint a
    Python program can poll, and using the web-integration route
    would take over her Kraken LCD display, so Oracle does NOT
    do that. CAM is therefore the VERIFICATION reference (the
    panel number must match CAM's display), not a data source.
    ``cam_running()`` reports whether CAM is up so the worker
    can compare the two displays live.
  * Pump speed + liquid temperature — ``liquidctl`` (``liquidctl
    --json status``; the Kraken 2023 Elite is supported and
    reports Liquid temperature, Pump speed in rpm, Pump duty).
    Fallback: the LHM fan sensor for the pump (name contains
    "pump"/"aio", else the CPU_FAN-header fan — that header
    drives the pump on her rig). Caveat: CAM also talks to the
    Kraken over USB, so liquidctl reads can fail while CAM holds
    the device; the LHM fallback covers that. liquidctl is NOT
    a Python import here — the CLI is called (``pip install
    liquidctl`` on the PC, or a bundled liquidctl.exe on PATH /
    next to Oracle.exe).
  * RAM — psutil.virtual_memory: load % AND used/total, total
    read from the system (64 GB on her PC now — never hardcoded).
  * Network — psutil.net_io_counters(pernic=True): down/up in
    Mbps from the byte delta over the real elapsed time between
    refreshes, on the active adapter (Wi-Fi preferred — she is
    on Wi-Fi, 192.168.1.87). Never a cumulative total shown as
    a speed; first read has no delta yet and shows "—".

If a sensor genuinely cannot be read, its value is None and
``notes`` says which one and why. The GUI shows "—" for it.
NEVER a made-up number.

Stdlib only, except optional psutil. Every function is guarded:
``read_all()`` never raises. Slow sources (PowerShell/WMI,
liquidctl) are cached; nvidia-smi runs every call (fast).
"""

import json
import os
import shutil
import subprocess
import sys
import time

try:
    import psutil as _psutil
except Exception:
    _psutil = None

IS_WINDOWS = sys.platform.startswith("win")

# Cache for the slow WMI / LibreHardwareMonitor reads (PowerShell
# spawn is ~200-500 ms — do not pay it every 2 s refresh).
_CACHE_TTL = 10.0
_cache = {}  # key -> (epoch, value)

# liquidctl status touches USB (~0.5-1 s); cache it a few seconds.
_LIQUIDCTL_TTL = 5.0

# Network state: previous per-adapter counters + timestamp, for
# the delta-based down/up rates.
_net_prev = {"when": None, "counters": None, "adapter": None}

# LibreHardwareMonitor auto-start: only attempted once per process.
_lhm_start_tried = False
_lhm_started_by_us = False


def _now():
    """Monotonic clock (separate function so tests can stub it)."""
    return time.monotonic()


def _cached(key, fn, ttl=_CACHE_TTL):
    now = time.time()
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (now, value)
    return value


def _run(cmd, timeout=8):
    """Run a command, return stdout text or '' on any failure."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
        return proc.stdout or ""
    except Exception:
        return ""


def _num(text):
    """'72' / '72.5' / 'N/A' / '' -> float or None."""
    if text is None:
        return None
    text = str(text).strip()
    if not text or text.upper() in ("N/A", "N\\A", "-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ------------------------------------------------------------ GPU: nvidia-smi

def read_gpu():
    """One GPU's live readings via nvidia-smi, or all-None + note
    when nvidia-smi is missing / fails / has no GPU."""
    out = {"gpu_name": None, "gpu_temp_c": None, "gpu_clock_mhz": None,
           "gpu_mem_clock_mhz": None, "gpu_fan_pct": None,
           "gpu_util_pct": None, "gpu_power_w": None, "gpu_note": None}
    raw = _run(["nvidia-smi",
                "--query-gpu=name,temperature.gpu,clocks.sm,clocks.mem,"
                "fan.speed,utilization.gpu,power.draw",
                "--format=csv,noheader,nounits"], timeout=8)
    if not raw.strip():
        out["gpu_note"] = "nvidia-smi not found or no NVIDIA GPU"
        return out
    fields = [f.strip() for f in raw.strip().splitlines()[0].split(",")]
    if len(fields) < 7:
        out["gpu_note"] = "nvidia-smi output not understood"
        return out
    out["gpu_name"] = fields[0] or None
    out["gpu_temp_c"] = _num(fields[1])
    out["gpu_clock_mhz"] = _num(fields[2])
    out["gpu_mem_clock_mhz"] = _num(fields[3])
    out["gpu_fan_pct"] = _num(fields[4])
    out["gpu_util_pct"] = _num(fields[5])
    out["gpu_power_w"] = _num(fields[6])
    if out["gpu_temp_c"] is None and out["gpu_util_pct"] is None:
        out["gpu_note"] = "nvidia-smi ran but returned no readings"
    return out


# ------------------------------------------------------------ CPU: psutil / WMI

def _cpu_psutil():
    if _psutil is None:
        return None
    try:
        freq = _psutil.cpu_freq()
        return {"cpu_clock_mhz": (float(freq.current) if freq else None),
                "cpu_util_pct": float(_psutil.cpu_percent(interval=None))}
    except Exception:
        return None


def _cpu_wmi():
    """Win32_Processor via PowerShell (cached): current clock and
    load %. Used only when psutil is not installed."""
    if not IS_WINDOWS:
        return None
    raw = _run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Processor | Select-Object -First 1 "
                "CurrentClockSpeed,LoadPercentage | ConvertTo-Json"],
               timeout=10)
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, list):
        data = data[0] if data else {}
    return {"cpu_clock_mhz": _num(data.get("CurrentClockSpeed")),
            "cpu_util_pct": _num(data.get("LoadPercentage"))}


def read_cpu_load():
    """CPU clock + utilisation. psutil first, WMI fallback."""
    result = _cpu_psutil()
    if result is not None:
        return result
    return _cached("cpu_wmi", _cpu_wmi) or {
        "cpu_clock_mhz": None, "cpu_util_pct": None}


# ------------------------------------------------------------ RAM: psutil

def read_ram():
    """RAM load % + used/total GB. Total comes from the system
    (64 GB on her PC now) — never hardcoded."""
    out = {"ram_util_pct": None, "ram_used_gb": None, "ram_total_gb": None}
    if _psutil is None:
        return out
    try:
        vm = _psutil.virtual_memory()
        out["ram_util_pct"] = float(vm.percent)
        out["ram_used_gb"] = float(vm.used) / (1024 ** 3)
        out["ram_total_gb"] = float(vm.total) / (1024 ** 3)
    except Exception:
        pass
    return out


# ------------------------------------------------------------ Network: psutil

def _pick_adapter(counters):
    """Active adapter: prefer Wi-Fi/Wireless/WLAN, else the
    non-loopback adapter with the most traffic. Returns the
    adapter name or None."""
    if not counters:
        return None
    names = list(counters.keys())
    for want in ("wi-fi", "wifi", "wireless", "wlan"):
        for name in names:
            if want in name.lower():
                return name
    best, best_bytes = None, -1
    for name, c in counters.items():
        low = name.lower()
        if "loopback" in low or low.startswith("lo"):
            continue
        total = (getattr(c, "bytes_sent", 0) or 0) + \
            (getattr(c, "bytes_recv", 0) or 0)
        if total > best_bytes:
            best, best_bytes = name, total
    return best


def read_network():
    """Live down/up speed in Mbps on the active adapter, from the
    byte-counter delta over the real elapsed time since the last
    read. First read has no previous sample: rates are None
    (panel shows "—" for one tick, then real numbers). A counter
    reset also yields None, never a negative or wild rate."""
    out = {"net_down_mbps": None, "net_up_mbps": None, "net_adapter": None}
    if _psutil is None:
        return out
    try:
        counters = _psutil.net_io_counters(pernic=True)
    except Exception:
        return out
    if not counters:
        return out
    adapter = _pick_adapter(counters)
    if adapter is None or adapter not in counters:
        return out
    now = _now()
    cur = counters[adapter]
    prev = _net_prev
    out["net_adapter"] = adapter
    if prev["when"] is not None and prev["counters"] is not None \
            and prev["adapter"] == adapter:
        elapsed = now - prev["when"]
        old = prev["counters"]
        d_recv = (getattr(cur, "bytes_recv", 0) or 0) - \
            (getattr(old, "bytes_recv", 0) or 0)
        d_sent = (getattr(cur, "bytes_sent", 0) or 0) - \
            (getattr(old, "bytes_sent", 0) or 0)
        if elapsed > 0 and d_recv >= 0 and d_sent >= 0:
            out["net_down_mbps"] = d_recv * 8.0 / 1e6 / elapsed
            out["net_up_mbps"] = d_sent * 8.0 / 1e6 / elapsed
    _net_prev["when"] = now
    _net_prev["counters"] = cur
    _net_prev["adapter"] = adapter
    return out


# ------------------------------------------------------------ NZXT CAM: status only

def cam_running():
    """True when NZXT CAM is running (NZXT CAM.exe process).
    CAM is the verification reference for the CPU temperature —
    its display is what the panel number must match — not a data
    source (see the module docstring: CAM exposes monitoring data
    only to web integrations inside its own browser). Cached
    30 s; tasklist is cheap but there is no need to run it
    every 2 s."""
    if not IS_WINDOWS:
        return False

    def _check():
        out = _run(["tasklist", "/FI", "IMAGENAME eq NZXT CAM.exe",
                    "/NH"], timeout=8)
        return "NZXT CAM.exe" in out
    return _cached("cam_running", _check, ttl=30.0)


# ------------------------------------------------- LibreHardwareMonitor

def _lhm_raw():
    """All LHM Temperature + Fan sensors via WMI, or None when
    LHM is not running / the namespace is absent."""
    if not IS_WINDOWS:
        return None
    raw = _run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance -Namespace root\\LibreHardwareMonitor "
                "-ClassName Sensor | Where-Object { $_.SensorType -eq "
                "'Temperature' -or $_.SensorType -eq 'Fan' } | "
                "Select-Object Name,SensorType,Value,Parent | ConvertTo-Json"],
               timeout=10)
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict):
        data = [data]
    return data if isinstance(data, list) else None


def _lhm_exe_candidates():
    """Where a bundled portable LibreHardwareMonitor.exe may live:
    next to this module (source tree / install folder), next to
    the frozen exe, or LIBREHARDWAREMONITOR_EXE. LHM is free
    (MPL-2.0) and portable — bundling it with its licence is
    allowed; it is NOT in the repo by default, the build step
    drops the portable zip's exe here."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "LibreHardwareMonitor",
                          "LibreHardwareMonitor.exe"),
             os.path.join(here, "LibreHardwareMonitor.exe")]
    try:
        cands.append(os.path.join(
            os.path.dirname(os.path.abspath(sys.executable)),
            "LibreHardwareMonitor", "LibreHardwareMonitor.exe"))
    except Exception:
        pass
    env = os.environ.get("LIBREHARDWAREMONITOR_EXE")
    if env:
        cands.insert(0, env)
    return cands


def ensure_lhm_running():
    """Make sure LibreHardwareMonitor is running so its WMI
    sensors are readable. Returns (running, started_by_us, note).
    If the namespace is already there, nothing is started. If
    it is absent and a bundled portable exe exists, start it
    hidden/minimised and wait up to ~8 s for the namespace to
    appear. Only attempted once per process. Never raises."""
    global _lhm_start_tried, _lhm_started_by_us
    if _lhm_raw() is not None:
        return True, _lhm_started_by_us, ""
    if _lhm_start_tried:
        return False, False, ("LibreHardwareMonitor is not running — "
                              "automatic start was already attempted")
    _lhm_start_tried = True
    exe = next((p for p in _lhm_exe_candidates()
                if p and os.path.isfile(p)), None)
    if exe is None:
        return False, False, ("LibreHardwareMonitor is not running and "
                              "no bundled copy was found next to Oracle — "
                              "drop the portable LibreHardwareMonitor.exe "
                              "beside Oracle.exe to auto-start it")
    try:
        kwargs = {}
        if IS_WINDOWS:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 6  # SW_MINIMIZE
            kwargs["startupinfo"] = si
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([exe], **kwargs)
        _lhm_started_by_us = True
    except Exception as exc:
        return False, False, f"Could not start LibreHardwareMonitor: {exc}"
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if _lhm_raw() is not None:
            return True, True, ""
        time.sleep(0.5)
    return False, True, ("LibreHardwareMonitor was started but its "
                         "sensors are not readable yet")


def _lhm_sensors():
    """(cpu_temp_c, pump_rpm, note) from LibreHardwareMonitor.
    CPU temp prefers the "CPU Package" sensor (Ryzen). Pump speed
    is the fan sensor named pump/AIO, else the CPU_FAN-header fan
    — on her rig that header drives the Kraken pump, not a fan.
    Returns (None, None, note) when LHM is not running."""
    data = _cached("lhm", _lhm_raw)
    if data is None:
        return None, None, ("LibreHardwareMonitor is not running — "
                            "CPU temperature unavailable")
    temps = [s for s in data if s.get("SensorType") == "Temperature"]
    fans = [s for s in data if s.get("SensorType") == "Fan"]
    temp = None
    for cand in temps:
        name = str(cand.get("Name", ""))
        parent = str(cand.get("Parent", ""))
        if name == "CPU Package" or "Ryzen" in parent or "CPU" in parent:
            temp = _num(cand.get("Value"))
            if temp is not None:
                break
    if temp is None and temps:
        temp = _num(temps[0].get("Value"))
    pump = None
    for cand in fans:
        name = str(cand.get("Name", "")).lower()
        if "pump" in name or "aio" in name:
            pump = _num(cand.get("Value"))
            if pump is not None:
                break
    if pump is None:
        for cand in fans:
            if "cpu" in str(cand.get("Name", "")).lower():
                pump = _num(cand.get("Value"))
                if pump is not None:
                    break
    missing = []
    if temp is None:
        missing.append("CPU temperature")
    if pump is None:
        missing.append("pump speed")
    note = ("LibreHardwareMonitor running but no "
            + " / ".join(missing) + " sensor found") if missing else ""
    return temp, pump, note


def _thermal_zone_temp():
    """MSAcpi_ThermalZoneTemperature fallback (root\\wmi). Often
    absent on desktops; when present it may be a chipset sensor,
    not the CPU — callers must flag that."""
    if not IS_WINDOWS:
        return None
    raw = _run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance -Namespace root\\wmi -ClassName "
                "MSAcpi_ThermalZoneTemperature | Select-Object -First 1 "
                "CurrentTemperature | ConvertTo-Json"], timeout=10)
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, list):
        data = data[0] if data else {}
    kelvin_tenths = _num(data.get("CurrentTemperature"))
    if kelvin_tenths is None:
        return None
    return kelvin_tenths / 10.0 - 273.15


# ------------------------------------------------------------ Kraken: liquidctl

def _liquidctl_cmd():
    """How to run liquidctl: a liquidctl.exe on PATH / next to
    Oracle.exe, else `python -m liquidctl` when the package is
    installed. Returns an argv prefix list or None."""
    exe = shutil.which("liquidctl")
    if exe:
        return [exe]
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "liquidctl.exe")
    if os.path.isfile(local):
        return [local]
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        local2 = os.path.join(exe_dir, "liquidctl.exe")
        if os.path.isfile(local2):
            return [local2]
    except Exception:
        pass
    try:
        import liquidctl as _lc  # noqa: F401  (presence check only)
        return [sys.executable, "-m", "liquidctl"]
    except Exception:
        return None


def read_kraken():
    """Kraken Elite 360 via liquidctl: (pump_rpm, liquid_temp_c,
    note). ``liquidctl --json status`` reports Liquid temperature
    and Pump speed in rpm. Cached ~5 s (USB init is slow).
    Note: NZXT CAM also talks to the Kraken over USB, so this
    can fail while CAM holds the device — the LHM fan sensor is
    the fallback for pump speed. Never raises."""
    cmd = _liquidctl_cmd()
    if cmd is None:
        return None, None, ("liquidctl not found — install it "
                            "(`pip install liquidctl`) or put "
                            "liquidctl.exe next to Oracle.exe for "
                            "pump speed / liquid temperature")

    def _fetch():
        raw = _run(cmd + ["--json", "status"], timeout=10)
        if not raw.strip():
            return None, None, ("liquidctl ran but returned nothing — "
                                "it may be blocked while NZXT CAM holds "
                                "the Kraken USB device")
        try:
            devices = json.loads(raw)
        except Exception:
            return None, None, "liquidctl output not understood"
        if isinstance(devices, dict):
            devices = [devices]
        kraken = None
        for dev in devices:
            if "kraken" in str(dev.get("description", "")).lower():
                kraken = dev
                break
        if kraken is None:
            return None, None, "liquidctl found no Kraken device"
        pump, liquid = None, None
        for item in kraken.get("status", []):
            key = str(item.get("key", ""))
            if key == "Pump speed":
                pump = _num(item.get("value"))
            elif key == "Liquid temperature":
                liquid = _num(item.get("value"))
        if pump is None and liquid is None:
            return None, None, ("liquidctl found the Kraken but no "
                                "pump / liquid-temperature reading")
        return pump, liquid, ""
    return _cached("kraken", _fetch, ttl=_LIQUIDCTL_TTL)


def read_cpu_temp_pump():
    """(temp_c, pump_rpm, liquid_temp_c, temp_source, note).
    CPU temp: LHM first (auto-starting it if needed), thermal-zone
    fallback flagged. Pump: liquidctl first, LHM fan sensor
    second. temp_source names the source that supplied the CPU
    temperature, so the panel note can say where it came from."""
    lhm_running, _started, lhm_note = ensure_lhm_running()
    temp, pump, note = (None, None, "")
    if lhm_running:
        temp, pump, note = _lhm_sensors()
        source = "LibreHardwareMonitor" if temp is not None else None
    else:
        source = None
        note = lhm_note
    kraken_pump, liquid, kraken_note = read_kraken()
    if kraken_pump is not None:
        pump = kraken_pump
    if temp is None:
        zone = _cached("thermal_zone", _thermal_zone_temp)
        if zone is not None:
            temp = zone
            source = "thermal zone (may be chipset, not CPU)"
            note = ("CPU temperature is a thermal-zone reading — "
                    "it may be the chipset, not the CPU")
    if temp is None and not note:
        note = "CPU temperature: no sensor source available"
    if pump is None and kraken_note and "not found" not in kraken_note:
        note = (note + " | " if note else "") + "Pump: " + kraken_note
    return temp, pump, liquid, source, note


# ------------------------------------------------------------ all together

def read_all():
    """Full Hardware-panel snapshot. Never raises; unavailable
    sensors are None with an explanation in ``notes``."""
    notes = []
    try:
        gpu = read_gpu()
    except Exception:
        gpu = {"gpu_name": None, "gpu_temp_c": None, "gpu_clock_mhz": None,
               "gpu_mem_clock_mhz": None, "gpu_fan_pct": None,
               "gpu_util_pct": None, "gpu_power_w": None,
               "gpu_note": "GPU read failed"}
    if gpu.get("gpu_note"):
        notes.append("GPU: " + gpu["gpu_note"])
    try:
        cpu_load = read_cpu_load()
    except Exception:
        cpu_load = {"cpu_clock_mhz": None, "cpu_util_pct": None}
    try:
        cpu_temp, pump, liquid, temp_source, cpu_note = read_cpu_temp_pump()
    except Exception:
        cpu_temp, pump, liquid, temp_source, cpu_note = (
            None, None, None, None, "CPU temp/pump read failed")
    if cpu_note:
        notes.append(cpu_note)
    if temp_source:
        notes.append("CPU temp source: " + temp_source)
    try:
        ram = read_ram()
    except Exception:
        ram = {"ram_util_pct": None, "ram_used_gb": None,
               "ram_total_gb": None}
    try:
        net = read_network()
    except Exception:
        net = {"net_down_mbps": None, "net_up_mbps": None,
               "net_adapter": None}
    if net.get("net_adapter"):
        notes.append("Network: " + str(net["net_adapter"]))
    return {
        "cpu_temp_c": cpu_temp,
        "cpu_clock_mhz": cpu_load.get("cpu_clock_mhz"),
        "pump_speed_rpm": pump,
        "liquid_temp_c": liquid,
        "cpu_util_pct": cpu_load.get("cpu_util_pct"),
        "gpu_name": gpu.get("gpu_name"),
        "gpu_temp_c": gpu.get("gpu_temp_c"),
        "gpu_clock_mhz": gpu.get("gpu_clock_mhz"),
        "gpu_mem_clock_mhz": gpu.get("gpu_mem_clock_mhz"),
        "gpu_fan_pct": gpu.get("gpu_fan_pct"),
        "gpu_util_pct": gpu.get("gpu_util_pct"),
        "gpu_power_w": gpu.get("gpu_power_w"),
        "ram_util_pct": ram.get("ram_util_pct"),
        "ram_used_gb": ram.get("ram_used_gb"),
        "ram_total_gb": ram.get("ram_total_gb"),
        "net_down_mbps": net.get("net_down_mbps"),
        "net_up_mbps": net.get("net_up_mbps"),
        "net_adapter": net.get("net_adapter"),
        "notes": notes,
    }


def format_value(value, unit, decimals=0):
    """'—' for an unavailable sensor, otherwise '72 °C' style."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f} {unit}"
    except Exception:
        return "—"


def format_pump(result):
    """Pump row: '1357 RPM' plus the liquid temperature when
    liquidctl supplied it ('1357 RPM · liquid 32.2 °C')."""
    pump = result.get("pump_speed_rpm")
    if pump is None:
        return "—"
    text = format_value(pump, "RPM")
    liquid = result.get("liquid_temp_c")
    if liquid is not None:
        text += f" · liquid {float(liquid):.1f} °C"
    return text


def format_ram(result):
    """RAM row: '38% — 24.3 / 64 GB' (total from the system)."""
    pct = result.get("ram_util_pct")
    used = result.get("ram_used_gb")
    total = result.get("ram_total_gb")
    if pct is None:
        return "—"
    if used is None or total is None:
        return format_value(pct, "%")
    return f"{float(pct):.0f}% — {float(used):.1f} / {float(total):.0f} GB"


def format_net(result):
    """Network row: '↓ 12.4 ↑ 3.1 Mbps' (down then up)."""
    down = result.get("net_down_mbps")
    up = result.get("net_up_mbps")
    if down is None or up is None:
        return "—"
    return f"↓ {float(down):.1f} ↑ {float(up):.1f} Mbps"
