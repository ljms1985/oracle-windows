"""Frozen (PyInstaller) path helpers for Oracle on Windows.

When Oracle runs from source, everything lives next to the .py files.
When it runs as a frozen Oracle.exe (onefile), two different folders
matter and they must NOT be confused:

* ``sys._MEIPASS`` — the temp folder PyInstaller extracts the bundle
  into at startup. It holds READ-ONLY bundled resources (avatar,
  docs, Tcl/Tk data). It is deleted when the app exits, so nothing
  written there survives — and on some runs it is not even writable.
* The folder next to Oracle.exe — the WRITABLE home for memory.json,
  workspace/, credentials/, prints/, alerts/, etc. That is where
  user data must live, so it persists between launches.

Before this module existed every .py file did
``BASE_DIR = Path(__file__).resolve().parent``, which in a onefile
build points at the temp _MEIPASS folder — so writes vanished, and
bundled resources could resolve wrong.

``fix_tcl()`` must run BEFORE ``import tkinter``: it points
TCL_LIBRARY / TK_LIBRARY at the bundled Tcl/Tk data inside _MEIPASS
so ``tk.Tk()`` can find init.tcl. PyInstaller's own tkinter runtime
hook is supposed to do this, but v1.0.0 crashed on a real PC with
"can't find a usable init.tcl", so Oracle now sets the variables
itself, belt and braces, in both the runtime hook (rth_tcl.py) and
gui.py before the tkinter import.
"""

import json
import os
import sys
from pathlib import Path


def is_frozen():
    """True when running as a frozen PyInstaller .exe."""
    return bool(getattr(sys, "frozen", False))


