#!/usr/bin/env python
"""PyInstaller entry point for the standalone Coach service executable.

Thin wrapper only, same pattern as hook_receiver_entry.py — the real logic
is claude_code_coach/service/__main__.py's main(), completely unchanged.
This file exists only because that module uses relative imports
(`from ..database import init_db`), which only resolve when the module is
imported as part of its package — pointing PyInstaller directly at a
relatively-importing submodule as a top-level script fails the same way
`python claude_code_coach/service/__main__.py` (as opposed to
`python -m claude_code_coach.service`) would.

Zero PySide6/Qt import anywhere in this chain (verified: this is the same
property claude_code_coach/service/__main__.py's own docstring already
requires of the whole service — this wrapper adds none).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.service.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
