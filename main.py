#!/usr/bin/env python
"""Entry point: python main.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_code_coach.app import run

if __name__ == "__main__":
    sys.exit(run())
