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


def app_dir():
    """Writable home for user data (memory, workspace, credentials, ...).

    Frozen: next to Oracle.exe, so data persists. Source: next to the
    .py files, as before.
    """
    return exe_dir()


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
