# PyInstaller spec (M8, NFR-P8).
#
# Named app.spec rather than after the product: the name is still open
# until M8 (DEC-03), and a filename carrying it is one more place a rename
# would have to reach. The bundle and executable names come from branding.py
# at build time, so the artefact is named correctly without this file being.
#
# The exclusion list is the whole point of this file, not housekeeping. PySide6
# ships 1,164 MB on the development machine, of which QtWebEngineCore alone is
# 453 MB and the FFmpeg libraries behind QtMultimedia another 60 MB. A naive
# freeze therefore lands far outside NFR-P8's 250 MB compressed budget, which is
# why the PRD calls stripping a build requirement rather than an optimisation.
#
# The list names what is *excluded* rather than what is kept, deliberately. An
# allow-list silently drops a module the day someone adds a widget that needs it,
# and the failure surfaces on a user's machine as an import error. Excluding by
# name fails at build time instead, where it is cheap.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "src"))
from foamwb.branding import APP_DISPLAY_NAME, BUNDLE_ID  # noqa: E402

#: Qt modules this application does not use. Each comment says why, so a future
#: reader can tell a deliberate exclusion from an oversight.
EXCLUDED_QT = [
    "PySide6.QtWebEngineCore",      # 453 MB. No embedded browser anywhere.
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtMultimedia",         # pulls FFmpeg: ~60 MB of libav*.
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.QtQuick",              # the UI is QtWidgets throughout.
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtCharts",             # plotting is pyqtgraph.
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",           # a developer tool, not a runtime one.
    "PySide6.QtUiTools",
    "PySide6.QtHelp",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtSql",                # settings are JSON; no database.
    "PySide6.QtTest",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebView",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSensors",
    "PySide6.QtHttpServer",
    "PySide6.QtGraphs",
]

#: Not Qt, but present in the environment and not part of the artefact.
EXCLUDED_OTHER = ["tkinter", "matplotlib", "IPython", "pytest", "setuptools"]

#: Everything read at runtime through importlib.resources: the runtime manifest,
#: the form schemas, the turbulence data, the signed content library, the guide.
DATA = [(str(ROOT / "src" / "foamwb" / "data"), "foamwb/data")]


a = Analysis(
    [str(ROOT / "src" / "foamwb" / "ui" / "app.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=DATA,
    hiddenimports=["foamwb"],
    excludes=EXCLUDED_QT + EXCLUDED_OTHER,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_DISPLAY_NAME,
    console=False,
    # Signing and notarisation happen after this step, from a machine that holds
    # the certificates. Deliberately not automated here: a spec that expects a
    # signing identity cannot be built by anyone who does not have one, and the
    # build should be reproducible by a contributor.
    codesign_identity=None,
    entitlements_file=None,
)

collected = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_DISPLAY_NAME)

app = BUNDLE(collected, name=f"{APP_DISPLAY_NAME}.app", bundle_identifier=BUNDLE_ID)
