"""Allow `python -m frontend.desktop` to launch the desktop client."""
import sys

from frontend.desktop.app import main

sys.exit(main())
