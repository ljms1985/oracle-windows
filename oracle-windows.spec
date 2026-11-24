# PyInstaller spec for Oracle for Windows — builds a standalone Oracle.exe.
#
# Build ON WINDOWS ONLY (a Windows .exe cannot be built on macOS or Linux):
#   pip install pyinstaller
#   pyinstaller oracle-windows.spec
# Output: dist/Oracle.exe  (double-click to run; no Python install needed)
#
# This spec was built by GitHub Actions on a real Windows runner
# (see .github/workflows/build-windows.yml). It is a single-file,
# windowed (no console) build of gui.py — the Gideon-style GUI.
# No OpenAI API key, password, or credential is bundled: the user adds
# her own OPENAI_API_KEY on first run (the GUI says so if it is missing).
# tkinter is bundled by PyInstaller automatically on Windows; the data
# files below are the docs the GUI/setup text refers to.

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
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
    ],
    hiddenimports=[
        'agent', 'computer', 'voice', 'camera', 'monitor',
        'email_alerts', 'identity', 'repair', 'design3d', 'security',
        'sms',
        'PIL', 'PIL.Image', 'PIL.ImageTk',
        'openai', 'numpy', 'trimesh',
    ],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
