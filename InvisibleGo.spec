# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the desktop app.
#
# Build (Windows):  pyinstaller InvisibleGo.spec
# Build (macOS/Linux): same command on the target OS.
#
# Excludes web-only deps (fastapi, uvicorn, websockets) and test deps so the
# bundled binary stays lean — the desktop app never imports them.

from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("frontend.desktop")

a = Analysis(
    ["desktop_main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    excludes=[
        "fastapi",
        "uvicorn",
        "starlette",
        "websockets",
        "httptools",
        "watchfiles",
        "pytest",
        "pytest_asyncio",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="InvisibleGo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
