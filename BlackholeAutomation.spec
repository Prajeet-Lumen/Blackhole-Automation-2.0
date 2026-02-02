# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Blackhole Automation .exe packaging.

Usage:
  pyinstaller BlackholeAutomation.spec

This creates a standalone Windows .exe with all dependencies bundled.
The .exe can be distributed to coworkers without requiring Python or venv installation.

Output:
  - dist/BlackholeAutomation.exe (main executable)
  - dist/BlackholeAutomation/ (folder with all dependencies and data files)
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect Playwright and pyee data files (browsers, libraries, etc.)
playwright_datas = collect_data_files('playwright')
pyee_datas = collect_data_files('pyee')
all_datas = playwright_datas + pyee_datas

# Collect all submodules for these packages to ensure complete bundling
playwright_hiddens = collect_submodules('playwright')
pyee_hiddens = collect_submodules('pyee')

a = Analysis(
    ['main_entry.py'],
    pathex=[],
    binaries=[],
    datas=all_datas + [('README.md', '.')],  # Bundle README.md for Help menu
    hiddenimports=[
        'AuthManager',
        'RetrievalEngine',
        'CreateBlackhole',
        'BatchRemoval',
        'SessionLogger',
        'PlayWrightUtil',
        'BlackholeGUI',
    ] + playwright_hiddens + pyee_hiddens,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
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
    name='BlackholeAutomation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to False for GUI-only (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',  # Optional: replace with path to your icon file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BlackholeAutomation',
)
