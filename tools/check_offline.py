"""The application works offline (NFR-R5).

"Fully offline once provisioned, except the update check and the remote
catalogue." §2's users include a lab machine behind a proxy that blocks
everything, and a student on hotel wifi the night before a deadline. A feature
that silently needs the network fails for both, and fails in the way that is
hardest to diagnose: it hangs.

This is checked structurally rather than by running with the network down,
because a runtime check only exercises the paths a test happens to take. If no
module can open a socket, no code path can — including the ones nobody thought
to test.

AST-based, so a URL inside a docstring or a comment is fine and an import buried
in a function is not. Downloads are performed by the package manager the
provisioner invokes as a subprocess, which is why nothing here needs a
networking import today.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "src" / "foamwb"

#: Modules that reach the network. Importing one is a statement that this code
#: needs connectivity, which NFR-R5 permits only in named places.
NETWORK_MODULES = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "http.client",
        "urllib.request",
        "urllib.error",
        "ftplib",
        "telnetlib",
        "smtplib",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "xmlrpc.client",
    }
)

#: Where connectivity is allowed, with the requirement that permits it. Empty
#: today: provisioning downloads through brew and apt as subprocesses, and the
#: content catalogue is bundled rather than fetched (FR-L6 defers the remote one
#: to v1.1). An entry here is a deliberate exception, not a convenience.
ALLOWED: dict[str, str] = {}


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def main() -> int:
    offences: list[str] = []

    for source in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        relative = source.relative_to(REPO_ROOT).as_posix()
        if relative in ALLOWED:
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except SyntaxError as exc:  # pragma: no cover - caught by the lint step
            print(f"check_offline: cannot parse {relative}: {exc}", file=sys.stderr)
            return 1

        for name in sorted(_imports(tree)):
            root = name.split(".")[0]
            if name in NETWORK_MODULES or (root in NETWORK_MODULES and root != name):
                offences.append(f"  {relative}: imports {name}")

    if offences:
        print(
            "NFR-R5 violation — the application must work offline once "
            "provisioned:\n" + "\n".join(offences),
            file=sys.stderr,
        )
        print(
            "\nIf this module genuinely needs connectivity, add it to ALLOWED in "
            "this script with the requirement that permits it. A feature that "
            "silently needs the network hangs on the machines least able to "
            "diagnose it.",
            file=sys.stderr,
        )
        return 1

    print(
        "check_offline: OK — no service or view can open a network connection"
        + (f" ({len(ALLOWED)} documented exception(s))" if ALLOWED else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
