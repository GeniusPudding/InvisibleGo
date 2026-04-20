"""PyInstaller entry point.

PyInstaller cannot package `python -m frontend.desktop` directly, so we
provide this thin wrapper at the project root. Build with:

  pyinstaller --onefile --windowed --name InvisibleGo desktop_main.py
"""
import sys

from frontend.desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
