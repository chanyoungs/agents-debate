#!/usr/bin/env python3
"""Installed skill wrapper for the project-owned run_debate runtime."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path("{{AGENTS_DEBATE_ROOT}}")
TARGET = PROJECT_ROOT / "runtime" / "run_debate.py"


def main() -> int:
    result = subprocess.run(["python3", str(TARGET), *sys.argv[1:]], check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
