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

import pytest

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


def require_runtime_or_skip(reason: str) -> None:
    """Skip locally, fail loudly in CI.

    A gate that silently skips is worse than no gate: it reports green while
    verifying nothing, which is precisely the failure the §12.3 rows exist to
    prevent. Setting FOAMWB_REQUIRE_RUNTIME=1 — as the golden-case CI job does —
    turns "no OpenFOAM here" from an acceptable local condition into a build
    failure, because in that job it means the runtime never installed.
    """
    import pytest

    if os.environ.get("FOAMWB_REQUIRE_RUNTIME"):
        pytest.fail(f"FOAMWB_REQUIRE_RUNTIME is set, so this must not be skipped: {reason}")
    pytest.skip(reason)


# ---------------------------------------------------------------------------
# Headless environments without Qt
# ---------------------------------------------------------------------------
#
# The §12.3 golden-case job runs in an OpenFOAM container that has the solver but
# none of Qt's system libraries, so `import PySide6.QtCore` raises ImportError
# even though the wheel is installed. That is the correct environment for that
# job — it gates the *service* layer, which NFR-M1 requires to be exercisable
# with no Qt at all.
#
# So the UI tests exclude themselves when Qt cannot load, rather than the
# workflow maintaining a list of files to skip. A list would drift the first time
# someone adds a view; this cannot.


def _qt_is_usable() -> bool:
    try:
        import PySide6.QtCore  # noqa: F401
    except Exception:
        return False
    return True


QT_AVAILABLE = _qt_is_usable()

#: Test modules that need a working Qt. Named by the thing they test, so the
#: reason a module is here is visible from its name.
_UI_TEST_MODULES = (
    "test_app.py",
    "test_probe.py",
    "test_preprocessor_view.py",
    "test_run_view.py",
    "test_shell.py",
    "test_theme.py",
)

collect_ignore = [] if QT_AVAILABLE else list(_UI_TEST_MODULES)


# ---------------------------------------------------------------------------
# Shared runtime fixtures
# ---------------------------------------------------------------------------
#
# Defined here rather than duplicated into every module that needs a real
# OpenFOAM: three copies of "find an installation, verify it, locate its
# tutorials" would drift, and the copy that drifted would be the one that
# quietly stopped exercising anything.


@pytest.fixture(scope="session")
def runtime():
    from foamwb.services.runtime import RuntimeManager

    manager = RuntimeManager()
    installations = manager.discover()
    if not installations:
        require_runtime_or_skip("no OpenFOAM installation found")
    status = manager.verify(installations[0])
    if not status.is_usable:
        require_runtime_or_skip(f"OpenFOAM not usable: {status.detail}")
    return manager, installations[0], status


@pytest.fixture(scope="session")
def tutorials(runtime) -> Path:
    manager, installation, _status = runtime
    found = manager.tutorials_dir(installation)
    if found is None:
        require_runtime_or_skip(f"tutorials not reachable from {installation.entry_point}")
    return found
