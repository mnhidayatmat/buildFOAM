"""Shared test configuration.

``tools/`` is not an installed package — it holds standalone CI scripts — so it
is put on the path here to let the guard tests exercise the detection logic
directly rather than only through a subprocess exit code. A guard that silently
stops catching things is worse than no guard, so the guards get tested too.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Qt widget tests render offscreen so the suite needs no display: it works on a
# CI runner, over ssh, and without stealing focus during a local run. Set before
# any PySide6 import, since the platform plugin is chosen at QApplication
# construction and cannot be changed afterwards.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
TESTS_DIR = Path(__file__).resolve().parent

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
