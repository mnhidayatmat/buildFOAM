"""CaseService — open, classify and describe an OpenFOAM case (§5.1, §5.2, FR-C2).

**A case is a directory, not a project file.** Everything the application adds
lives in one hidden directory that OpenFOAM ignores, so deleting it leaves a case
that still runs from a bare shell (FR-C7). That invariant is the mechanical
expression of D4 — never trapping the user — and it is why classification reads
the case tree first and the metadata second, never the other way round.

**Opening must not fail because one file is odd.** FR-C2's acceptance criterion is
that *any* tutorial from the OpenFOAM distribution opens without error, and the
tutorial suite puts non-dictionary files under ``system/`` and ``constant/``:
geometry, CSV data, m4 templates, shell scripts. A case opener that parsed
everything eagerly and propagated the first failure would refuse cases that run
perfectly well. Parse failures are therefore *findings attached to a file*, not
exceptions — the case still opens, the Preprocessor still lists the file, and the
raw-text tab still shows it (FR-P6).

Only one thing makes a directory not a case: no ``system/controlDict`` (E-C01).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from foamwb import __version__
from foamwb.branding import (
    APP_DISPLAY_NAME,
    CASE_METADATA_DIR,
    CASE_METADATA_FILE,
)
from foamwb.codes import Code, ErrorCode, Severity
from foamwb.logs import Event, get_logger, log_event
from foamwb.services import fence
from foamwb.services.foamdict import Document, ParseError

__all__ = [
    "Case",
    "CaseClass",
    "CaseError",
    "CaseMetadata",
    "CaseService",
    "Finding",
    "RunRecord",
]

_log = get_logger("case")

#: The file whose presence defines a case (§5.1).
CONTROL_DICT = Path("system") / "controlDict"

#: Directories that hold the case *definition* and therefore contribute to the
#: tree hash. Written results do not: a hash that changed every write interval
#: would fire FR-C4's "modified outside" banner during a run.
DEFINITION_DIRS = ("system", "constant", "0", "0.orig")

#: Never part of the case definition, and never hashed.
TRANSIENT_NAMES = frozenset({CASE_METADATA_DIR, "postProcessing", "dynamicCode", "logs"})


class CaseClass(StrEnum):
    """§5.1's four classifications."""

    MANAGED = "managed"
    """Metadata present and the tree hash matches. Full UX with run history."""

    FOREIGN = "foreign"
    """A valid case tree with no metadata. Full UX; metadata is written on first
    write, with consent — opening someone else's case must not modify it."""

    MODIFIED = "modified"
    """Metadata present, hash mismatch: the case changed outside the application.
    Never silently overwritten (FR-C4) — the user is offered Reload, Diff or
    Keep-mine."""


class CaseError(ValueError):
    """A directory that cannot be opened as a case."""

    def __init__(self, message: str, code: Code, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class Finding:
    """One problem with a case (FR-C3).

    Carries file, line and a §9 code so the validation panel can be clicked
    through to the offending line rather than reporting "invalid case".
    """

    code: Code
    severity: Severity
    file: Path
    line: int | None = None
    column: int | None = None
    detail: str = ""

    @property
    def blocks_run(self) -> bool:
        return self.severity >= Severity.ERROR


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One entry in the case's run history (§5.2)."""

    id: str
    started: str
    finished: str | None = None
    exit_code: int | None = None
    plan: tuple[str, ...] = ()
    n_procs: int = 1
    wall_seconds: float = 0.0
    final_time: str | None = None
    converged: bool | None = None
    log_dir: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "started": self.started,
            "finished": self.finished,
            "exit": self.exit_code,
            "plan": list(self.plan),
            "n_procs": self.n_procs,
            "wall_seconds": self.wall_seconds,
            "final_time": self.final_time,
            "converged": self.converged,
            "log_dir": self.log_dir,
        }

    @classmethod
    def from_json(cls, raw: dict) -> RunRecord:
        return cls(
            id=raw.get("id", ""),
            started=raw.get("started", ""),
            finished=raw.get("finished"),
            exit_code=raw.get("exit"),
            plan=tuple(raw.get("plan", ())),
            n_procs=raw.get("n_procs", 1),
            wall_seconds=raw.get("wall_seconds", 0.0),
            final_time=raw.get("final_time"),
            converged=raw.get("converged"),
            log_dir=raw.get("log_dir", ""),
        )


