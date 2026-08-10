"""Shared test configuration.

``tools/`` is not an installed package — it holds standalone CI scripts — so it
is put on the path here to let the guard tests exercise the detection logic
directly rather than only through a subprocess exit code. A guard that silently
stops catching things is worse than no guard, so the guards get tested too.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
TESTS_DIR = Path(__file__).resolve().parent

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
