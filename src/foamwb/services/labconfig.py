"""Managed-image configuration (FR-R7, FR-R8, §14).

A lab machine is not a small version of a personal one. §14's users are a
university IT department imaging two hundred machines and a student account with
no administrator rights — and on that account ``wsl --install`` is simply
impossible, so a first run that tries it dead-ends every student in the room.

Two capabilities, one file:

* **Silent provisioning** (FR-R7). The installer runs from an imaging script
  with no UI and no questions.
* **Adopting what is already there** (FR-R8). IT provisioned the runtime once,
  into the image; the application must find it and report ready rather than
  attempting an install it cannot perform.

**A lab config is trusted about paths and never about safety.** It says where
the runtime is; it cannot switch off the content signature check or lower any
other guarantee. An administrator installing for two hundred students is exactly
the person who must not be able to disable verification for two hundred
students, and a setting that could would eventually be found by someone copying
a configuration from a forum.

**A configuration that does not describe this machine is reported, not
half-applied.** A bashrc path that does not exist means the image is not what the
file says it is, and continuing on the parts that happen to match would produce a
machine that half works, silently, on every one of the two hundred.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from foamwb.branding import APP_ID, WSL_DISTRO_NAME
from foamwb.codes import Code, ErrorCode

__all__ = [
    "CONFIG_ENV_VAR",
    "LabConfig",
    "LabConfigError",
    "adoption_status",
    "load_lab_config",
]

#: Where an imaging script points the application at its configuration.
CONFIG_ENV_VAR = f"{APP_ID.upper()}_LAB_CONFIG"


class LabConfigError(Exception):
    """A configuration that could not be used, with the §9 code to report."""

    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class LabConfig:
    """What a managed image declares about itself."""

    silent: bool = False
    """FR-R7: run without UI. Only meaningful during provisioning."""

    adopt_runtime: bool = False
    """FR-R8: a runtime is already present; do not attempt to install one."""

    distro: str = WSL_DISTRO_NAME
    bashrc: PurePosixPath | None = None
    """Where the OpenFOAM environment script lives inside the runtime."""

    version: str = ""
    """Which OpenFOAM release the image provides, for the footer to report."""

    case_root: Path | None = None
    """Where students' cases should live — often a network home directory."""

    telemetry: bool = False
    """Default off, as §7.3 step 1 requires. Present so an institution can
    record a decision it has actually made, never to enable it by omission."""

    source: Path | None = field(default=None, compare=False)

    @property
    def is_managed(self) -> bool:
        return self.adopt_runtime or self.silent


def load_lab_config(path: Path) -> LabConfig:
    """Read and validate a lab configuration.

    Every failure raises rather than returning a default. A managed install that
    silently fell back to "install it yourself" would produce two hundred
    machines that each stop at the first administrator prompt — the exact
    outcome §14 exists to prevent — and it would do so without saying why.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LabConfigError(
            ErrorCode.NOT_PROVISIONED, f"The lab configuration could not be read: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LabConfigError(
            ErrorCode.NOT_PROVISIONED,
            f"{path.name} is not valid JSON: line {exc.lineno}, column {exc.colno}.",
        ) from exc

    if not isinstance(raw, dict):
        raise LabConfigError(ErrorCode.NOT_PROVISIONED, f"{path.name} should contain an object.")

    _refuse_unsafe_keys(raw, path)

    bashrc = raw.get("bashrc")
    adopt = bool(raw.get("adopt_runtime", False))
    if adopt and not bashrc:
        raise LabConfigError(
            ErrorCode.RUNTIME_BROKEN,
            "adopt_runtime is set but no bashrc path is given, so there is nothing to adopt.",
        )

    case_root = raw.get("case_root")
    return LabConfig(
        silent=bool(raw.get("silent", False)),
        adopt_runtime=adopt,
        distro=str(raw.get("distro", WSL_DISTRO_NAME)),
        bashrc=PurePosixPath(str(bashrc)) if bashrc else None,
        version=str(raw.get("version", "")),
        case_root=Path(str(case_root)) if case_root else None,
        telemetry=bool(raw.get("telemetry", False)),
        source=path,
    )


#: Settings a configuration file may not contain. Each would weaken a guarantee
#: the application makes to the *student*, who did not write the file and cannot
#: see it. An administrator may decide where things are installed; they may not
#: decide that unverified content is acceptable on someone else's behalf.
_FORBIDDEN_KEYS: dict[str, str] = {
    "skip_signature_check": "content verification cannot be switched off (E-L01)",
    "allow_unsigned_content": "content verification cannot be switched off (E-L01)",
    "disable_verification": "content verification cannot be switched off (E-L01)",
    "public_key": "the signing key is compiled in and cannot be replaced by a file",
}


def _refuse_unsafe_keys(raw: dict, path: Path) -> None:
    present = sorted(key for key in _FORBIDDEN_KEYS if key in raw)
    if not present:
        return
    reasons = "; ".join(_FORBIDDEN_KEYS[key] for key in present)
    raise LabConfigError(
        ErrorCode.SIGNATURE_INVALID,
        f"{path.name} sets {', '.join(present)}, which is not permitted: {reasons}.",
    )


@dataclass(frozen=True, slots=True)
class AdoptionStatus:
    """Whether a declared runtime is actually present on this machine."""

    usable: bool
    detail: str = ""
    code: Code | None = None


def adoption_status(config: LabConfig, *, exists: bool | None = None) -> AdoptionStatus:
    """Check that the image really provides what the configuration claims.

    ``exists`` lets a caller supply the answer for a path inside a runtime this
    process cannot see directly — a WSL path is not a host path, and stat-ing it
    from Windows would test the wrong filesystem.
    """
    if not config.adopt_runtime:
        return AdoptionStatus(usable=False, detail="This configuration adopts nothing.")

    if config.bashrc is None:
        return AdoptionStatus(
            usable=False,
            detail="No environment script was named.",
            code=ErrorCode.RUNTIME_BROKEN,
        )

    present = exists if exists is not None else Path(str(config.bashrc)).is_file()
    if not present:
        # The image is not what the file says it is. Reported rather than
        # worked around, because the same wrong file is on every machine.
        return AdoptionStatus(
            usable=False,
            detail=(
                f"{config.bashrc} is not present in {config.distro}. The image "
                "does not provide the runtime this configuration declares."
            ),
            code=ErrorCode.RUNTIME_BROKEN,
        )

    return AdoptionStatus(usable=True, detail=f"Adopted {config.distro}.")