@dataclass(slots=True)
class CaseMetadata:
    """The per-case metadata document (§5.2).

    Its location is :data:`~foamwb.branding.CASE_METADATA_DIR` /
    :data:`~foamwb.branding.CASE_METADATA_FILE` — named here by constant rather
    than spelled out, because a literal path in prose becomes silently wrong the
    moment the product is renamed (NFR-M5, DEC-03).

    Deleting it degrades the experience — lost run history — and never breaks the
    case. That is asserted by FR-C7's automated test, not merely intended.
    """

    schema: int = 1
    created_by: str = ""
    created_at: str = ""
    template: str | None = None
    lineage: str = "esi"
    openfoam_version: str | None = None
    tree_hash: str = ""
    runs: list[RunRecord] = field(default_factory=list)
    ui: dict = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "template": self.template,
            "openfoam": {"lineage": self.lineage, "version": self.openfoam_version},
            "tree_hash": self.tree_hash,
            "runs": [run.to_json() for run in self.runs],
            "ui": self.ui,
        }

    @classmethod
    def from_json(cls, raw: dict) -> CaseMetadata:
        openfoam = raw.get("openfoam", {})
        return cls(
            schema=raw.get("schema", 1),
            created_by=raw.get("created_by", ""),
            created_at=raw.get("created_at", ""),
            template=raw.get("template"),
            lineage=openfoam.get("lineage", "esi"),
            openfoam_version=openfoam.get("version"),
            tree_hash=raw.get("tree_hash", ""),
            runs=[RunRecord.from_json(r) for r in raw.get("runs", [])],
            ui=raw.get("ui", {}),
        )


@dataclass(slots=True)
class Case:
    """An opened case."""

    path: Path
    classification: CaseClass
    metadata: CaseMetadata | None = None
    application: str | None = None
    """Solver from ``system/controlDict``, or ``None`` if unreadable."""

    findings: list[Finding] = field(default_factory=list)
    tree_hash: str = ""

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def metadata_dir(self) -> Path:
        return self.path / CASE_METADATA_DIR

    @property
    def foam_stub(self) -> Path:
        """The ``<case>/<case>.foam`` file ParaView's reader looks for (FR-V2)."""
        return self.path / f"{self.name}.foam"

    @property
    def is_modified_externally(self) -> bool:
        return self.classification is CaseClass.MODIFIED

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.blocks_run]

    def time_directories(self) -> list[str]:
        """Written time directories, numerically sorted.

        Sorted as numbers, not as strings: ``10`` sorts after ``9`` numerically
        and before it lexically, so a string sort would report the wrong latest
        time and FR-S8's resume would restart from the wrong place.
        """
        times = []
        for child in self.path.iterdir():
            if child.is_dir() and (value := _as_time(child.name)) is not None:
                times.append((value, child.name))
        return [name for _value, name in sorted(times)]

    @property
    def latest_time(self) -> str | None:
        times = self.time_directories()
        return times[-1] if times else None

    @property
    def has_results(self) -> bool:
        return any(t not in {"0", "0.orig"} for t in self.time_directories())


def _as_time(name: str) -> float | None:
    try:
        return float(name)
    except ValueError:
        return None


def _write_atomically(target: Path, data: bytes) -> None:
    """Write via a temporary file and rename (NFR-R2).

    A crash mid-write must never truncate a case file. Rename is atomic on both
    supported platforms, so the file is either the old one or the new one.
    """
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)


def _is_definition_file(case: Path, path: Path) -> bool:
    """Whether a file is part of the case definition and so contributes to the hash."""
    try:
        relative = path.relative_to(case)
    except ValueError:  # pragma: no cover - callers pass descendants
        return False
    if TRANSIENT_NAMES & set(relative.parts):
        return False
    if relative.parts and relative.parts[0].startswith("processor"):
        return False
    return bool(relative.parts) and relative.parts[0] in DEFINITION_DIRS


