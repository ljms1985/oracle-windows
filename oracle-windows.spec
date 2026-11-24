# PyInstaller spec for Oracle for Windows — builds a standalone Oracle.exe.
#
# Build ON WINDOWS ONLY (a Windows .exe cannot be built on macOS or Linux):
#   pip install pyinstaller
#   pyinstaller oracle-windows.spec
# Output: dist/Oracle.exe  (double-click to run; no Python install needed)
#
# This spec is built by GitHub Actions on a real Windows runner
# (see .github/workflows/build-windows.yml). It is a single-file,
# windowed (no console) build of gui.py — the Gideon-style GUI.
# No OpenAI API key, password, or credential is bundled: the user adds
# her own OPENAI_API_KEY on first run (the GUI says so if it is missing).
#
# v1.0.1 — Tcl/Tk fix (see oracle_paths.py / rth_tcl.py):
# v1.0.0 crashed on Lorenza's real PC with "Failed to execute script
# 'gui'" and "can't find a usable init.tcl". The same build PASSED the
# tkinter smoke test on the GitHub Windows runner, and _tcl_data /
# _tk_data WERE in the bundle — so the PC failure was not "no Tcl data
# in the exe". The most likely cause is a TCL_LIBRARY / TK_LIBRARY
# environment variable on that PC pointing tkinter at a broken Python
# install, overriding PyInstaller's own hook. This spec therefore:
#   * collects ALL of tkinter explicitly (collect_all) instead of
#     relying only on the hook,
#   * ALSO bundles the Tcl/Tk library folders directly from the build
#     Python (Tree: tcl8.6 -> _tcl_data, tk8.6 -> _tk_data),
#   * runs rth_tcl.py before gui.py, which sets TCL_LIBRARY /
#     TK_LIBRARY to the bundled data, and gui.py calls
#     oracle_paths.fix_tcl() before importing tkinter as a second layer.
# UPX is off in v1.0.1: UPX-compressed binaries are a known source of
# extraction / antivirus trouble on real PCs, and removing that
# variable costs only a few MB.

# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# --- Tcl/Tk: collect everything, twice over ---------------------------
# (1) PyInstaller's own tkinter collection.
_tk_datas, _tk_binaries, _tk_hidden = collect_all("tkinter")

# (2) Direct copy of the Tcl/Tk library folders from the build Python,
# so init.tcl is present even if the hook collection ever changes.
# Layout matches the hook's: tcl8.6/* -> _tcl_data/*, tk8.6/* -> _tk_data/*.
_tcl_extra_datas = []
for _lib, _dest in (("tcl8.6", "_tcl_data"), ("tk8.6", "_tk_data")):
    _src = os.path.join(sys.base_prefix, "tcl", _lib)
    if os.path.isdir(_src):
        _tcl_extra_datas.append((_src, _dest))

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=_tk_binaries,
    datas=[
        ('README.md', '.'),
        ('SETUP_GUIDE.md', '.'),
        ('ORACLE_SETUP_DETAILED.md', '.'),
        ('3D_KNOWLEDGE.md', '.'),
        ('SECURITY_KNOWLEDGE.md', '.'),
        ('AVATAR_NOTES.md', '.'),
        ('WINDOWS_UPDATE_NOTES.md', '.'),
        # Lorenza's chosen Muse avatar (red-and-black anime). gui.py
        # loads assets/avatar.png, falling back to avatar.png — both
        # are bundled so the face shows in the frozen .exe.
        ('assets/avatar.png', 'assets'),
        ('avatar.png', '.'),
        # Sample STL prints (design3d.py writes new ones to prints/).
        ('prints', 'prints'),
    ] + _tk_datas + _tcl_extra_datas,
    hiddenimports=[
        'agent', 'computer', 'voice', 'camera', 'monitor',
        'email_alerts', 'identity', 'repair', 'design3d', 'security',
        'sms', 'oracle_paths',
        'PIL', 'PIL.Image', 'PIL.ImageTk',
        'openai', 'numpy', 'trimesh',
    ] + _tk_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rth_tcl.py'],
    excludes=['face_recognition'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Oracle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
