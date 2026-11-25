# PyInstaller spec for Oracle for Windows — builds a standalone Oracle.exe.
#
# Build ON WINDOWS ONLY (a Windows .exe cannot be built on macOS or Linux):
#   pip install pyinstaller
#   pyinstaller oracle-windows.spec
# Output: dist/Oracle-debug/Oracle-debug.exe  (double-click to run; no Python install
# needed). The whole dist/Oracle-debug folder is the install — copy the folder,
# run Oracle.exe inside it. Do NOT move Oracle.exe out of its folder:
# the Tcl/Tk data and DLLs live next to it.
#
# This spec is built by GitHub Actions on a real Windows runner
# (see .github/workflows/build-windows.yml).
# No OpenAI API key, password, or credential is bundled: the user adds
# her own OPENAI_API_KEY on first run (the GUI says so if it is missing).
#
# v1.0.2 — ONE-DIR build (was one-file in v1.0.0 / v1.0.1).
# Why: both one-file builds crashed on Lorenza's real PC with
# "_tkinter.TclError: Can't find a usable init.tcl", even though the
# extracted _tcl_data/init.tcl was present, readable, and had the
# correct header. The one-file bootloader extracts the bundle into a
# temp _MEI folder — on her PC that was C:\WINDOWS\TEMP\_MEI... —
# and tkinter reported the extracted init.tcl as "not usable".
# The v1.0.1 fix_tcl() (re-pointing TCL_LIBRARY at the same extracted
# data) could not fix that, because the extracted data was the problem.
# A one-dir build extracts nothing at runtime: Tcl/Tk data sits in
# real folders next to Oracle.exe (_tcl_data/tcl8.6/, _tk_data/tk8.6/),
# exactly as PyInstaller's official tkinter hook lays them out, and
# tkinter finds init.tcl through its normal search. This also removes
# the v1.0.1 duplicate: the spec no longer flattens a second copy of
# tcl8.6 directly into _tcl_data (Tree tcl8.6 -> _tcl_data), which
# created a top-level _tcl_data/init.tcl alongside
# _tcl_data/tcl8.6/init.tcl and gave fix_tcl()/the runtime hook an
# ambiguous, flattened root to point TCL_LIBRARY at.
# The spec therefore now relies ONLY on collect_all("tkinter") for
# Tcl/Tk, drops the rth_tcl.py runtime hook, and oracle_paths.fix_tcl()
# will only ever point at a versioned tcl8.6/tk8.6 folder, never at
# the _tcl_data/_tk_data root itself.
# UPX stays off: UPX-compressed binaries are a known source of
# extraction / antivirus trouble on real PCs.

# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# --- Tcl/Tk: PyInstaller's own tkinter collection ONLY ----------------
# No manual Tree copy, no flattened second copy of tcl8.6/tk8.6.
_tk_datas, _tk_binaries, _tk_hidden = collect_all("tkinter")

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
    ] + _tk_datas,
    hiddenimports=[
        'agent', 'computer', 'voice', 'camera', 'monitor',
        'email_alerts', 'identity', 'repair', 'design3d', 'security',
        'sms', 'oracle_paths',
        # Camera auto-tracking + local face recognition (v1.0.8,
        # items 7/9): tracking.py / face_profiles.py. Face profiles
        # themselves (faces/) are runtime data next to Oracle.exe,
        # never bundled — they are local-only and gitignored.
        'tracking', 'face_profiles',
        'PIL', 'PIL.Image', 'PIL.ImageTk',
        'openai', 'numpy', 'trimesh',
    ] + _tk_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['face_recognition'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-dir: EXE excludes binaries/datas here; COLLECT puts them in
# dist/Oracle-debug/ next to Oracle-debug.exe.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Oracle-debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Oracle-debug',
)
