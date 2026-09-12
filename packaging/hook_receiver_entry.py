#!/usr/bin/env python
"""PyInstaller entry point for the standalone hook_receiver companion exe.

Thin wrapper only — the real logic lives in
claude_code_coach.runtime.hook_receiver, the exact same module the
source (non-packaged) build invokes as `sys.executable hook_receiver.py`.
This file exists only so PyInstaller has a top-level script to analyze; it
is never imported by the rest of the app, and it is deliberately kept free
of any PySide6/Qt import — see hook_installer.py's module docstring for
why this ships as a second, separate executable rather than being folded
into the main app's own exe.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.runtime.hook_receiver import _main  # noqa: E402

if __name__ == "__main__":
    sys.exit(_main())