class CaseService:
    """Opens cases and owns their metadata (§4.2)."""

    def __init__(self, app_version: str | None = None) -> None:
        self._app_version = app_version or __version__

    # -- opening -----------------------------------------------------------

    def is_case(self, path: Path) -> bool:
        return (path / CONTROL_DICT).is_file()

    def open(self, path: Path) -> Case:
        """Open a case directory (FR-C2).

        Raises :class:`CaseError` with E-C01 only when the directory is not a
        case at all. Every other problem becomes a finding, so a case with one
        unreadable dictionary still opens and can be repaired in the raw-text tab.
        """
        path = path.expanduser().resolve()

        if not path.is_dir():
            raise CaseError(f"Not a directory: {path}", ErrorCode.NOT_A_CASE, path)
        if not self.is_case(path):
            raise CaseError(
                f"No {CONTROL_DICT.as_posix()} here, so this is not an OpenFOAM case folder",
                ErrorCode.NOT_A_CASE,
                path,
            )

        findings: list[Finding] = []
        application = self._read_application(path, findings)
        tree_hash = self.tree_hash(path)
        metadata = self._read_metadata(path, findings)

        if metadata is None:
            classification = CaseClass.FOREIGN
        elif metadata.tree_hash and metadata.tree_hash != tree_hash:
            classification = CaseClass.MODIFIED
        else:
            classification = CaseClass.MANAGED

        log_event(
            _log,
            Event.CASE_CLASSIFY,
            case=str(path),
            classification=classification.value,
            application=application,
            findings=len(findings),
        )
        return Case(
            path=path,
            classification=classification,
            metadata=metadata,
            application=application,
            findings=findings,
            tree_hash=tree_hash,
        )

    def _read_application(self, path: Path, findings: list[Finding]) -> str | None:
        control = path / CONTROL_DICT
        try:
            document = Document.parse_bytes(control.read_bytes())
        except ParseError as exc:
            # E-C02 with a location, so the editor can put the cursor on it. The
            # case still opens: this is the file the user most needs to fix.
            findings.append(
                Finding(
                    code=ErrorCode.PARSE_ERROR,
                    severity=Severity.ERROR,
                    file=control,
                    line=exc.line,
                    column=exc.column,
                    detail=exc.message,
                )
            )
            return None
        except OSError as exc:  # pragma: no cover - unreadable file
            findings.append(
                Finding(
                    code=ErrorCode.PARSE_ERROR,
                    severity=Severity.ERROR,
                    file=control,
                    detail=str(exc),
                )
            )
            return None
        return document.get("application")

    def _read_metadata(self, path: Path, findings: list[Finding]) -> CaseMetadata | None:
        source = path / CASE_METADATA_DIR / CASE_METADATA_FILE
        if not source.is_file():
            return None
        try:
            return CaseMetadata.from_json(json.loads(source.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError, AttributeError) as exc:
            # Corrupt metadata is a degraded experience, never a broken case —
            # the case is the directory, and the metadata is an accessory to it.
            findings.append(
                Finding(
                    code=ErrorCode.PARSE_ERROR,
                    severity=Severity.WARNING,
                    file=source,
                    detail=f"Run history could not be read and will be rebuilt: {exc}",
                )
            )
            return None

    # -- hashing -----------------------------------------------------------

    def tree_hash(self, path: Path) -> str:
        """Hash the case *definition* (§5.2's ``tree_hash``).

        Covers ``system/``, ``constant/`` and the initial-condition directories,
        and excludes written time directories, ``processor*`` and
        ``postProcessing``. Results are deliberately outside it: a hash that moved
        every write interval would fire FR-C4's "changed outside" banner
        continuously during a run, training the user to dismiss the one warning
        that matters.

        Paths are hashed alongside contents, so renaming a file is a change even
        when the bytes are identical.
        """
        digest = hashlib.sha256()
        for file in sorted(p for p in path.rglob("*") if p.is_file()):
            if not _is_definition_file(path, file):
                continue
            digest.update(file.relative_to(path).as_posix().encode("utf-8"))
            digest.update(b"\0")
            try:
                digest.update(file.read_bytes())
            except OSError:  # pragma: no cover - unreadable file
                digest.update(b"<unreadable>")
            digest.update(b"\0")
        return f"sha256:{digest.hexdigest()}"

    # -- metadata ----------------------------------------------------------

    def write_metadata(
        self,
        case: Case,
        *,
        openfoam_version: str | None = None,
        template: str | None = None,
    ) -> CaseMetadata:
        """Create or refresh the case metadata document.

        Written atomically (NFR-R2): temp file, then rename. A crash mid-write
        must not leave truncated metadata, because the next open would classify
        the case as modified and offer to overwrite the user's own edits.
        """
        metadata = case.metadata or CaseMetadata(
            created_by=f"{APP_DISPLAY_NAME} {self._app_version}",
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            template=template,
        )
        metadata.tree_hash = self.tree_hash(case.path)
        if openfoam_version:
            metadata.openfoam_version = openfoam_version

        case.metadata_dir.mkdir(parents=True, exist_ok=True)
        target = case.metadata_dir / CASE_METADATA_FILE
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(metadata.to_json(), indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

        case.metadata = metadata
        case.tree_hash = metadata.tree_hash
        case.classification = CaseClass.MANAGED
        log_event(_log, Event.CASE_WRITE, case=str(case.path))
        return metadata

    def record_run(self, case: Case, record: RunRecord) -> None:
        """Append a run to the history and persist it (FR-S7)."""
        if case.metadata is None:
            self.write_metadata(case)
        assert case.metadata is not None
        case.metadata.runs.append(record)
        self.write_metadata(case)

    def accept_external_changes(self, case: Case) -> None:
        """Adopt the case as it now is on disk — FR-C4's "Keep mine"."""
        self.write_metadata(case)

    # -- monitoring --------------------------------------------------------

    def solved_fields(self, case: Case) -> tuple[str, ...]:
        """Field names to hand to ``solverInfo`` (FR-S3).

        Taken from the initial-condition directory, because that is what the case
        itself declares it solves for — ``icoFoam`` has ``U`` and ``p``,
        ``interFoam`` has ``U``, ``p_rgh`` and ``alpha.water``. Hard-coding a set
        per solver would need a table that goes stale with every OpenFOAM release
        and would be wrong for any custom solver, which is exactly what NFR-M3
        exists to prevent.

        Naming a field the solver does not solve is harmless: ``solverInfo``
        simply reports no columns for it.
        """
        for directory in ("0", "0.orig"):
            source = case.path / directory
            if source.is_dir():
                return tuple(
                    sorted(
                        entry.name
                        for entry in source.iterdir()
                        if entry.is_file() and not entry.name.startswith(".")
                    )
                )
        return ()

    def enable_monitoring(self, case: Case) -> bool:
        """Install the residual-monitoring fence in ``controlDict`` (FR-S3).

        Done at *run* time rather than at open: opening someone else's case must
        not modify it (§5.1), while a user who pressed Run has asked for the run
        and its monitoring. The block is fenced, self-describing and reversible
        (NFR-C3), and removing it leaves the file byte-identical.

        Returns whether anything was written, so a caller can say what it did.
        """
        fields = self.solved_fields(case)
        if not fields:
            return False

        control = case.path / CONTROL_DICT
        original = control.read_bytes()
        updated = fence.install(original.decode("utf-8"), fence.solver_info_block(fields)).encode(
            "utf-8"
        )
        if updated == original:
            return False

        _write_atomically(control, updated)
        case.tree_hash = self.tree_hash(case.path)
        if case.metadata is not None:
            self.write_metadata(case)
        return True

    def disable_monitoring(self, case: Case) -> bool:
        """Remove the fence, restoring ``controlDict`` byte-for-byte (FR-C5)."""
        control = case.path / CONTROL_DICT
        original = control.read_bytes()
        updated = fence.remove(original.decode("utf-8")).encode("utf-8")
        if updated == original:
            return False

        _write_atomically(control, updated)
        case.tree_hash = self.tree_hash(case.path)
        if case.metadata is not None:
            self.write_metadata(case)
        return True

    # -- initial conditions ------------------------------------------------

    def needs_initial_conditions(self, case: Case) -> bool:
        """Whether ``0.orig`` must be restored to ``0`` before the case can run.

        This is not an edge case. In the v2512 tutorial suite **351 cases ship
        ``0.orig`` with no ``0``, against 78 that ship a ``0``** — the majority of
        tutorials cannot run as they are unpacked. Their ``Allrun`` scripts open
        with ``restore0Dir``, and a user who imports such a tutorial and presses
        Run without it gets a failure that has nothing to do with their case.

        FR-C2 requires any tutorial to open, and FR-C1 requires a created case to
        run to ``endTime`` unmodified; neither holds unless something performs
        this step.
        """
        return (case.path / "0.orig").is_dir() and not (case.path / "0").is_dir()

    def restore_initial_conditions(self, case: Case) -> bool:
        """Copy ``0.orig`` to ``0``, as OpenFOAM's own ``restore0Dir`` does.

        A filesystem operation rather than a :class:`RunPlan` stage: there is no
        OpenFOAM *binary* that does it — ``restore0Dir`` is a shell function in
        the tutorial helpers — and expressing it as an argv would mean shelling
        out to ``cp`` for something the application can do directly and report on.

        Returns whether it acted, so a caller can tell the user what happened
        rather than silently rewriting their case. The metadata hash is refreshed
        afterwards: this is an application-initiated change, and leaving it would
        classify the case as modified-outside on the next open (FR-C4) and offer
        to undo work the user just asked for.
        """
        if not self.needs_initial_conditions(case):
            return False

        shutil.copytree(case.path / "0.orig", case.path / "0", symlinks=False)
        log_event(_log, Event.CASE_WRITE, case=str(case.path), action="restore_initial")

        case.tree_hash = self.tree_hash(case.path)
        if case.metadata is not None:
            self.write_metadata(case)
        return True