def _meipass():
    """The PyInstaller temp extraction folder, or None when unfrozen."""
    if not is_frozen():
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def exe_dir():
    """Folder containing Oracle.exe (frozen) or this file (source)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(rel):
    """Path to a bundled read-only resource (avatar, docs, prints samples).

    Frozen: inside _MEIPASS. Source: next to this file.
    """
    meipass = _meipass()
    if meipass is not None:
        return meipass / rel
    return Path(__file__).resolve().parent / rel


# ------------------------------------------------------------ data drive
# Dedicated Oracle data drive (2026-11-24, Lorenza): she wants the
# program's memory on its own drive if there is room — there is
# (MSI MPG X670E Carbon WiFi: 4x M.2, only 1 NVMe fitted, 3 free;
# suggested 1TB Gen4 NVMe, NTFS, its own letter — far more than
# memory will ever need; nothing is bought without her approval).
# When set, memory.json, memory_import/, alerts/, logs, face
# profiles and get-to-know-you profiles live on that drive instead
# of next to Oracle.exe. Default (nothing set) stays next to the
# exe, so existing installs do not break.
SETTINGS_FILE_NAME = "oracle_settings.json"


def settings_path():
    """oracle_settings.json always lives next to the exe — it holds
    the data-drive choice itself, so it can never live ON the data
    drive (chicken-and-egg)."""
    return exe_dir() / SETTINGS_FILE_NAME


def _valid_data_dir(path):
    """A usable data dir: an existing directory, or one we can
    create. Returns the Path, or None (never raises)."""
    if not path:
        return None
    try:
        p = Path(str(path)).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        if p.is_dir():
            return p
    except Exception:
        return None
    return None


def data_dir():
    """Writable home for user data, honouring the dedicated drive.

    Priority: ORACLE_DATA_DIR env var, then the data_dir saved in
    oracle_settings.json (set from the GUI), then next to the exe.
    A set-but-unusable path falls back silently to the exe folder
    — Oracle must never fail to start over a bad drive letter.
    """
    env = _valid_data_dir(os.environ.get("ORACLE_DATA_DIR"))
    if env is not None:
        return env
    try:
        settings = json.loads(settings_path().read_text(encoding="utf-8"))
        saved = _valid_data_dir(settings.get("data_dir"))
        if saved is not None:
            return saved
    except Exception:
        pass
    return exe_dir()


def set_data_dir(path):
    """Point Oracle at a dedicated data drive and persist the choice
    in oracle_settings.json next to the exe. Returns the Path used.
    Raises ValueError when the path cannot be created/used. Takes
    effect on the next Oracle restart (APP_DIR is fixed at import).
    """
    valid = _valid_data_dir(path)
    if valid is None:
        raise ValueError(f"Cannot use {path!r} as the Oracle data drive.")
    try:
        settings = _read_settings()
        settings["data_dir"] = str(valid)
        _write_settings(settings)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not save the data-drive setting: {e}")
    return valid


# ------------------------------------------------------------ generic settings
# Small user preferences that live in the same oracle_settings.json
# next to the exe (voice engine, ElevenLabs voice id, the spare-key
# label). Never credentials: keys live in User env vars (Windows)
# or the Keychain (Mac), never in this file.

def _read_settings():
    """The settings dict, or {} when the file is missing/broken."""
    try:
        settings = json.loads(settings_path().read_text(encoding="utf-8"))
        if isinstance(settings, dict):
            return settings
    except Exception:
        pass
    return {}


def _write_settings(settings):
    settings_path().write_text(
        json.dumps(settings, indent=2), encoding="utf-8")


def get_setting(key, default=None):
    """One preference from oracle_settings.json (default when absent)."""
    return _read_settings().get(key, default)


def set_setting(key, value):
    """Persist one preference in oracle_settings.json. Returns value."""
    settings = _read_settings()
    settings[key] = value
    _write_settings(settings)
    return value


def app_dir():
    """Writable home for user data (memory, workspace, credentials, ...).

    Frozen: next to Oracle.exe, so data persists — unless a
    dedicated data drive is set (see data_dir()), in which case
    user data lives there. Source: next to the .py files, as
    before, unless a data drive is set.
    """
    return data_dir()


def _find_tcl_dir(meipass, names, filename):
    """First directory under _MEIPASS that contains ``filename``.

    ``filename`` matters: Tcl's library dir holds init.tcl, Tk's
    holds tk.tcl, and they are SEPARATE folders in PyInstaller 6
    one-dir builds (_internal/_tcl_data/ vs _internal/_tk_data/).
    Searching for init.tcl when looking for Tk returned _tcl_data
    as the Tk dir and set TK_LIBRARY to a folder with no tk.tcl —
    that is exactly the v1.0.4 smoke-test failure ("Can't find a
    usable tk.tcl", searched _tcl_data, _tcl_data/tk8.6, tk8.6...).

    Versioned folders first (tcl8.6/tk8.6), then the flat data
    roots themselves: if PyInstaller laid the data out flat, the
    root IS the library dir. In a one-dir build PyInstaller's own
    tkinter hook already sets the variables, so this is
    belt-and-braces only — but it must never point a variable at
    the wrong library's folder.
    """
    candidates = []
    for name in names:
        candidates.append(meipass / name)
        # PyInstaller 6 collects Tcl as _tcl_data/tcl8.6/..., so also
        # look one level down inside _tcl_data / _tk_data.
        for parent in ("_tcl_data", "_tk_data", "tcl", "tk"):
            candidates.append(meipass / parent / name)
    # Flat layout fallback: the data root itself holds the file.
    for parent in ("_tcl_data", "_tk_data", "tcl", "tk"):
        candidates.append(meipass / parent)
    for cand in candidates:
        try:
            if (cand / filename).is_file():
                return cand
        except Exception:
            pass
    return None


def fix_tcl():
    """Point TCL_LIBRARY / TK_LIBRARY at the bundled Tcl/Tk data.

    Safe to call when unfrozen (does nothing) and safe to call twice.
    Returns True when both libraries were located.

    v1.0.5: versioned folders first, then the flat data roots —
    PyInstaller 6.22.3 one-dir puts Tcl flat in
    _internal/_tcl_data/ (init.tcl) and Tk flat in
    _internal/_tk_data/ (tk.tcl). Each variable must point at its
    OWN library's folder: TCL_LIBRARY at the folder holding
    init.tcl, TK_LIBRARY at the folder holding tk.tcl. Pointing
    TK_LIBRARY at _tcl_data was the v1.0.4 smoke-test failure.
    If no folder is found for a library, that variable is left
    alone — PyInstaller's own tkinter hook sets them correctly
    for a one-dir build.
    """
    meipass = _meipass()
    if meipass is None:
        return False
    tcl_dir = _find_tcl_dir(meipass, ("tcl8.6", "tcl8.7", "tcl"), "init.tcl")
    tk_dir = _find_tcl_dir(meipass, ("tk8.6", "tk8.7", "tk"), "tk.tcl")
    if tcl_dir is not None:
        os.environ["TCL_LIBRARY"] = str(tcl_dir)
    if tk_dir is not None:
        os.environ["TK_LIBRARY"] = str(tk_dir)
    return tcl_dir is not None and tk_dir is not None
