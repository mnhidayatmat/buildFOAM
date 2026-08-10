# Product Requirements Document — **BuildFOAM**
### A desktop workbench for OpenFOAM®

**Version:** 1.0 · **Status:** Approved for build · **Date:** 10 August 2026
**Supersedes:** PRD v0.1 "OpenFOAM GUI Launcher (Kicker)", 10 August 2026
**Companion:** `PRD-review-memo.md` — why v0.1 changed

> *BuildFOAM is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.*

> **Working name: BuildFOAM** — chosen by the product owner, with one risk knowingly accepted and recorded here so it is not rediscovered later.
>
> `<something>Foam` is OpenFOAM's own executable naming convention: `simpleFoam`, `icoFoam`, `interFoam`, `rhoCentralFoam`, and `paraFoam` (which already launches ParaView on a case). A product named `BuildFOAM` therefore reads to an experienced user as a command shipping *inside* OpenFOAM rather than as a third-party application, and that origin confusion is the substance of what OpenCFD's trade mark guidelines are written to prevent. FOAM alone is not the registered mark — OPENFOAM is — so this is a plausible-letter risk rather than clear infringement, and it is the product owner's call to take. Two practical consequences to plan for regardless: users will expect a terminal utility, and the name will not distinguish the product in search from OpenFOAM's own tooling.
>
> **NFR-M5 is the insurance.** The identifier appears in exactly two places in the source tree, so reversing this decision costs two lines plus a migration shim rather than an excavation across the installer, bundle identifier, distro name, case metadata and content namespace. Revisit before M8, when the name becomes public and the reversal cost rises sharply. See DEC-03.

---

## Table of contents

1. [Product definition](#1-product-definition)
2. [Scope and release plan](#2-scope-and-release-plan)
3. [Platform and runtime strategy](#3-platform-and-runtime-strategy)
4. [Architecture](#4-architecture)
5. [Data model](#5-data-model)
6. [Functional requirements](#6-functional-requirements)
7. [User interface specification](#7-user-interface-specification)
8. [Non-functional requirements](#8-non-functional-requirements)
9. [Error taxonomy and failure UX](#9-error-taxonomy-and-failure-ux)
10. [Security, privacy and trust](#10-security-privacy-and-trust)
11. [Milestones and exit criteria](#11-milestones-and-exit-criteria)
12. [Verification and test plan](#12-verification-and-test-plan)
13. [Licensing and legal](#13-licensing-and-legal)
14. [Teaching and laboratory deployment](#14-teaching-and-laboratory-deployment)
15. [Release, update and support](#15-release-update-and-support)
16. [Decision log](#16-decision-log)
17. [Risk register](#17-risk-register)
18. [Glossary](#18-glossary)

---

## 1. Product definition

### 1.1 One-sentence definition

BuildFOAM is a cross-platform desktop application that installs, configures and drives a complete OpenFOAM workflow — mesh, solve, visualise — without the user ever opening a terminal.

### 1.2 The problem

OpenFOAM is the most capable open-source CFD toolkit in existence and one of the least approachable. Three barriers, in the order users hit them:

1. **Installation.** On Windows it means WSL2, a Linux distribution, an apt repository, and environment sourcing. On macOS it means a third-party Homebrew tap or Docker. Both defeat a large fraction of prospective users before they run anything.
2. **Environment.** Every command must run inside a shell that has sourced the correct `etc/bashrc`. Divergence between the two OpenFOAM lineages in dictionary names (ESI `transportProperties` / `turbulenceProperties` vs Foundation `physicalProperties` / `momentumTransport`) makes copied tutorials fail cryptically, and users cannot tell which lineage a forum post assumed.
3. **Case authoring.** A case is a tree of free-form dictionaries with no schema, no autocomplete, and error messages that report a line number in a file the user did not know existed. Boundary-condition/patch mismatches are the single most common beginner failure.

BuildFOAM addresses all three. It does not attempt to replace the CLI, ParaView, or a CAD/meshing suite.

### 1.3 Target users

| Persona | Description | Primary need | Success looks like |
|---|---|---|---|
| **P1 — Student** (primary) | Undergraduate/postgraduate in a CFD or thermofluids course. Windows laptop. No Linux experience. | Complete this week's lab exercise and submit results. | Runs the assigned tutorial to convergence within one 2-hour lab session, unaided. |
| **P2 — Lecturer** (primary) | Prepares and distributes lab exercises; must support ~40 students on mixed hardware. | Distribute a working case set; grade reproducible results. | Publishes a course pack once; zero installation support tickets per cohort. |
| **P3 — Practising engineer** (secondary) | Uses commercial CFD; evaluating OpenFOAM. Comfortable with engineering software, not with Linux. | Reproduce a known case and compare against a commercial result. | Gets a validated benchmark running in an afternoon. |
| **P4 — OpenFOAM power user** (tolerated, not targeted) | Already productive in the CLI. | Must not be obstructed. | Can hand-edit any case BuildFOAM touched, and BuildFOAM does not corrupt or reformat their files. |

**P4 is a constraint, not a feature.** Every design decision that would trap a user inside the GUI is rejected.

### 1.4 Competitive positioning

| Tool | What it is | Why BuildFOAM is different |
|---|---|---|
| **SimFlow** | Commercial freemium OpenFOAM GUI, Windows/Linux | BuildFOAM is free and open, and targets *provisioning* + *curriculum* rather than a general-purpose GUI. |
| **HELYX-OS** | Open-source OpenFOAM GUI, largely unmaintained | BuildFOAM targets current OpenFOAM releases with an explicit version-support policy. |
| **FreeCAD CfdOF workbench** | CFD workbench inside a CAD tool | BuildFOAM is CFD-first; CAD is out of scope. BuildFOAM does not require learning FreeCAD. |
| **Salome / integrated platforms** | Large multi-physics platforms | BuildFOAM is a single small installer, not a platform. |
| **Bare CLI + ParaView** | The status quo | BuildFOAM removes the terminal and the environment problem. |
| **Spreadsheets + hand calculation** | How grid-convergence studies and validation comparisons are done today, by almost everyone | BuildFOAM's V&V module (§6.9) automates the Celik/GCI procedure and the experimental comparison, which is currently manual, error-prone and rarely reproducible. This is the gap no GUI in the table above addresses. |

**The defensible differentiators — and therefore the things that must not be cut:**

- **D1.** One installer that leaves a working OpenFOAM stack behind, on a machine that had nothing.
- **D2.** Course packs: a lecturer publishes a week's lab as one file; a student imports it in one click.
- **D3.** Run reports: a submittable, reproducible PDF record of a simulation.
- **D4.** Never traps the user — every file remains a valid, hand-editable OpenFOAM dictionary.
- **D5.** **A built-in V&V workflow** (§6.9): guided turbulence-model and wall-treatment selection, an automated grid-convergence study producing a publication-ready GCI table, and structured comparison against experimental data. No open-source OpenFOAM front-end does this, and it is the capability that turns a student exercise into a defensible result.

### 1.5 Success metrics

| Metric | v1.0 target | Measurement |
|---|---|---|
| M-1 First-run success rate | ≥ 85% of clean installs reach "runtime ready" without support | Wizard telemetry (opt-in) + lab observation |
| M-2 Time to first result | ≤ 30 min from installer download to a converged `cavity` run on a clean Windows 11 machine | Timed acceptance test, three reference machines |
| M-3 Lab support load | ≤ 2 installation tickets per 40-student cohort | Lecturer report |
| M-4 CLI interop | 100% of BuildFOAM-written cases run unmodified from a bare solver invocation in a sourced shell (`simpleFoam`, `interFoam`, …) | Automated (§12.3) |
| M-5 Round-trip fidelity | 100% byte-identical for untouched regions of edited dictionaries | Automated (§12.2) |

---

## 2. Scope and release plan

### 2.1 Release ladder

| Release | Audience | Contents | Hard cut-line |
|---|---|---|---|
| **v0.9** | Internal / pilot cohort | One platform (see DEC-11), runtime provisioning, case import, sequential run, ParaView launch, two bundled tutorials | No marketplace, no installer polish, no second platform |
| **v1.0** | Public | Both platforms, preprocessor, solver monitor, postprocessor, **turbulence advisor and y⁺ audit (§6.9.1)**, bundled content library, original quick-start docs, installers, notarised macOS build | **Sequential runs only. No cloud registry. No compiled extensions. No GCI or validation module.** |
| **v1.1** | Public | Parallel runs (single machine), **mesh refinement study with GCI (§6.9.2)**, **experimental validation (§6.9.3)**, cloud content registry (static host), course packs, run and V&V reports, offline lab bundle | No cluster submission |
| **v2.0** | Public | Compiled extensions with signing, cluster/scheduler submission, plugin API | — |

### 2.2 Non-goals (permanent)

- **NG1** Geometry creation or interactive CAD. BuildFOAM configures and runs `blockMesh`, `snappyHexMesh` and imports third-party meshes; it does not draw geometry.
- **NG2** Cloud or remote compute in v1.x. Runs are local.
- **NG3** Replacing ParaView. BuildFOAM launches it.
- **NG4** A native Linux desktop build. Linux users have a working CLI and package manager; the value proposition does not apply. *(Reconsider only if requested by ≥ 3 institutional users.)*
- **NG5** Supporting both the ESI (`openfoam.com`, `vYYMM`) and Foundation (`openfoam.org`, `v13`, `v14`…) lineages simultaneously in v1.x. **v1.x targets the ESI lineage only** — the dictionary naming divergence doubles the schema surface. The version manifest (§3.4) is designed so Foundation support is additive later.

### 2.3 Out of scope for v1.0, explicitly

Mesh quality visualisation beyond `checkMesh` text output; chemistry/combustion setup wizards; multiphase setup wizards beyond `interFoam` template; optimisation loops; scripting/macro recording; multi-case parameter sweeps.

---

## 3. Platform and runtime strategy

### 3.1 Supported platforms

| Platform | Minimum | Notes |
|---|---|---|
| Windows | Windows 11 22H2 or later | x86-64. Virtualization must be enabled in firmware. ARM64 Windows: not supported in v1.x. |
| Windows 10 22H2 | **Best-effort until 30 June 2027** (DEC-17) | Windows 10 reached end of support on 14 October 2025. Student hardware lags, so BuildFOAM runs there and the acceptance suite covers it, but no defect specific to Windows 10 blocks a release, and support sunsets on the stated date. |
| macOS | macOS 14 Sonoma or later, **Apple silicon** | Intel Macs: degraded path only (see §3.3). |

**Minimum system requirements** (published, and checked by the wizard):

| Resource | Minimum | Recommended |
|---|---|---|
| RAM | 8 GB | 16 GB |
| Free disk | 25 GB (WSL distro + OpenFOAM + ParaView + cases) | 60 GB |
| CPU | 4 cores | 8+ cores |
| GPU | Any OpenGL 3.3 capable (ParaView) | Discrete GPU for large cases |

### 3.2 Windows runtime

| Component | Approach |
|---|---|
| Linux runtime | **WSL2**, provisioned by the wizard. Preferred distro: a **dedicated distribution named `BuildFOAM`** created by importing a base Ubuntu LTS rootfs (`wsl --import`), *not* the user's existing default Ubuntu. |
| OpenFOAM | ESI Debian/Ubuntu packages from the official apt repository, installed inside the BuildFOAM distro. GPG-verified, upgradable via `apt`. |
| ParaView | Native **Windows** ParaView (detect existing → download → offline bundle). Runs Windows-side, reading the case over `\\wsl.localhost\`. |
| Command bridge | `wsl.exe -d BuildFOAM -e /bin/bash -lc "source <bashrc> && <cmd>"`, wrapped in a `RuntimeSession` object that owns the environment. |
| Case storage (default) | **Inside the BuildFOAM distro on ext4**: `/home/<user>/cases`. Surfaced in Windows Explorer as `\\wsl.localhost\BuildFOAM\home\<user>\cases`. |
| Case storage (opt-in) | A Windows-side folder, mapped to `/mnt/<drive>/...`. **Requires an explicit user choice and shows a persistent performance warning.** |

**Why a dedicated distro (DEC-12).** Importing a private distro rather than adopting the user's Ubuntu means: no collision with the user's existing toolchain; a deterministic environment for support ("what OpenFOAM version?" has one answer); a self-contained uninstall (`wsl --unregister BuildFOAM`); and no risk of BuildFOAM's apt operations breaking a user's development setup. Cost: ~2 GB extra disk and a slightly slower first-run download.

> ⚠ **Consequence that must be handled, not assumed away.** Default cases live on the distro's ext4 filesystem, which is inside the distro's VHDX. `wsl --unregister` therefore **deletes the user's cases along with the runtime**. Uninstall must never do that silently: FR-R9 requires that cases are exported to a Windows-side folder (or the user explicitly declines) *before* the distro is unregistered, and FR-A6 defaults that choice to keep-and-export. This is the price of DEC-12 and DEC-05 together.

**Why not `/mnt/c` by default (DEC-05).** Cross-OS file access in WSL2 traverses a 9p translation layer that is substantially slower than ext4 for small-file operations — Microsoft's documentation directs users to keep files on the Linux filesystem when working with Linux tools, and community benchmarking (microsoft/WSL issue #4515) puts the penalty at roughly an order of magnitude for many-small-file workloads. Microsoft publishes no magnitude of its own; treat the 10× figure as indicative, not official. An OpenFOAM write interval creates one file per field per processor, which is precisely that workload. Secondary defects on `/mnt/c`: no POSIX permissions or symlinks (breaking the `0.orig` link pattern used across the tutorial suite), NTFS case-insensitivity colliding with `U` vs `u`, and no `inotify` events (forcing the log tail to poll).

**Acknowledged tension: ParaView reads back over the same bridge.** Windows-side ParaView opens the case via `\\wsl.localhost\`, i.e. the 9p path DEC-05 avoids for writes. This is accepted for v1.0 on the grounds that the read profile differs — ParaView performs a bounded, mostly sequential bulk load once per session, whereas the solver performs sustained small-file writes throughout a run. It is not free: expect noticeably slower first loads on large transient cases. If measurement at M6 shows load times beyond ~30 s for a corpus case, the contingency is a Linux-side `pvserver` inside the distro with the Windows ParaView client connecting to it over the WSL loopback. Specified here so it is a planned fallback rather than a discovery.

**Elevation.** `wsl --install` and the Virtual Machine Platform feature require administrator rights and typically a reboot. BuildFOAM requests elevation **once**, for the runtime feature enablement only (FR-R3), and must present a clean "you need to reboot, we will resume automatically" path (§9, E-R03).

### 3.3 macOS runtime

| Component | Approach |
|---|---|
| OpenFOAM (primary) | The **`gerlero/openfoam` Homebrew tap** — `brew install gerlero/openfoam/openfoam@<version>` — which packages native OpenFOAM.app builds. Homebrew itself is installed by the wizard if absent (see the elevation note below). |
| OpenFOAM (fallback) | **Docker Desktop + the official OpenFOAM image**, offered when the tap is unavailable, on Intel hardware, or when Homebrew installation fails. |
| ParaView | Native macOS ParaView (detect → download → offline bundle). |
| Command bridge | Direct `subprocess` with the OpenFOAM environment sourced, via the same `RuntimeSession` abstraction as Windows. |
| Case storage | `~/BuildFOAM/cases` (native APFS; no bridge required). |

**Known constraints, to be surfaced in the wizard, not discovered by the user:**

- The tap requires **macOS 14 Sonoma or later**.
- **Intel Macs** are limited to older releases (the tap's Intel support ends at an OpenFOAM v2506-era build). On Intel hardware BuildFOAM offers the Docker path by default and marks the tap path as unsupported.
- The tap is a **community-maintained, single-maintainer project**. See RISK-02 for the mitigation.
- **Homebrew installation is not silent.** On Apple silicon Homebrew's default prefix is `/opt/homebrew`, and its installer requires an interactive administrator password. A GUI wizard cannot satisfy a TTY `sudo` prompt. This is a real hole in the zero-terminal promise and is closed as follows, in order: (1) if Homebrew is already present, use it and never prompt; (2) if absent, request the administrator password through the native macOS authorisation dialog (`Authorization Services` / an `osascript` privileged prompt) and drive the installer non-interactively — the user sees a system password dialog, not a terminal; (3) if that fails, fall back to the Docker path, which needs no `/opt` write. **Requirement FR-R11** covers this and is a v1.0 MUST.

### 3.4 Version support policy (replaces all hard-coded version references)

BuildFOAM ships a **`runtime-manifest.json`** describing every OpenFOAM release it knows how to provision and drive. No OpenFOAM version number appears anywhere in application code.

```jsonc
{
  "schema": 1,
  "lineage": "esi",
  "default": "v2606",
  "minimum_supported": "v2506",
  "releases": {
    "v2606": {
      "released": "2026-06-26",
      "windows": { "apt_package": "openfoam2606-default",
                   "bashrc": "/usr/lib/openfoam/openfoam2606/etc/bashrc" },
      "macos":   { "brew_formula": "gerlero/openfoam/openfoam@2606",
                   "min_macos": "14.0", "arch": ["arm64"] },
      "dictionaries": {                      // ESI lineage names
        "transport": "transportProperties",  // Foundation v11+ calls this physicalProperties
        "turbulence": "turbulenceProperties" // Foundation v11+ calls this momentumTransport
      }
    }
  }
}
```

- **Cadence.** ESI releases twice yearly on a `vYYMM` scheme (…, v2506, v2512, **v2606**, v2612, …). The current release at the time of writing is **v2606, released 26 June 2026**.
- **Support window.** BuildFOAM supports the current release and the previous two — at the time of writing v2606, v2512 and v2506, i.e. a rolling 12-month window.
- **Manifest updates** ship independently of the application, over the same channel as the content catalog, so a new OpenFOAM release is supported without an app update.
- The `dictionaries` block absorbs naming divergence between releases and, later, between lineages (DEC-15). Every schema lookup in `CaseService` goes through it — no dictionary filename is ever a literal in code.

### 3.5 Case format

Cases are ordinary OpenFOAM case trees. BuildFOAM adds exactly one non-standard file, `.buildfoam/case.json` (§5.2), which is **ignored by OpenFOAM and safe to delete** — deleting it degrades BuildFOAM's UX (lost run history) but never breaks the case. This is the mechanical expression of D4.

---

## 4. Architecture

### 4.1 Layers

```
┌─────────────────────────────────────────────────────────────┐
│  Presentation — PySide6 (Qt 6)                              │
│  Shell · Hub · Preprocessor · Run · Post · Library · Guide  │
└───────────────────────────┬─────────────────────────────────┘
                            │  Qt signals / async task queue
┌───────────────────────────┴─────────────────────────────────┐
│  Application services (pure Python, no Qt imports)          │
│  ┌──────────────┬─────────────┬──────────────┬───────────┐  │
│  │RuntimeManager│ CaseService │ RunController│ Content   │  │
│  │              │             │  ↳Monitor    │  Service  │  │
│  │              │             │   Service    │           │  │
│  ├──────────────┴─────────────┴──────────────┴───────────┤  │
│  │  GuideService        ReportService (v1.1)             │  │
│  └───────┬──────────────┬──────────────┬───────────┬─────┘  │
└──────────┼──────────────┼──────────────┼───────────┼────────┘
           │              │              │           │
┌──────────┴──────┐ ┌─────┴──────┐ ┌─────┴──────┐ ┌──┴───────┐
│ RuntimeSession  │ │ FoamDict   │ │ ProcessHost│ │ Registry │
│ (wsl / native / │ │ (parser +  │ │ (spawn,    │ │ Client   │
│  docker)        │ │  emitter)  │ │  tail,     │ │ (signed) │
└─────────────────┘ └────────────┘ │  signals)  │ └──────────┘
                                   └────────────┘
```

**Rule: the service layer must not import Qt.** It is exercised headlessly by the test suite (§12) and could later back a CLI. This is enforced by a lint rule in CI.

### 4.2 Components

| Component | Responsibility | Key interface |
|---|---|---|
| **RuntimeSession** | Abstracts "run a command in an OpenFOAM environment". Three implementations: `WslSession`, `NativeSession`, `DockerSession`. Owns path translation between host and runtime. | `run(argv, cwd, env) -> Process`, `to_runtime_path(host_path)`, `to_host_path(runtime_path)` |
| **RuntimeManager** | Detect, provision, verify, upgrade and remove the runtime. Emits a `RuntimeStatus` (ready / degraded / missing / broken) with a machine-readable reason. | `detect()`, `provision(plan, progress_cb)`, `verify()`, `remove()` |
| **FoamDict** | Tolerant OpenFOAM dictionary parser and **round-trip-faithful** emitter. Token-stream based, not AST-rebuild. | `parse(text) -> Document`, `Document.set(path, value)`, `Document.render() -> text` |
| **CaseService** | Create / import / validate cases. Schema lookup via the version manifest. Owns `.buildfoam/case.json`. Detects external modification. | `create(template, params)`, `open(path)`, `validate() -> [Finding]` |
| **RunController** | Builds and executes a `RunPlan` (a list of stages). Owns solver lifecycle, monitoring injection, and stop semantics. | `plan(case, options) -> RunPlan`, `start(plan)`, `stop(mode)` |
| **MonitorService** | Reads `postProcessing/**/*.dat` (primary) and the log (fallback); emits time-series to the UI. | `series(name) -> TimeSeries` |
| **ContentService** | Bundled and (v1.1) remote content catalog; verify signature, install, remove, list. | `catalog()`, `install(id)`, `remove(id)` |
| **GuideService** | Renders bundled Markdown with a search index. | `search(query)`, `page(id)` |
| **ReportService** *(v1.1)* | Assembles the run report PDF. | `build(run_id) -> Path` |

### 4.3 The `RunPlan` abstraction (the reason v1.1 is cheap)

Every execution — meshing, solving, post-utility — is expressed as an ordered list of stages, each an argv plus a runtime, working directory and success predicate. Sequential and parallel differ only in the plan's contents.

```python
RunPlan(
  case=<Case>,
  n_procs=1,                        # v1.0 fixed at 1; v1.1 exposes it
  stages=[
    Stage("blockMesh",      argv=["blockMesh"]),
    Stage("checkMesh",      argv=["checkMesh"], fail_on=Severity.ERROR),
    Stage("decomposePar",   argv=["decomposePar"],        when=lambda p: p.n_procs > 1),
    Stage("solve",          argv=["simpleFoam"],          parallel=True, monitored=True),
    Stage("reconstructPar", argv=["reconstructPar"],      when=lambda p: p.n_procs > 1),
  ])
```

`Stage(parallel=True)` is rendered as `mpirun -np N <argv> -parallel` when `n_procs > 1`, and as `<argv>` otherwise. **v1.0 must implement the full stage machinery with `n_procs` fixed at 1.** Hard-coding a serial pipeline is explicitly forbidden (DEC-06).

---

## 5. Data model

### 5.1 What BuildFOAM considers a "case"

A directory containing at minimum `system/controlDict`. On open, BuildFOAM classifies it:

| Class | Detection | Behaviour |
|---|---|---|
| **BuildFOAM case** | `.buildfoam/case.json` present and its `tree_hash` matches | Full UX: run history, form editors, report |
| **Foreign case** | Valid case tree, no `.buildfoam/` | Full UX; `.buildfoam/case.json` created on first write, with consent |
| **Externally modified** | `.buildfoam/` present, `tree_hash` mismatch | Banner: "This case changed outside BuildFOAM." Offers Reload / Diff / Keep-mine. Never silently overwrites. |
| **Not a case** | No `system/controlDict` | Rejected with a specific message (E-C01) |

### 5.2 `.buildfoam/case.json`

```jsonc
{
  "schema": 1,
  "created_by": "BuildFOAM 1.0.0",
  "created_at": "2026-08-10T09:14:22+08:00",
  "template": "incompressible/simpleFoam/pitzDaily",
  "openfoam": { "lineage": "esi", "version": "v2606" },
  "tree_hash": "sha256:…",              // over dictionary files, excludes time dirs
  "runs": [
    { "id": "r-0001", "started": "…", "finished": "…", "exit": 0,
      "plan": ["blockMesh","checkMesh","simpleFoam"],
      "n_procs": 1, "wall_seconds": 412,
      "final_time": "1000", "converged": true,
      "log_dir": ".buildfoam/logs/r-0001" }
  ],
  "ui": { "last_view": "solver", "pinned_monitors": ["Ux","p"] }
}
```

**Invariant (FR-C7):** deleting `.buildfoam/` must leave a case that runs correctly from the command line. Enforced by an automated test.

### 5.3 Application state

| Data | Location (Windows) | Location (macOS) |
|---|---|---|
| Configuration | `%APPDATA%\BuildFOAM\config.json` | `~/Library/Application Support/BuildFOAM/config.json` |
| Runtime manifest cache | `%LOCALAPPDATA%\BuildFOAM\manifest\` | `~/Library/Application Support/BuildFOAM/manifest/` |
| Content library | Inside the runtime: `$WM_PROJECT_USER_DIR/buildfoam/content` | `~/BuildFOAM/content` |
| Application logs | `%LOCALAPPDATA%\BuildFOAM\logs\` | `~/Library/Logs/BuildFOAM/` |
| Downloads cache | `%LOCALAPPDATA%\BuildFOAM\cache\` | `~/Library/Caches/BuildFOAM/` |
| Cases (default) | `\\wsl.localhost\BuildFOAM\home\<user>\cases` | `~/BuildFOAM/cases` |

**Content installs into the runtime, not the host home directory** — on Windows, host-side content would be executed/read across the slow bridge and, for future compiled extensions, would not be on `$WM_PROJECT_USER_DIR` at all.

### 5.4 The dictionary schema layer

Form editors are driven by declarative schema files, not hand-written widgets:

```jsonc
// schemas/v2606/controlDict.json
{ "file": "system/controlDict",
  "fields": [
    { "key": "application",  "type": "enum",  "source": "solvers",  "required": true },
    { "key": "endTime",      "type": "scalar","min": 0, "required": true,
      "depends": { "stopAt": "endTime" } },
    { "key": "writeInterval","type": "scalar","min": 0, "required": true },
    { "key": "deltaT",       "type": "scalar","min": 0, "required": true },
    { "key": "writeControl", "type": "enum",
      "values": ["timeStep","runTime","adjustableRunTime","cpuTime","clockTime"] }
  ]}
```

Adding support for a new OpenFOAM version is therefore predominantly a data change, not a code change. Any key present in the file but absent from the schema is preserved untouched and shown in the raw-text tab (FR-P6).

---

## 6. Functional requirements

Each requirement has an ID, a priority (**MUST** for v1.0 / **SHOULD** / **v1.1**), and a testable acceptance criterion.

### 6.1 Runtime (FR-R)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-R1 | Detect an existing usable OpenFOAM installation before proposing to install anything. | MUST | On a machine with OpenFOAM already present (WSL or brew tap), the wizard reports "detected v\<X\>" and offers Adopt, with no download. |
| FR-R2 | Report a machine-readable `RuntimeStatus` with a specific reason code at all times. | MUST | Every code in §9 table R is reachable and shown in the status footer. |
| FR-R3 | Provision the runtime with at most one elevation prompt, and survive the reboot it may require. | MUST | On a clean Windows 11 VM with WSL absent, the wizard completes across one reboot with no terminal use and no second elevation. |
| FR-R4 | Install OpenFOAM from the strongest verification available on each platform, and disclose which was used. | MUST | Windows: ESI's apt repository, **GPG-signed by the publisher** (authenticity). macOS: the Homebrew tap, which provides a **sha256 recorded in a third-party formula** (integrity only — it does not establish authenticity from OpenCFD; see RISK-02). No plain tarball fetch appears in any code path, and the Setup view names the verification level actually in force. |
| FR-R5 | Verify the runtime by executing a canary command and parsing its output. | MUST | `foamVersion`/`blockMesh -help` returns the expected version string; a corrupted install is reported as `broken`, not `ready`. |
| FR-R6 | Support switching between installed OpenFOAM versions and installing an additional version side-by-side. | SHOULD | Two versions installed; a case pinned to each runs correctly. |
| FR-R7 | Support an unattended/silent provisioning mode driven by a config file. | MUST (for §14) | `BuildFOAM-Setup.exe /S /CONFIG=lab.json` completes with no UI on a managed image. |
| FR-R8 | Adopt an externally pre-provisioned runtime (lab image) without attempting installation. | MUST | With `lab.json` specifying an existing distro and bashrc path, first launch goes straight to `ready`. |
| FR-R9 | Fully remove the runtime on request, reporting reclaimed disk, **after** user cases have been exported per FR-R12. | MUST | Uninstall removes the BuildFOAM distro / brew formula / ParaView / content and states the byte count freed; no user case is lost, verified by checksum comparison before and after. |
| FR-R10 | Provide a Docker-based runtime as fallback on macOS. | SHOULD | On an Intel Mac, the wizard offers and completes the Docker path. |
| FR-R11 | Install Homebrew without a terminal, using the native macOS authorisation dialog, and fall back to Docker if authorisation is refused or fails. | MUST | On a clean macOS 15 machine with no Homebrew, the wizard completes with the user seeing only a system password dialog; refusing it routes to the Docker path rather than dead-ending. |
| FR-R12 | Before removing a runtime that holds user cases, export those cases to a host-side folder (or obtain an explicit decline) and verify the copy before deletion. | MUST | Uninstall on Windows with 3 cases in the distro writes all 3 to the chosen Windows folder, verifies checksums, and only then unregisters. Declining requires typing a confirmation. |

### 6.2 Case management (FR-C)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-C1 | Create a case from a template (name, location, solver family, turbulence model). | MUST | Generated case passes `checkMesh` and runs to `endTime` unmodified. |
| FR-C2 | Import an existing case directory. | MUST | Any tutorial from the OpenFOAM distribution opens without error. |
| FR-C3 | Validate a case and report findings with severity, file, line, and a suggested fix. | MUST | A case with a missing `boundaryField` entry produces a finding naming the patch and the field, with a one-click fix offer. |
| FR-C4 | Detect external modification and never silently overwrite. | MUST | Editing `controlDict` in a text editor while BuildFOAM is open triggers the banner in §5.1 on next focus. |
| FR-C5 | Clean a case back to its initial state: remove written time directories, `processor*`, `postProcessing`, logs, **and the GUI-owned function-object fence written by FR-S3**. | MUST | After clean, the case tree is byte-identical to the post-import state except for `.buildfoam/`. Tested on cases that have been run at least once, so the fence removal is actually exercised. |
| FR-C6 | Duplicate ("Save As") a case, rewriting no absolute paths. | MUST | Duplicated case runs correctly from its new location. |
| FR-C7 | Deleting `.buildfoam/` leaves a fully valid case. | MUST | Automated: for every bundled template, delete `.buildfoam/`, run from a bare shell, exit code 0. |
| FR-C8 | Warn when the case directory is on a network/roaming location or a slow bridge. | MUST | A case under `/mnt/c` or a UNC home shows a persistent, dismissible performance warning. |

### 6.3 Preprocessing (FR-P)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-P1 | Form editors for `system/controlDict`, `system/fvSchemes`, `system/fvSolution`, and the version-appropriate transport and turbulence dictionaries. | MUST | Each schema-covered key is editable, validated on entry, and written correctly. |
| FR-P2 | Form editor for `system/blockMeshDict` (vertices, blocks, grading, patches) with a live 2D/3D wireframe preview. | SHOULD | Editing a vertex updates the preview within 200 ms; generated mesh matches the preview topology. |
| FR-P3 | Configure and run `snappyHexMeshDict` with STL import; surface refinement levels editable. | SHOULD | An imported STL meshes successfully with default refinement on the bundled example. |
| FR-P4 | **Boundary condition editor** built on the patch list from `constant/polyMesh/boundary`, presenting each field's `boundaryField` entries as a patch × field matrix. | MUST | Every patch is shown for every field; a missing or type-incompatible entry is flagged before the run; `cyclic`/`empty` patch constraints are enforced. |
| FR-P5 | Run `blockMesh`, `snappyHexMesh`, `checkMesh`, `surfaceFeatureExtract`, `renumberMesh`, `transformPoints` with a live output panel. | MUST | Each utility runs, streams output, and reports a parsed pass/fail. |
| FR-P6 | Raw-text editing tab for every dictionary, with OpenFOAM syntax highlighting, bracket matching, and validate-on-save. | MUST | Any dictionary can be hand-edited in-app; invalid syntax blocks the save with a line-accurate error. |
| FR-P7 | **Round-trip fidelity**: writing a dictionary through a form modifies only the edited entry; comments, ordering, whitespace and preprocessor directives (`#include`, `#calc`, `#codeStream`, macro expansion `$var`, regex keys) are preserved byte-for-byte elsewhere. | MUST | Automated (§12.2) over the entire bundled tutorial corpus. |
| FR-P8 | Launch ParaView for visual mesh inspection via the `<case>/<case>.foam` stub (the same mechanism as FR-V2), with the time set to the initial state so only the mesh is shown. | MUST | Opens with the mesh loaded and no manual reader selection, on a case that has no written time directories yet. |
| FR-P9 | Surface the `checkMesh` quality summary (non-orthogonality, skewness, aspect ratio) as a pass/warn/fail panel, not raw text. | SHOULD | Thresholds configurable; the panel matches `checkMesh` output on the bundled corpus. |

### 6.4 Running (FR-S)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-S1 | Compose and execute a `RunPlan` covering mesh → solve → (v1.1) reconstruct. | MUST | Plan is displayed before launch; each stage's status is visible during the run. |
| FR-S2 | Stream the solver log to the UI in real time, with search and a jump-to-error control. | MUST | Log lines appear ≤ 500 ms after emission at up to 5 000 lines/s without UI stall. |
| FR-S3 | **Inject a `solverInfo` function object** into a GUI-owned, comment-fenced block in `controlDict`, and plot residuals from `postProcessing/**/*.dat`. Fall back to log parsing when the fence is absent or the user has disabled injection. | MUST | Residual plots are identical between injected and fallback modes on the bundled corpus; removing the fence leaves a valid `controlDict`. |
| FR-S4 | Plot arbitrary monitored quantities (residuals, continuity errors, forces, probes, `fieldMinMax`) with per-series toggles, log scale, and CSV export. | MUST | A `forceCoeffs` function object in a bundled case produces a live Cd/Cl plot. |
| FR-S5 | **Three-level stop:** *Stop & Write* — default; *Stop Now* (SIGTERM); *Force Kill* (SIGKILL). Stop & Write is implemented by the **`abort` function object** (ESI; `stopAtFile` in the Foundation lineage), installed into the same GUI-owned fence as FR-S3 at launch and triggered by creating its trigger file with `action writeNow`. Falls back to rewriting `controlDict` with `stopAt writeNow` (relying on `runTimeModifiable`) when the fence is absent. | MUST | Stop & Write yields a complete, loadable final time directory in every bundled corpus case, in both the function-object and fallback paths. SIGTERM is never the default. Note that the `abort` FO is **not** enabled by OpenFOAM automatically and its own default action is `nextWrite`, so the FO must be installed with `writeNow` explicitly. |
| FR-S6 | Detect divergence and non-convergence and surface a diagnosis, not a stack trace. | MUST | An induced Courant-number blow-up produces "Solution diverging — Courant number exceeded N at t=…" with a link to the relevant guide page. |
| FR-S7 | Persist run history with logs, plan, wall time and exit status in `.buildfoam/`. | MUST | History survives app restart; logs are retrievable per run. |
| FR-S8 | Resume/restart from the latest time directory (`startFrom latestTime`). | SHOULD | A stopped run resumes and continues the residual series without a discontinuity. |
| FR-S9 | Parallel execution: `decomposePar` → `mpirun -np N` → `reconstructPar`, with `nProcs` validated against `decomposeParDict`, `scotch`/`simple` methods. | **v1.1** | `-np` and `numberOfSubdomains` mismatch is caught before launch; reconstruction completes; ParaView opens the reconstructed result. |
| FR-S10 | Never leave orphaned processes: killing the app terminates the process group. | MUST | Force-quitting BuildFOAM mid-run leaves no `simpleFoam`/`mpirun` process, verified on both platforms. |

### 6.5 Postprocessing (FR-V)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-V1 | Locate ParaView (bundled path → registry/Spotlight → user-specified), or offer to download it. | MUST | On a machine with ParaView already installed, no download is offered. |
| FR-V2 | Create/refresh the `<case>/<case>.foam` stub and launch ParaView on it. | MUST | ParaView opens with fields loaded and the correct time steps, on both platforms, without manual reader selection. |
| FR-V3 | On Windows, translate the WSL case path to a `\\wsl.localhost\` UNC path for the Windows-side ParaView. | MUST | Works with spaces and non-ASCII characters in the path. |
| FR-V4 | Offer *Reconstructed* vs *Decomposed* case type when `processor*` directories are present. | **v1.1** | Both open correctly. |
| FR-V5 | Run standard post utilities from the UI (`postProcess -func`, `foamToVTK`, `sample`). | SHOULD | Each streams output and writes to `postProcessing/`. |
| FR-V6 | Generate a **run report** PDF (mesh statistics, effective dictionaries, residual plot, monitored final values, wall time, environment fingerprint, case checksum). | **v1.1** | Report opens in any PDF reader; checksum matches an independent recomputation. |

### 6.6 Content library (FR-L)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-L1 | Browse a bundled catalog of tutorials and example cases by category, solver and OpenFOAM version compatibility. | MUST | Catalog is searchable and filterable; incompatible items are marked, not hidden. |
| FR-L2 | Install a content item into the user's case area in one action. | MUST | Installed case opens and runs without further configuration. |
| FR-L3 | Content packages are **data only** in v1.0 (cases, meshes, worksheets, geometry). No compiled artefacts, no scripts executed at install time. | MUST | Installer rejects any package containing an executable bit or a `build/` recipe. |
| FR-L4 | Verify package integrity (sha256) and catalog authenticity (detached ed25519 signature over the catalog, public key compiled into the app). | MUST | A tampered catalog or payload is rejected with a clear message and no install. |
| FR-L5 | Sideload from a local `.zip` with an explicit, non-default-accept trust dialog. | MUST | Dialog names the publisher (or "unknown"), lists contents, and requires an affirmative click. |
| FR-L6 | Remote catalog over HTTPS with offline fallback to the bundled catalog. | **v1.1** | With the network unavailable, the library still lists bundled items and states that it is offline. |
| FR-L7 | **Course packs**: a signed bundle of cases + worksheet + expected results + manifest, importable in one action. | **v1.1** | A pack authored by a lecturer imports on a student machine and the worksheet renders in the Guide view. |
| FR-L8 | Compiled extensions (solvers/libraries) built in-runtime via `wmake` into `$WM_PROJECT_USER_DIR`, first-party signed only. | **v2.0** | Build streams to a log; failure is reported with the compiler error, and a failed build leaves no partial install. |

### 6.7 Guide (FR-G)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-G1 | Render bundled Markdown documentation with a table of contents and full-text search, fully offline. | MUST | Search returns results with no network. |
| FR-G2 | Context links: every error message and every form field links to the relevant guide section. | MUST | 100% of error codes in §9 have a target page. |
| FR-G3 | Original content: a ~10-page quick start, one page per bundled tutorial, and a troubleshooting index. Upstream documentation is deep-linked, not rehosted. | MUST | No upstream document is redistributed. |
| FR-G4 | Render a course pack's worksheet alongside the bundled guide. | **v1.1** | Worksheet appears under a "Course" section. |

### 6.8 Application shell (FR-A)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-A1 | Hub view with large launch targets: New Case, Open Case, Library, Guide, Case Folder, Settings; plus recent cases. | MUST | Every target reachable in one click from launch. |
| FR-A2 | Persistent status footer: OpenFOAM version, runtime status, active case, run state. | MUST | Footer reflects state changes within 1 s. |
| FR-A3 | Open the case folder in Explorer/Finder, correctly resolving the WSL UNC path on Windows. | MUST | Opens the right folder on both platforms. |
| FR-A4 | **Diagnostics bundle**: one click exports a zip of app logs, environment report, runtime status and (with consent) the active case's dictionaries. | MUST | Bundle is ≤ 10 MB by default and contains no credentials; contents are listed before export. |
| FR-A5 | Update check and in-app update with rollback to the previous version. | MUST | A failed update restores the prior version and reports the failure. |
| FR-A6 | Uninstall flow with explicit choices for runtime, ParaView, content and user cases (cases default to **keep**). | MUST | Each component's disk usage is shown before the choice. |
| FR-A7 | Crash handler: on an unhandled exception, offer to save a diagnostics bundle before exit; never lose unsaved dictionary edits silently. | MUST | Induced crash produces a bundle and preserves editor buffers. |

### 6.9 Verification and validation (FR-VV)

This is the **V&V module**: three capabilities that together take a user from "I ran a simulation" to "I can defend this result in a journal or a viva." It is the product's strongest differentiator (D5) and the section most directly aligned with what P2 teaches and P3 must document.

The three parts are deliberately sequenced by dependency: the **turbulence advisor** shapes the case before it runs, the **mesh refinement study** quantifies numerical error after it runs, and **experimental validation** compares the converged answer to reality. Only the last two are new machinery; the first is a setup aid.

---

#### 6.9.1 Turbulence model advisor (FR-VVT) — v1.0

Model choice is the single highest-leverage decision a novice makes and the one they most often get wrong — usually by pairing a low-Reynolds model with a wall-function mesh, or vice versa. The advisor makes the coupling between *model*, *wall treatment* and *mesh* explicit, and refuses to let the three disagree silently.

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-VVT1 | Guided model selection from a small set of physics questions: internal/external, expected separation, adverse pressure gradient, swirl or streamline curvature, transition importance, buoyancy, steady/unsteady, compressibility, and available compute. | MUST | Answering the questionnaire for each bundled tutorial recommends the model that tutorial actually uses, or explains why an alternative is defensible. |
| FR-VVT2 | Present recommendations as a **ranked shortlist with reasons and trade-offs**, never a single silent answer. Each entry states what the model is good at, where it is known to fail, and its relative cost. | MUST | At least two candidates with stated trade-offs are shown for every questionnaire path. |
| FR-VVT3 | Cover the standard OpenFOAM RAS set (`kEpsilon`, `realizableKE`, `RNGkEpsilon`, `kOmega`, `kOmegaSST`, `kOmegaSSTLM`, `SpalartAllmaras`, `LaunderSharmaKE`, `v2f`, `LRR`, `SSG`), the LES set (`Smagorinsky`, `WALE`, `kEqn`, `dynamicKEqn`), and hybrid RANS-LES (`SpalartAllmarasDDES`, `SpalartAllmarasIDDES`, `kOmegaSSTDES`). Model availability is read from the version manifest, not hard-coded. | MUST | Every listed model can be selected and produces a case that runs. Selecting a model absent from the installed version is impossible, not merely warned about. |
| FR-VVT4 | **Wall-treatment coupling.** Selecting a model forces an explicit wall-treatment choice — wall functions (target y⁺ 30–300, log layer) or resolved near-wall (target y⁺ ≈ 1) — and writes the matching boundary conditions (`nutkWallFunction` / `nutUSpaldingWallFunction` / `kqRWallFunction` / `epsilonWallFunction` / `omegaWallFunction`, or their low-Re counterparts) across all affected fields. | MUST | No combination of model and wall treatment can be saved that produces inconsistent BCs across `0/`. |
| FR-VVT5 | **First-cell-height calculator.** From free-stream velocity, a reference length, fluid properties and a target y⁺, compute the required first-cell height using flat-plate skin-friction correlations, and show the resulting boundary-layer cell count and growth ratio. State the correlation used and that it is an estimate. | MUST | For a flat-plate case at a known Reynolds number, the computed height brings the achieved y⁺ within a factor of two of the target — and the UI says that a factor of two is the expected accuracy. |
| FR-VVT6 | **Turbulence initialisation calculator.** Derive inlet `k`, `epsilon`, `omega` and `nuTilda` from turbulence intensity and length scale (or hydraulic diameter), showing each formula. | MUST | Values match hand calculation for the bundled worked example. |
| FR-VVT7 | **Post-run y⁺ audit.** After a run, execute the `yPlus` function object and report min / max / mean per wall patch against the target band, with a pass/warn/fail verdict per patch. | MUST | A case meshed for wall functions but run with a low-Re model is flagged, naming the offending patches and the achieved range. |
| FR-VVT8 | Warn on the classic mismatches: y⁺ landing in the buffer layer (5 < y⁺ < 30), a low-Re model on a y⁺ ≫ 1 mesh, wall functions on a y⁺ < 5 mesh, and `kEpsilon` used with strong adverse pressure gradient or separation. Each warning links to a guide page. | MUST | Each condition is reachable in the corpus and produces its specific warning, not a generic one. |
| FR-VVT9 | Changing the model rewrites only the turbulence dictionary and the affected `boundaryField` entries, preserving everything else byte-for-byte (FR-P7). | MUST | Round-trip test passes after a model change. |

---

#### 6.9.2 Mesh refinement study — Richardson extrapolation and GCI (FR-VVM) — v1.1

Implements the **Celik et al. (2008) five-step procedure** adopted as the *Journal of Fluids Engineering* editorial policy, which is what reviewers in this field actually ask for. The output is a table a user can paste into a paper.

**The procedure, as specified for implementation.** Given three solutions φ₁, φ₂, φ₃ on systematically refined meshes with representative sizes h₁ < h₂ < h₃:

1. **Representative cell size** — `h = [ (1/N) Σᵢ ΔVᵢ ]^(1/3)` in 3D, `[ (1/N) Σᵢ ΔAᵢ ]^(1/2)` in 2D, computed from the actual mesh, not from a nominal cell count.
2. **Refinement ratios** — `r₂₁ = h₂/h₁`, `r₃₂ = h₃/h₂`. **r > 1.3 is the recommended minimum**; below it, discretization error cannot be separated cleanly from other error sources, and the app must warn.
3. **Apparent order** — solved by fixed-point iteration:
   `p = (1/ln r₂₁) · | ln|ε₃₂/ε₂₁| + q(p) |`
   `q(p) = ln[ (r₂₁ᵖ − s) / (r₃₂ᵖ − s) ]`,  `s = sgn(ε₃₂/ε₂₁)`
   where `ε₂₁ = φ₂ − φ₁`, `ε₃₂ = φ₃ − φ₂`. For equal refinement ratios `q(p) = 0` and the expression collapses to `p = ln(ε₃₂/ε₂₁)/ln r`.
4. **Extrapolated value** — `φ²¹_ext = (r₂₁ᵖ φ₁ − φ₂) / (r₂₁ᵖ − 1)`.
5. **Error and uncertainty** —
   approximate relative error `e²¹_a = |(φ₁ − φ₂)/φ₁|`;
   extrapolated relative error `e²¹_ext = |(φ²¹_ext − φ₁)/φ²¹_ext|`;
   **fine-grid convergence index** `GCI²¹_fine = 1.25 · e²¹_a / (r₂₁ᵖ − 1)`.
   The safety factor is **1.25 for a three-mesh study with a computed p**, and **3.0 for a two-mesh study with an assumed p** — the app must use the right one and say which.

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-VVM1 | Generate a systematically refined **mesh family** of three or more levels from a base case at a chosen refinement ratio (default √2, alternatives 1.3 and 2.0). | v1.1 | For a `blockMesh` case, the three generated meshes have measured h ratios within 2% of the requested r. |
| FR-VVM2 | Support mesh-family generation for: `blockMesh` (scale block subdivisions — the clean case); `snappyHexMesh` (step refinement levels, giving r = 2 per level, with the coarser granularity disclosed); imported meshes (uniform `refineMesh`, r = 2, or **user supplies the three meshes manually**). | v1.1 | Each path produces a valid family or refuses with a specific reason. The manual path accepts any three cases the user nominates. |
| FR-VVM3 | Run the family as one batch job, sequentially or in parallel, with per-mesh progress, and survive a single mesh failing without losing the others. | v1.1 | A deliberately broken middle mesh yields results for the other two and a clear report of what failed. |
| FR-VVM4 | Define the **quantity of interest** (QoI) — an integral value (drag/lift coefficient, pressure drop, mass flow, Nusselt number, mean outlet temperature), a point value from a probe, or a user-supplied function-object output. Multiple QoIs per study. | v1.1 | Each QoI type is extractable from the corpus and produces a full GCI table. |
| FR-VVM5 | Compute and display h, r, φ, p, φ_ext, e_a, e_ext and GCI for each QoI, formatted as the **standard JFE-style table**, exportable to CSV, LaTeX and the run report. | v1.1 | Output matches the published worked examples in §12.6 to within display precision. |
| FR-VVM6 | **Classify convergence** from `R = ε₂₁/ε₃₂`: monotonic (0 < R < 1), oscillatory (−1 < R < 0), divergent (\|R\| > 1). Report the class prominently and, for oscillatory or divergent behaviour, state plainly that the GCI is unreliable and why. | v1.1 | Each class is reachable with a constructed fixture and produces its correct label and caveat. |
| FR-VVM7 | Warn when the apparent order p departs substantially from the scheme's theoretical order (typically 2 for the default second-order schemes), when p exceeds a plausible bound, or when r < 1.3. Explain what each condition usually means. | v1.1 | Each warning fires on a constructed fixture. |
| FR-VVM8 | Plot φ against hᵖ with the extrapolated value marked, showing the approach to the asymptotic range. | v1.1 | Plot renders and exports at publication resolution. |
| FR-VVM9 | **Never present a GCI number without its caveats.** Output always carries the convergence class, the refinement ratios achieved, the apparent order, and a statement that the estimate assumes solutions in the asymptotic range on geometrically similar, systematically refined meshes with iterative convergence far below the discretization error. | MUST (whenever the module ships) | No export path can produce a bare GCI figure. |
| FR-VVM10 | Require and display evidence that **iterative convergence** is not contaminating the study — final residuals per mesh, shown alongside the GCI, with a warning when they are not at least two orders below the estimated discretization error. | v1.1 | A deliberately under-converged mesh triggers the warning. |

> **Why FR-VVM9 and FR-VVM10 are not optional.** A GCI number is trivial to compute and easy to compute meaninglessly. The most common failure in the published literature is a GCI reported from three meshes that were never in the asymptotic range, or where iterative error swamped discretization error. A tool that emits the number without the diagnosis would industrialise that mistake across every student who uses it. The caveats are the product, not the decoration.

---

#### 6.9.3 Validation against experiment (FR-VVE) — v1.1

Framed on **ASME V&V 20**, which distinguishes *verification* (are we solving the equations right — §6.9.2) from *validation* (are we solving the right equations — this section).

The comparison error is `E = S − D`, simulation minus experimental data. The validation uncertainty combines the numerical, input-parameter and experimental contributions, `u_val = √(u_num² + u_input² + u_D²)`, and sets the resolution floor: when `|E| ≤ u_val`, the modelling error is buried in the noise and validation is achieved *at that level* — it does not mean the model is correct. When `|E| ≫ u_val`, E is a useful estimate of the modelling error itself. The GCI from §6.9.2 supplies `u_num`, which is precisely why the two modules belong together.

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-VVE1 | Import experimental data from CSV/TSV with a column-mapping step, units declaration, and an optional per-point uncertainty column. | v1.1 | A messy real-world CSV imports with headers on row 3 and mixed delimiters. |
| FR-VVE2 | **Co-locate** simulation and experiment: sample the solution at the experimental measurement locations via `postProcess -func sets` / `probes` / surface sampling, generating the sampling dictionary automatically from the imported coordinates. | v1.1 | Sampled locations match imported coordinates to within mesh tolerance; points outside the domain are reported, not silently dropped. |
| FR-VVE3 | Overlay plots — simulation line against experimental points with error bars — for profiles, along-path distributions and scalar comparisons. Publication-quality export. | v1.1 | Renders correctly for a velocity profile and a pressure-coefficient distribution. |
| FR-VVE4 | Compute comparison metrics: comparison error E per point, RMSE, MAE, normalised RMSE, maximum absolute deviation, and R² where meaningful. State each definition in the UI. | v1.1 | Metrics match an independent calculation on a fixture dataset. |
| FR-VVE5 | Compute `u_val` from the GCI-derived `u_num`, user-declared input-parameter uncertainty, and imported experimental uncertainty; display `E` against `±u_val` and state the interpretation in words. | v1.1 | For a fixture where \|E\| < u_val the UI states validation is achieved at the u_val level and explicitly does **not** claim the model is correct. |
| FR-VVE6 | Ship a **validation case library**: canonical benchmarks with reference experimental data and the accepted comparison — backward-facing step, flow over a cylinder, turbulent channel flow, flat-plate boundary layer, lid-driven cavity. Each with provenance and citation for its data. | v1.1 | Each case runs, compares, and reproduces its published agreement within the documented tolerance. |
| FR-VVE7 | Export a **V&V report** combining the mesh study (§6.9.2), the turbulence configuration and y⁺ audit (§6.9.1), and the experimental comparison, in the run-report format (FR-V6). | v1.1 | Report contains all three sections and a complete provenance fingerprint. |
| FR-VVE8 | Never assign a pass/fail verdict to a validation comparison. Report E, u_val and the interpretation; the judgement of adequacy belongs to the engineer and depends on the application. | MUST (whenever the module ships) | No UI path displays "validated" as a boolean. |

---

## 7. User interface specification

### 7.1 Shell layout

Original design. Three regions, no borrowed layout:

```
┌────────────────────────────────────────────────────────────────┐
│  BuildFOAM                                            ─  □  ×     │
├──────────┬─────────────────────────────────────────────────────┤
│          │                                                     │
│  ⌂ Hub   │                                                     │
│  ▤ Cases │              Main panel (stacked views)             │
│  ⚙ Setup │                                                     │
│  ▶ Run   │                                                     │
│  ◈ Post  │                                                     │
│  ⧉ Library│                                                    │
│  ? Guide │                                                     │
│          │                                                     │
├──────────┴─────────────────────────────────────────────────────┤
│ ● OpenFOAM v2606 · Runtime ready · pitzDaily · idle            │
└────────────────────────────────────────────────────────────────┘
```

- Left **nav rail**, icon + label, collapsible to icons only.
- **Main panel** is a stack; each nav item maps to one view.
- **Status footer** is always visible and always truthful (FR-A2). Runtime status is a coloured dot: green ready, amber degraded, red missing/broken — clicking it jumps to Setup.

### 7.2 Hub view

Recent cases (name, solver, last run, status) as the primary content — because a returning user's first action is almost always "continue what I was doing". Secondary row of large actions: **New Case**, **Open Case**, **Library**, **Guide**, **Case Folder**. A runtime banner appears only when the runtime is not ready.

### 7.3 Setup wizard (first launch)

| Step | Content | Failure handling |
|---|---|---|
| 1 | Welcome; licence; the OpenCFD non-endorsement notice; opt-in telemetry choice (default **off**) | — |
| 2 | System check: OS version, architecture, RAM, free disk, virtualization enabled, admin availability, network reachability | Any failure produces a specific code from §9 with remediation text; the wizard offers "check again" without restarting |
| 3 | Detect existing runtime → **Adopt** / **Install fresh** / **Advanced (point to existing)** | — |
| 4 | Plan review: exactly what will be installed, where, and how many bytes downloaded and occupied. **Nothing installs before this screen is accepted.** | — |
| 5 | Provision runtime (WSL feature → distro import → apt → OpenFOAM) with per-stage progress, a live log pane (collapsed by default), and a resumable download | Reboot required → save state, register resume, tell the user plainly |
| 6 | ParaView: detected / download / skip for now / point to existing | Skippable; Post view later offers it again |
| 7 | Create the case folder; offer to install the starter content pack | — |
| 8 | Verification run: execute the `cavity` tutorial end-to-end and show the residual plot. **The wizard is not "done" until a real simulation has succeeded.** | Failure produces a diagnostics bundle offer and a specific code |

Step 8 is not decoration. It converts "the installer said OK" into "this machine can actually run CFD", which is the only claim the user cares about, and it moves failures from the middle of a lab session to the setup screen.

### 7.4 Preprocessor view

Left: case file tree (real tree, showing real filenames). Centre: tabbed editors — a **Form** tab and a **Text** tab for the selected dictionary, always both. Right: a live **Validation** panel listing findings with severity, each clickable to the offending line.

The **Boundary Conditions** tab is a matrix: rows = patches from `constant/polyMesh/boundary` (with patch type), columns = fields in `0/`. Each cell shows the BC type; empty cells are errors. Bulk actions ("apply `noSlip` to all `wall` patches for `U`") are provided because that is what the work actually is.

### 7.5 Run view

Top: the `RunPlan` as a horizontal stage strip with per-stage state. Left: log pane with filter and error jump. Right: monitor plots, tabbed by function object, with series toggles and log-scale. Bottom: the three-level stop control, with **Stop & Write** as the default button and the destructive options behind a dropdown.

### 7.6 Post view

ParaView status and launch; case type selector (v1.1); post-utility runner; and (v1.1) **Generate run report**.

### 7.7 V&V view

A dedicated view, because V&V is a workflow rather than a dialog. Three tabs mirroring §6.9:

- **Turbulence** *(v1.0)* — the questionnaire on the left, the ranked shortlist with trade-offs in the centre, and a live panel on the right showing the coupled consequences: chosen wall treatment, target y⁺, required first-cell height, resulting boundary-layer cell count, and the derived inlet `k`/`ε`/`ω`. Every number shows its formula on hover. After a run, the y⁺ audit appears here as a per-patch table with pass/warn/fail against the target band.
- **Mesh study** *(v1.1)* — family generator at the top (base case, refinement ratio, number of levels, generation strategy), the batch run status in the middle, and the GCI table below with the convergence-class banner above it. The banner is the loudest element on the screen when the class is oscillatory or divergent, because that is the case where the number underneath must not be trusted.
- **Validation** *(v1.1)* — imported dataset on the left with its column mapping, the overlay plot in the centre, and the metrics panel on the right showing E, u_val and its three constituents, with the interpretation written out in a sentence rather than left to the reader.

The three tabs share a **provenance strip** naming the case, mesh family, OpenFOAM version and turbulence configuration the displayed numbers came from — because the most common way a V&V table becomes wrong is that it outlives the case it describes.

### 7.8 Library and Guide views

Library: category sidebar, card grid, per-item detail with compatibility badge, size, licence and publisher. Guide: TOC sidebar, content pane, search box; renders the same Markdown pipeline as course-pack worksheets.

### 7.9 Interaction principles

1. **No dead ends.** Every error state offers at least one action.
2. **No hidden work.** Anything that downloads, writes, or takes over five seconds shows progress and is cancellable.
3. **Never trap the user.** Every generated file is visible and hand-editable in-app and outside it.
4. **The status footer never lies.** If the runtime is degraded, it says so even mid-run.
5. **Destructive actions are never the default button.**
6. **No uncertainty figure appears without its caveats.** GCI values, validation metrics and y⁺ verdicts always travel with their convergence class, assumptions and interpretation — in the UI, in exports, and in the report. A number that looks authoritative and is not is worse than no number.

---

## 8. Non-functional requirements

### 8.1 Performance and capacity (NFR-P)

| ID | Requirement | Target |
|---|---|---|
| NFR-P1 | Cold application start to interactive Hub | ≤ 3 s on the reference machine |
| NFR-P2 | Case open (parse + validate) for a 200-file case | ≤ 2 s |
| NFR-P3 | Log tail throughput without UI stall | ≥ 5 000 lines/s |
| NFR-P4 | Monitor plot update latency | ≤ 500 ms from `.dat` write |
| NFR-P5 | Plot point budget (decimated beyond this, full data retained for export) | 50 000 points/series |
| NFR-P6 | Largest supported case (file tree navigation remains responsive) | 100 000 files / 20 GB |
| NFR-P7 | Idle CPU usage | < 1% |
| NFR-P8 | Installer size (without ParaView) | ≤ 250 MB compressed. **This requires active Qt module stripping** — a naive PyInstaller freeze of PySide6 + Qt 6 + a plotting library lands at 150–350 MB *before* compression. Excluding unused Qt modules (WebEngine, Quick3D, Multimedia, Charts, Designer, the translation catalogues) is therefore a build requirement, not an optimisation, and is verified in CI on every tag. |
| NFR-P9 | Total first-run download (runtime + OpenFOAM + ParaView) | ≤ 4 GB, resumable, checksummed |

Reference machine: 4-core x86-64, 8 GB RAM, SATA SSD, Windows 11 22H2.
**Reference network for time-based targets: 50 Mbit/s sustained.** M-2 (≤ 30 min to first result) is stated against this assumption and is not achievable below roughly 25 Mbit/s. BuildFOAM measures throughput during the first download and, when it projects an installation longer than 45 minutes, says so explicitly and offers the offline bundle (§14.2) instead of letting the user discover it by waiting. §14.1's blanket "a 4 GB download is not viable" applies to *lab* conditions — filtered proxies and 40 machines contending for one uplink — not to a home connection.

### 8.2 Reliability (NFR-R)

| ID | Requirement |
|---|---|
| NFR-R1 | All downloads resumable and sha256-verified before use. |
| NFR-R2 | Dictionary writes are atomic (write temp → fsync → rename). A crash mid-write never truncates a case file. |
| NFR-R3 | No user data loss on crash: editor buffers are journalled. |
| NFR-R4 | Runtime provisioning is idempotent and resumable: re-running the wizard after any failure converges to the same state. |
| NFR-R5 | The app functions fully offline once provisioned, except the update check and the remote catalog. |
| NFR-R6 | Termination of the app terminates all child process groups (FR-S10). |

### 8.3 Compatibility and correctness (NFR-C)

| ID | Requirement |
|---|---|
| NFR-C1 | Every file BuildFOAM writes is a valid OpenFOAM dictionary accepted by the target version. |
| NFR-C2 | BuildFOAM never requires its own metadata to be present for a case to run (FR-C7). |
| NFR-C3 | BuildFOAM never silently changes numerical settings. Any modification to `fvSchemes`/`fvSolution`/`controlDict` made on the user's behalf (e.g. function-object injection) is fenced, disclosed, and reversible. |
| NFR-C4 | Unicode and spaces in paths are supported on both platforms, including across the WSL bridge. |

### 8.4 Security (NFR-S)

See §10. Summary: HTTPS-only, signed catalog, no install-time code execution in v1.0, no elevation after setup, no network listeners.

### 8.5 Usability and accessibility (NFR-A)

| ID | Requirement |
|---|---|
| NFR-A1 | Full keyboard navigation; visible focus indicators throughout. |
| NFR-A2 | Text contrast meets WCAG 2.1 AA (4.5:1 body, 3:1 large). Colour is never the sole carrier of meaning — status uses shape + label as well as colour. |
| NFR-A3 | HiDPI/Retina correct at 100–300% scaling; no rasterised UI assets below 2×. |
| NFR-A4 | Light and dark themes, following the OS setting by default. |
| NFR-A5 | All user-visible strings externalised for translation from M1. **English ships in v1.0; Bahasa Melayu in v1.1.** Retrofitting i18n later is expensive — the extraction discipline starts immediately. |
| NFR-A6 | No jargon in error messages without an inline definition or a guide link. |

### 8.6 Maintainability (NFR-M)

| ID | Requirement |
|---|---|
| NFR-M1 | Service layer contains no Qt imports; enforced in CI. |
| NFR-M2 | ≥ 80% line coverage on `FoamDict`, `CaseService`, `RunController`; ≥ 60% overall. |
| NFR-M3 | Version- and lineage-specific knowledge lives only in the manifest and schema files, never in code. Enforced by a CI grep for version literals. |
| NFR-M4 | Structured logging (JSON lines) with a stable event vocabulary, so diagnostics bundles are machine-analysable. |
| NFR-M5 | **The product name appears exactly twice in the source tree**: an `APP_ID` constant (lowercase identifier, used for every path, bundle identifier, distro name, metadata directory, package extension and content namespace) and a `APP_DISPLAY_NAME` string (human-facing, localisable). Enforced by a CI grep. A rename must therefore be a two-line change plus a migration shim that detects the previous `APP_ID` in existing installs and case trees. |

---

## 9. Error taxonomy and failure UX

Every failure has a stable code, a plain-language message, a remediation, and a guide anchor. Codes appear in the UI and in logs so a support conversation can start from a code rather than a screenshot. *(Abridged — the full table is a living appendix.)*

### Runtime (R)

| Code | Condition | User-facing message and remediation |
|---|---|---|
| E-R01 | Virtualization disabled in firmware | "Your computer's virtualization feature is switched off. WSL2 cannot run without it." → link to a guide page with per-vendor BIOS instructions; **Check again** button. |
| E-R02 | No administrator rights | "Installing the Linux runtime needs administrator rights on this computer." → offers the **lab/managed machine** path (FR-R8) and generates a one-page request for IT. |
| E-R03 | Reboot required after enabling WSL | "Windows needs to restart to finish enabling WSL. BuildFOAM will continue automatically after you restart." → **Restart now** / **Later**; state is persisted and resumed. |
| E-R04 | Download blocked (proxy/firewall) | Names the blocked host and offers proxy configuration + the offline bundle. |
| E-R05 | Insufficient disk | States required vs available, and which component can be skipped. |
| E-R06 | apt/Homebrew failure | Shows the last 20 lines of the tool's output, offers retry, and offers a diagnostics bundle. |
| E-R07 | Runtime detected but broken (canary fails) | "OpenFOAM is installed but not working." → **Repair** (reinstall package) / **Reinstall runtime** / diagnostics. |
| E-R08 | macOS: Intel hardware, tap unsupported | Explains the limitation and offers the Docker path. |
| E-R09 | macOS: Gatekeeper/quarantine blocks a downloaded component | Explains and links to the notarised-download page; never instructs the user to disable Gatekeeper. |

### Case (C)

| Code | Condition | Message |
|---|---|---|
| E-C01 | Directory is not a case | "There's no `system/controlDict` here, so this isn't an OpenFOAM case folder." + shows what was found. |
| E-C02 | Dictionary parse error | File, line, column, offending token, and the enclosing dictionary path. |
| E-C03 | Missing `boundaryField` entry | Names the patch and the field; offers to insert a type chosen from those valid for that patch type. |
| E-C04 | Patch/BC type incompatible | Names both and explains the constraint (e.g. "`empty` patches require the `empty` boundary condition"). |
| E-C05 | Case modified outside BuildFOAM | Reload / Diff / Keep mine. |
| E-C06 | Case on a slow or network path | Performance warning with the reason and a **Move to fast storage** action. |
| E-C07 | Version mismatch (case authored for an unsupported release) | Names both versions; offers to open read-only or to install the required version. |

### Run (S)

| Code | Condition | Message |
|---|---|---|
| E-S01 | Mesh generation failed | Parsed `blockMesh`/`snappyHexMesh` error with the offending dictionary entry. |
| E-S02 | `checkMesh` reports errors | Summary table of failed checks with thresholds; **Run anyway** requires confirmation. |
| E-S03 | Solver diverged | "The solution is diverging (Courant number reached N at t=…)." + link to a stability guide page listing the usual causes in order. |
| E-S04 | Floating point exception | Explains that this usually follows divergence or a zero-division in a boundary condition; points at the last written time. |
| E-S05 | Solver binary not found | Names the solver and the runtime searched; offers to check the installed version. |
| E-S06 | Out of memory / OOM-killed | Reports the killed stage and suggests a coarser mesh or (v1.1) parallel decomposition. |
| E-S07 | Disk full mid-run | Stops with `stopAt writeNow` if possible; reports the last complete time directory. |
| E-S08 | `-np` / `numberOfSubdomains` mismatch *(v1.1)* | Caught pre-launch; offers to fix `decomposeParDict`. |

### Content / Post / App

| Code | Condition | Message |
|---|---|---|
| E-L01 | Signature verification failed | "This content could not be verified and was not installed." No override. |
| E-L02 | Checksum mismatch | Offers re-download once, then fails. |
| E-L03 | Sideloaded package from an unknown publisher | Explicit trust dialog; affirmative click required. |
| E-V01 | ParaView not found | Detect / download / locate manually. |
| E-V02 | ParaView cannot open the case | Distinguishes "no time directories yet" from a genuine reader failure. |
| E-A01 | Update failed | Rolled back to the previous version; the failure reason is stated. |

---

## 10. Security, privacy and trust

### 10.1 Threat model

| Asset | Threat | Mitigation |
|---|---|---|
| User's machine | Malicious content package executing code | v1.0 content is **data only** (FR-L3). No install-time scripts. Compiled extensions deferred to v2.0 behind first-party signing. |
| Content channel | Catalog or payload tampering / MITM | HTTPS only, certificate validation, **detached ed25519 signature over the catalog** with the public key compiled into the binary; per-payload sha256 from the signed catalog (FR-L4). |
| Update channel | Malicious update | Updates signed with the same trust root; downgrade rejected; rollback preserved. |
| Elevation | Privilege escalation via the setup path | Elevation requested once, for a fixed, auditable set of Windows feature-enablement operations; never for routine operation. No elevated helper service is installed. |
| User data | Accidental exfiltration via diagnostics | Bundle contents listed before export; case dictionaries included only with explicit consent; no field data ever included. |
| Network exposure | — | BuildFOAM opens **no listening sockets**. |

### 10.2 Supply chain

- Python dependencies pinned by hash (`requirements.txt` with `--require-hashes`); dependency updates reviewed, not automatic.
- Build reproducibility: CI records the exact toolchain, dependency hashes and manifest version in the artefact.
- SBOM (CycloneDX) published with each release.

### 10.3 Sandboxing posture (stated honestly)

OpenFOAM solvers run as the user, unsandboxed, inside the runtime. On Windows, WSL provides a meaningful boundary between the solver and the host; on macOS with the native tap, there is none. BuildFOAM does not claim to sandbox simulation code. This is documented, and it is a reason content is data-only in v1.0.

### 10.4 Privacy

- Telemetry is **opt-in**, off by default, with the exact payload shown at the point of choice.
- If enabled, the payload is limited to: OS + version, architecture, BuildFOAM version, OpenFOAM version, wizard step outcomes, error codes, and coarse feature-usage counters. **Never**: case names, file paths, geometry, field data, user identity, IP-derived location beyond country.
- A single switch disables all network activity including the update check ("Offline mode") — required for lab approval in many institutions.
- A published privacy statement ships with the app and is shown during setup.

---

## 11. Milestones and exit criteria

**Unit definition:** estimates are in **developer-weeks of 40 focused hours** (one FTE-week). The ordering is chosen so that the riskiest unknowns (round-trip parser, WSL provisioning) are proven early rather than late.

| M# | Deliverable | Exit criteria (all must pass) | Est. |
|---|---|---|---|
| **M0** | Foundations | Repo, CI (lint + test on both OSes), licence chosen and applied, name chosen, `RuntimeSession`/`RunPlan` interfaces defined, structured logging in place, no-Qt-in-services lint rule active. | 2 wk |
| **M1** | Shell + `FoamDict` | Hub, nav rail, status footer, view stack. **Parser passes the round-trip corpus test (§12.2) over the full bundled tutorial set** — this is the gate; do not proceed without it. | 4 wk |
| **M2** | Native runtime + first real run | On the chosen first platform: detect/provision, open the `cavity` tutorial, run `blockMesh` + solver sequentially, stream the log, plot residuals from an injected `solverInfo`, launch ParaView on the `.foam` stub. **Golden-case regression harness (§12.3) running in CI.** | 5 wk |
| **M3** | Second platform + bridge | Full WSL provisioning across a reboot, dedicated distro import, apt install, path translation both ways with Unicode and spaces, `\\wsl.localhost\` Explorer integration, ParaView over UNC. **M2's acceptance suite passes unchanged on this platform.** | 6 wk |
| **M4** | Preprocessor | Form editors (FR-P1), boundary-condition matrix (FR-P4), raw-text tab (FR-P6), validation panel (FR-C3), meshing utilities (FR-P5). **Every bundled tutorial can be opened, edited via a form, saved, and still runs.** | 6 wk |
| **M4a** | Turbulence advisor (§6.9.1) | **The questionnaire recommends each bundled tutorial's actual model, or justifies an alternative. No model/wall-treatment/mesh combination can be saved inconsistent. First-cell-height prediction lands within a factor of two on the flat-plate fixture at three Reynolds numbers. The post-run y⁺ audit flags a deliberately mismatched case, naming the patches.** | 3 wk |
| **M5** | Run experience | Stage strip, log search, multi-series monitors, three-level stop (FR-S5), divergence detection (FR-S6), run history, no orphan processes (FR-S10). **`stopAt writeNow` produces a loadable time directory in 100% of corpus cases.** | 4 wk |
| **M6** | Post + content library | **On a machine with ParaView already installed, no download is offered; on one without, the download completes and the case opens with fields loaded and no manual reader selection, on both platforms, with a Unicode path containing spaces. A tampered catalog and a tampered payload are each rejected with no install. First-load time for the largest corpus case is measured and recorded** (input to the `pvserver` contingency in §3.2). | 3 wk |
| **M7** | Guide + polish | **Every error code in §9 resolves to a guide page (automated link check, zero dangling). Offline search returns results with the network disabled. Pseudo-locale run shows no truncated or clipped strings. Automated contrast check passes NFR-A2 on every view, and a keyboard-only pass completes every task in §12.4 without a mouse.** | 3 wk |
| **M8** | Installers + release engineering | NSIS `.exe` and notarised `.dmg` from CI on tag, silent-install mode (FR-R7), lab adoption path (FR-R8), uninstall (FR-A6), update + rollback (FR-A5), SBOM. | 4 wk |
| **M9** | Beta and v1.0 | Pilot with one real cohort. **Exit: M-1 ≥ 85%, M-2 ≤ 30 min, M-4 and M-5 at 100%, zero open blocker defects.** | 4 wk |
| **M10** | v1.1 core | **A corpus case runs on 4 processors and reconstructs to a result matching the serial run within the §12.3 tolerances; an `-np`/`numberOfSubdomains` mismatch is caught before launch. A course pack authored on one machine imports and self-checks on another. A run report opens in an external reader and its case checksum matches an independent recomputation. The offline bundle installs with the network physically disconnected. The pseudo-locale pass is repeated for Bahasa Melayu.** | 8 wk |
| **M11** | Mesh refinement study (§6.9.2) | **The entire §12.6 GCI gate passes, including the published worked examples and every degenerate-input guard. A three-level `blockMesh` family is generated with measured h ratios within 2% of the request. Oscillatory and divergent fixtures produce their correct class and unreliability statement. No export path emits a bare GCI number.** | 4 wk |
| **M12** | Experimental validation (§6.9.3) | **A messy real-world CSV imports; sampled locations match to mesh tolerance with out-of-domain points reported; metrics match hand calculation exactly; u_val is assembled from the M11 GCI and displayed with a written interpretation; all five benchmark cases reproduce their published agreement within documented tolerance; no UI path shows "validated" as a boolean.** | 3 wk |

**Nominal v1.0 (M0–M9, including M4a): 44 developer-weeks = 1 760 focused hours.** v1.1 (M10–M12) adds a further **15 weeks**, of which 7 are the GCI and validation modules. What v1.0 means in calendar time:

| Capacity | Calendar duration |
|---|---|
| 1 FTE (40 h/wk) | ~11 months |
| Half-time (20 h/wk) | ~21 months |
| 15 h/wk (a lecturer's realistic research time in semester) | **~27 months** |

At 15 h/week this does not ship inside two years, which is the single most important number in this document. If that is unacceptable, the cut is not "work faster" — it is one or more of:

- **(a) Single platform for v1.0.** Removes M3 (6 wk) and roughly a third of M8 → ~36 wk ≈ 22 months at 15 h/wk.
- **(b) Fund help.** M4, M4a, M6, M11 and M12 are the most parallelisable milestones and the most suitable for a final-year or postgraduate student — M11 especially, since §12.6 defines its correctness completely before a line is written, which is exactly the kind of task you can hand over safely.
- **(c) Narrow v1.0 to the teaching-and-V&V workflow** — provisioning, content library, run, turbulence advisor, report — and defer the preprocessor's form editors (M4, 6 wk) behind the raw-text tab. Brings v1.0 to ~30 wk while preserving D1, D2, D3 and the v1.0 half of D5.
- **(d) Promote the V&V module and demote something else.** If §6.9 is the differentiator — and on the evidence of §1.4 it is the only capability with no open-source competitor — then shipping M11 in v1.0 and deferring the marketplace, course packs or the second platform is a defensible inversion. It would make the release story "the OpenFOAM front-end that does grid convergence properly" rather than "another GUI that also installs things", which is a much easier thing to be known for.

Option (d) deserves a decision rather than a default. It is recorded as an open choice in DEC-18.

**Sequencing rationale.** M1's parser gate and M2's golden-case harness exist before any feature work because they are the two things that, if wrong, silently corrupt user results. A CFD tool that produces plausible wrong answers is worse than one that does not exist.

---

## 12. Verification and test plan

### 12.1 Test corpus

The **bundled tutorial corpus** — a fixed set of ~25 cases drawn from the OpenFOAM tutorial suite, spanning incompressible/compressible, steady/transient, `blockMesh`/`snappyHexMesh`, single/multiphase, and cases exercising `#include`, `#calc`, `#codeStream`, macro expansion and regex patch keys. Vendored into the repo at a pinned OpenFOAM version and updated deliberately.

### 12.2 Round-trip fidelity test (the parser gate)

For every dictionary in the corpus:

1. Parse → render with **no modification** → assert **byte-identical** output.
2. Parse → modify one leaf value via the API → render → assert the diff is exactly one line, and that comments, ordering, blank lines and directives are otherwise untouched.
3. Parse → render → re-parse → assert semantic equality.
4. Fuzz: mutate whitespace, comment placement and directive positions; assert (1) still holds.

**This gate blocks M1.** It is the only mechanical guarantee behind the D4 promise.

### 12.3 Golden-case regression (the numerical gate)

Runs in CI on every commit touching services, on a Linux runner with OpenFOAM installed (the same `RunPlan` code path, `NativeSession`).

**Reproducibility caveat, stated up front.** CFD field output is *not* bit-reproducible across compiler version, MPI implementation, BLAS, or CPU generation, and §14.5 concedes that changing `n_procs` perturbs results at round-off level. A hash-equality gate would therefore fail spuriously the moment the CI runner image changes. The gate is consequently defined on **scalar functionals of the solution with explicit tolerances**, against references captured on a **pinned toolchain** (pinned container digest, pinned OpenFOAM package version, fixed `n_procs`) that is itself part of the reference and changes only by reviewed commit.

| Case | Assertion | Tolerance |
|---|---|---|
| `cavity` (icoFoam) | L2 norm of `U` and volume-weighted mean of `p` at final time vs reference | 1e-8 relative |
| `pitzDaily` (simpleFoam) | Iteration count to convergence; final initial-residual per equation | ±5% count; 1e-6 absolute on residuals |
| `damBreak` (interFoam) | Volume integral of `alpha.water` at t=0.1 (a conserved quantity, so a strong check) | 1e-8 relative |
| Every bundled template | BuildFOAM-generated case runs to `endTime` | exit 0 |
| Every corpus case, `.buildfoam/` deleted | Runs from a bare sourced shell | exit 0 (FR-C7) |
| Every corpus case, before/after a no-op form save | Solution functionals unchanged | bit-identical inputs ⇒ identical outputs on the pinned toolchain |

The last row is the one that actually protects users: it proves the *editor* changed nothing numerical, independently of whether the solver is reproducible. Reference values are regenerated only by an explicit, reviewed commit that also states why. A drift is a defect until proven to be an intended upstream change.

### 12.4 Platform acceptance suite (manual, gated on release)

Executed on clean VMs/machines before every release:

| Scenario | Platforms |
|---|---|
| Clean install → wizard → verification run, timed against M-2 | Win 11 (no WSL), Win 11 (WSL present, other distro), macOS 15 Apple silicon |
| Provisioning across a required reboot | Win 11 |
| Non-admin user | Win 11 managed image |
| Offline install from the lab bundle | Win 11, macOS |
| Adopt a pre-provisioned lab runtime | Win 11 |
| Unicode + spaces in the case path | Both |
| Uninstall, disk reclaimed as reported | Both |
| Update and rollback | Both |
| Force-quit mid-run leaves no orphan processes | Both |

### 12.5 Other testing

- **Unit**: services layer, per NFR-M2 coverage targets.
- **Integration**: `RuntimeSession` implementations against a real runtime in CI containers.
- **UI**: `pytest-qt` smoke tests for every view; screenshot regression for the Hub and Run views.
- **Accessibility**: automated contrast check in CI; one manual keyboard-only pass per release.
- **Performance**: NFR-P1–P6 asserted on the reference machine each release; results tracked over time.
- **Localisation**: pseudo-locale run (accented, 40%-expanded strings) to catch truncation before v1.1.

### 12.6 V&V module verification (the numerics gate for §6.9)

The V&V module computes numbers that users will put in papers. Its own correctness therefore has to be demonstrated, not assumed, and it is the one part of the application that can be tested purely analytically — the GCI procedure is arithmetic on three numbers.

| Test | Method | Gate |
|---|---|---|
| **GCI against published worked examples** | Reproduce the worked examples in Celik et al. (2008) and the NASA Turbulence Modeling Resource uncertainty summary, entering their φ and h values and comparing every intermediate quantity — p, φ_ext, e_a, e_ext, GCI — against the published figures. | Match to published precision. **Blocks the module's release.** |
| **Analytical convergence** | Manufacture φ values from a known exact solution with an imposed order (`φᵢ = φ_exact + C·hᵢ^p` for p = 1, 2, 3) and confirm the module recovers p and φ_exact. | p recovered to 1e-6; φ_ext to 1e-8 |
| **Non-uniform refinement ratios** | Construct a family with r₂₁ ≠ r₃₂ and confirm the iterative q(p) solution converges to the same answer an independent solver gives. | Agreement to 1e-8; iteration converges in < 100 steps or reports failure |
| **Oscillatory and divergent fixtures** | Constructed triples with R < 0 and \|R\| > 1. | Correct class reported; GCI is accompanied by the unreliability statement (FR-VVM6, FR-VVM9) |
| **Degenerate inputs** | ε₂₁ = 0 (identical solutions), r ≤ 1, two meshes only, meshes supplied out of order. | Each fails with a specific message, never with a NaN, an exception, or a plausible-looking wrong number |
| **Representative cell size** | Compute h for meshes of known uniform spacing in 2D and 3D. | Matches the analytical value to 1e-10 |
| **y⁺ correlation accuracy** | Flat-plate case at three Reynolds numbers; compare the first-cell-height prediction against the achieved y⁺. | Within a factor of two, which is what FR-VVT5 claims — the test asserts the claim, not perfection |
| **Validation metrics** | Fixture dataset with hand-computed E, RMSE, MAE, nRMSE, R², u_val. | Exact agreement |
| **End-to-end** | Run the full study on `pitzDaily` with a three-level `blockMesh` family and confirm the produced table is internally consistent and reproducible across two runs on the pinned toolchain. | Byte-identical table on repeat |

**Degenerate inputs deserve the emphasis.** The dangerous failure for this module is not a crash — it is returning a confident, well-formatted number from inputs that cannot support one. Every guard above is there because the alternative is a student publishing it.

---

## 13. Licensing and legal

### 13.1 Application licence

**GPL-3.0-or-later.** Rationale and the alternative considered are recorded in DEC-09.

> **On whether GPL is compelled — an opinion, not a settled fact.** It is commonly argued that a launcher which invokes OpenFOAM via fork/exec is an aggregation rather than a derivative work, and so could be licensed proprietarily. That is *a* reading of GPLv3 §5, not established law. The FSF's own guidance makes the fork/exec test turn on the intimacy of the communication, and BuildFOAM is not the easy case: it writes the input dictionaries, parses the output, and injects function objects into the solver's configuration. **Do not rely on this analysis without counsel.** Choosing GPL-3.0 makes the question moot, which is part of its appeal — and since §13.4 requires institutional IP clearance regardless, the legal review is happening anyway.

### 13.2 Dependency obligations

| Component | Licence | Obligation as we use it |
|---|---|---|
| OpenFOAM (ESI) | GPL-3.0 | Not linked; invoked as a separate process. No source-distribution obligation on BuildFOAM. Trade mark rules apply (§13.3). |
| ParaView | BSD-3-Clause | Attribution. Redistribution in the offline bundle permitted; include the licence text. |
| Qt 6 / PySide6 | LGPLv3 (with a commercial option) | Under GPL-3.0 for BuildFOAM this is compatible and the relinking obligation is moot. **If the licence ever changes to proprietary**, OneDir packaging keeps the Qt shared libraries replaceable, but whether that alone discharges LGPLv3 §4 is a question for counsel, not an assumption — published relinking instructions and a documented rebuild path would also be required. |
| Python | PSF | Attribution. |
| PyInstaller | GPL-2.0 with a bootloader exception | The exception is what permits distributing a non-GPL frozen application; under GPL-3.0 it is not a constraint. |
| Matplotlib / pyqtgraph | PSF-like / MIT | Attribution. |
| Ubuntu base rootfs (WSL distro) | Various, per-package | Redistributing a rootfs image carries per-package obligations. **Prefer importing an official Canonical-published rootfs at first run over vendoring one in the installer** — this avoids becoming a Linux distributor. |

An automated licence report (from the SBOM) ships with each release, and a **Third-Party Notices** page appears in the Guide.

### 13.3 Trade mark compliance

- The product name must not take the form *OpenFOAM \<Something\>*; OpenCFD's guidelines reject that construction explicitly.
- Permitted: a distinctive name plus a descriptor — *"BuildFOAM — a desktop workbench for OpenFOAM®"*.
- The mark carries ® on first prominent use, and the non-endorsement notice appears in: the setup wizard, the About dialog, the README, and the release page.
- Do not use OpenCFD or ESI logos, or a visual identity that suggests an official product.
- Do not imitate scFLOW's trade dress. The launcher-hub *concept* is unprotectable; a close visual copy plus the borrowed word "kicker" would not be.

### 13.4 Institutional matters

- **IP clearance**: work produced in the course of university employment may vest in the institution. Obtain written clearance before the first public release; a GPL release is normally the easiest case to get approved.
- **Citation**: register a DOI (Zenodo via the GitHub release integration) and ship a `CITATION.cff`. Academic uptake is the return on this project; make it citable from v1.0.
- **Student data**: run reports may carry student names in a teaching deployment — state in the privacy notice that reports are generated and stored locally only.

---

## 14. Teaching and laboratory deployment

This section is a first-class requirement set, not an appendix. Differentiators D2 and D3 live here.

### 14.1 What a managed lab imposes

| Constraint | Consequence | Requirement |
|---|---|---|
| Students have no administrator rights | `wsl --install` is impossible on the student account | FR-R7 (silent install by IT), FR-R8 (adopt a pre-provisioned runtime), E-R02 (a printable IT request) |
| No/limited internet during class; filtered proxies | A 4 GB first-run download is not viable | **Offline lab bundle** (§14.2) |
| Roaming profiles / network home directories | A case tree on a network drive over WSL is unusable | FR-C8 warning + a **Move to fast storage** action |
| Non-persistent machines (reimaged nightly) | Cases and the runtime vanish between sessions | Runtime baked into the image; **Export case** to student storage in one action |
| Mixed personal hardware (BYOD) | Windows, Intel Mac, Apple silicon, low RAM | Honest minimum-spec check at step 2 of the wizard; the Docker fallback on macOS |
| Fixed 2-hour lab slots | Setup must not consume the session | M-2 target ≤ 30 min; pre-provisioned image reduces it to ≤ 2 min |

### 14.2 Deliverables for institutions

1. **Offline lab bundle** — a single archive containing the installer, the WSL rootfs or brew bottles, the OpenFOAM packages, ParaView, and the starter content, installable with no network. *(v1.1)*
2. **Silent install with a config file** — `lab.json` specifying install paths, the runtime source (local bundle), the OpenFOAM version, telemetry off, update check off, and a pre-installed course pack. Consumed by NSIS `/S /CONFIG=` and by an equivalent macOS package script.
3. **Image-preparation guide** — a short document for IT: what to install once into the golden image, what must remain per-user, how to verify, and how to update between semesters.
4. **Verification script** — a one-command health check IT can run on an imaged machine that exercises the same canary + `cavity` run as wizard step 8 and prints a pass/fail.

### 14.3 Course packs (FR-L7, v1.1)

A course pack is a signed zip:

```
mech3103-week4.bfpack
├── manifest.json          # id, title, author, institution, openfoam range, checksum
├── worksheet.md           # rendered in the Guide view
├── cases/
│   ├── 01-laminar-pipe/   # a complete case tree
│   └── 02-turbulent-pipe/
├── expected/              # reference residuals + monitored values for self-checking
└── assets/                # figures, STL geometry
```

- A lecturer authors one from a working case directory via **Library → Create course pack** (fills the manifest, runs the cases to capture `expected/`, signs with the institution's key).
- A student imports it in one action; the worksheet appears in the Guide, the cases in their case list.
- **Self-check**: after a student's run, BuildFOAM can compare against `expected/` and report "within tolerance" / "diverged from the reference at …". This is formative feedback, not grading — it must never be presented as a mark.

### 14.4 Run reports (FR-V6, v1.1)

A one-click PDF containing:

- Case identity, checksum, and the BuildFOAM and OpenFOAM versions.
- Mesh statistics from `checkMesh` (cell count, non-orthogonality, skewness, aspect ratio).
- The effective `controlDict`, `fvSchemes`, `fvSolution` and boundary-condition matrix as written at run time.
- The residual history plot and any monitored quantities, with final values.
- Wall-clock time, decomposition, and the machine fingerprint.
- A student-name/matriculation field if the pack requests it.
- **The V&V section, when §6.9 output exists**: the turbulence model and wall treatment with the y⁺ audit per patch; the GCI table with its convergence class and caveats; and the experimental comparison with E, u_val and its interpretation. This is what makes the report a *defensible* artefact rather than a record of one run — and it is the same table a journal will ask for.

This is simultaneously an assessment artefact, a reproducibility record, and — for P3 — a document that can be attached to an engineering report. No competing OpenFOAM front-end does this well; it is cheap to build once the run history exists.

### 14.5 Classroom-scale considerations

- **Determinism.** Same case + same version + same decomposition should give bit-identical results; report the fingerprint so a discrepancy is diagnosable. Note honestly in the docs that changing `n_procs` changes results at round-off level — students will ask.
- **Reset.** One-click restore of a course-pack case to pristine (FR-C5), because students will break them.
- **No leaderboard, no gamification.** Out of scope, deliberately.

### 14.6 V&V as a teaching workflow

The three modules in §6.9 are not only a research capability — each maps onto a lab exercise that is currently painful to set up and tedious to mark.

| Exercise | What the module does for it | What the student learns |
|---|---|---|
| **Grid independence study** | Generates the mesh family, runs the batch, produces the GCI table — removing the three hours of manual mesh-making and spreadsheet arithmetic that currently consume the session | That "the answer changed when I refined the mesh" is a quantifiable statement, not a nuisance; and what an apparent order departing from 2 is telling them |
| **Turbulence model comparison** | Runs the same case across a shortlist of models, with the wall treatment and y⁺ handled correctly for each | Why k-ε and k-ω SST disagree on a separating flow, and that the disagreement is physics, not a bug |
| **Validation against published data** | Imports a benchmark dataset, co-locates the sampling, produces the overlay and the metrics | That agreement is a quantity with an uncertainty attached, not a visual impression of two curves being close |

Two consequences for the product:

- **Course packs should carry V&V configuration.** A pack (§14.3) can ship the mesh-family definition, the QoI list, and the reference experimental data, so a week's exercise is one import. This is a small extension to the manifest and the single highest-value thing the pack format can carry.
- **The run report becomes the submission.** §14.4's report with a V&V section is exactly what a lab write-up should contain, and it is auditable — the case checksum and environment fingerprint make it clear whether two students submitted the same run.

One caution worth stating in the guide rather than discovering in a lab: a grid-convergence study needs three runs, and the coarsest-to-finest ratio means the fine mesh may take an order of magnitude longer than the students' single-mesh exercise. Course packs must size their cases for the *family*, not for one run, or the exercise will not finish inside the session.

---

## 15. Release, update and support

### 15.1 Versioning

Semantic versioning on the application (`MAJOR.MINOR.PATCH`). The runtime manifest and content catalog are versioned independently, so OpenFOAM v2612 support ships without an app release.

### 15.2 Channels

| Channel | Audience | Cadence |
|---|---|---|
| **Stable** | Default | Every 8–12 weeks; patch releases as needed |
| **Beta** | Opt-in | Before each stable |
| **LTS** *(from v2.0)* | Institutions | One per academic year, patched for 12 months — because a lab image cannot be re-cut mid-semester |

### 15.3 Build and signing

- **CI**: GitHub Actions, tag-triggered, matrix-building Windows and macOS artefacts plus the SBOM and licence report.
- **macOS**: Developer ID signing + notarisation. **An Apple Developer Program membership (USD 99/yr) is a hard requirement** — an unnotarised `.dmg` is effectively undistributable to the target audience on current macOS.
- **Windows**: v1.0 ships **unsigned**, with a documented SmartScreen path and published sha256 checksums. Acquire an OV certificate (~USD 200–400/yr) once download volume makes the reputation penalty material; EV (hardware token) only if enterprise deployment demands it.
- **Budget line**: USD ~99/yr minimum, ~USD 400/yr with Windows signing.

### 15.4 Support

- GitHub Issues with templates that request a diagnostics bundle and an error code.
- A troubleshooting index in the Guide, keyed by the §9 codes.
- A published support policy: latest stable is supported; the previous minor gets security fixes for 6 months.

### 15.5 Deprecation

Dropping an OpenFOAM version requires one release of advance notice in the changelog and an in-app warning for cases pinned to it.

---

## 16. Decision log

Architecture-decision records for every question left open in v0.1, plus decisions taken during this revision.

**Coverage of v0.1's open questions:** Q1→DEC-01 · Q2→DEC-02 · Q3→DEC-03 · Q4→DEC-04 · Q5→DEC-16 · Q6→DEC-06 · Q7→DEC-07 · Q8→DEC-08 · Q9→DEC-09 · Q10→DEC-10. DEC-05 and DEC-11…DEC-15 are new decisions arising from this revision. **No question is left open.**

| ID | Decision | Alternatives rejected | Rationale | Reversal cost |
|---|---|---|---|---|
| **DEC-01** | Do not reference or reverse-engineer scFLOW. Original hub design (§7.1). | Mirror the scFLOW kicker layout | The hub concept is unprotectable but a close copy plus borrowed terminology invites a trade-dress argument for zero user benefit. | Low |
| **DEC-02** | No cloud registry in v1.0. v1.1 uses a **static host** (GitHub Pages for a signed `catalog.json`, GitHub Releases for payloads). | Self-hosted registry server from day one | Free, HTTPS, CDN-backed, versioned, zero operations, no server to patch. A full server is only justified by third-party uploads, which DEC-04 rejects. | Low |
| **DEC-03** | Rename away from "OpenFOAM GUI". Working name **BuildFOAM**, styled *"BuildFOAM — a desktop workbench for OpenFOAM®"*, with the OpenCFD non-endorsement notice on first prominent use. Drop "Kicker". **Constraint 2 below is knowingly overridden by the product owner; the other three hold.** | "OpenFOAM GUI"; "OpenFOAM Kicker"; `OpenFlow` (the ONF's SDN protocol, and a near-miss on OPENFOAM); `Airlens` (crowded, and implies visualization) | Naming constraints, in order of strength: **(1)** not `OpenFOAM <X>` — the construction the guidelines reject by name; **(2)** not `<something>Foam` — OpenFOAM's own executable convention, so it implies the product ships inside OpenFOAM; **(3)** no `Open` prefix implying a foundation-backed standard; **(4)** no implication of visualization (NG3). BuildFOAM satisfies 1, 3 and 4 and knowingly breaches 2. FOAM alone is not the registered mark, so the exposure is a plausible letter from OpenCFD rather than clear infringement — an owner's judgement call, logged rather than argued. | **High after release; Low before it, via NFR-M5.** Revisit at M8. |
| **DEC-04** | Content library is **first-party, data-only** in v1.0. Sideload behind an explicit trust dialog. Compiled extensions in v2.0 behind signing. | User uploads with authentication in v1 | User uploads require auth, moderation and abuse handling, and would make BuildFOAM the distribution channel for arbitrary code running on student machines. Data-only removes the entire class of risk. | Medium |
| **DEC-05** | Cases live on the **runtime-native filesystem** by default; Windows-side storage is opt-in with a warning. | `/mnt/c` by default, as in v0.1 | Order-of-magnitude small-file I/O penalty across the WSL 9p layer, no POSIX permissions or symlinks, case-insensitivity collisions, no `inotify`. OpenFOAM's write pattern is the worst case for it. | **High** — touches File Bridge, User Folder, New Case |
| **DEC-06** | v1.0 is **sequential-only in the UI**, but the `RunPlan` machinery is parallel-aware from M0 (`n_procs` fixed at 1). Parallel UI in v1.1, single machine, `scotch`/`simple`. | Parallel in v1.0; permanently serial | Parallel triples the failure surface (decomposition mismatch, partial reconstruction, MPI in WSL) but is essential for P3. Building the abstraction now makes v1.1 a UI change. | Low as specified; **high if hard-coded serial** |
| **DEC-07** | **Both** form editors and a raw-text tab for every dictionary, with byte-faithful round-trip as a blocking test. | Forms only; text only | Forms serve P1/P2; the text tab keeps the P4 constraint. Round-trip fidelity is what makes the two safe together. | **High** — parser architecture |
| **DEC-08** | Write **original** documentation; deep-link upstream rather than rehost. | Bundle the OpenFOAM User Guide | Rehosting invites licence and staleness problems and duplicates something upstream does better. The gap is task-oriented docs. | Low |
| **DEC-09** | **GPL-3.0-or-later.** | Proprietary; Apache-2.0 core + proprietary shell | Moots the LGPL-Qt relinking obligation; simplifies institutional IP clearance; maximises academic adoption and citation. Explicitly *not* compelled by OpenFOAM's licence — the subprocess boundary means proprietary would be legal. | **High after the first external contribution** |
| **DEC-10** | GitHub Actions CI. **macOS notarised (Apple Developer, USD 99/yr — mandatory). Windows unsigned for v1.0**, OV certificate when volume justifies it. | Sign both from day one; sign neither | Gatekeeper makes macOS notarisation non-optional. Windows SmartScreen is survivable at low volume with published checksums. | Low |
| **DEC-11** | Build the **native (macOS) runtime first** if the developer is on Apple silicon; otherwise Windows first. Second platform at M3. | Both simultaneously | The native path has no bridge, no elevation and no reboot, so M2 proves the *product* before M3 fights the *platform*. Choose on your own hardware and your students' hardware — if the cohort is Windows-only, invert it and accept a slower M2. | Medium at M2; high later |
| **DEC-12** | Import a **dedicated WSL distribution** named for the app rather than adopting the user's default Ubuntu. Accept that this puts default case storage inside the distro's VHDX, and pay for it with a mandatory case-export step before any uninstall (FR-R12). | Use the existing default distro; keep cases host-side | Deterministic support surface, no collision with the user's toolchain, self-contained removal. Costs ~2 GB, a longer first run, and the export obligation — `wsl --unregister` would otherwise delete the user's work. | Medium |
| **DEC-17** | Windows 10 22H2 is **best-effort until 30 June 2027**, then dropped. | Full support; no support | Windows 10 has been out of support since 14 October 2025, but student hardware lags and excluding it would exclude part of the target cohort. Best-effort means the acceptance suite covers it while no Windows-10-specific defect blocks a release. A dated sunset stops it becoming permanent by inertia. | Low |
| **DEC-13** | Monitor via an **injected `solverInfo` function object** reading `postProcessing/**/*.dat`; log scraping only as fallback. | Regex log parsing as primary | Stable columnar output vs. a format that changes between releases and solvers; works identically in parallel. | Low |
| **DEC-14** | Default stop is **`stopAt writeNow`** via `runTimeModifiable`; SIGTERM and SIGKILL are explicit secondary choices. "Pause" is removed. | SIGTERM as the stop button; SIGSTOP pause | SIGTERM mid-write leaves a partial time directory that breaks reconstruction and ParaView. Solvers cannot pause; SIGSTOP under MPI risks teardown. | Low |
| **DEC-15** | ESI lineage only in v1.x; the manifest is structured so the Foundation lineage is additive. | Support both from v1.0 | Dictionary naming diverges (`transportProperties`/`physicalProperties`, `turbulenceProperties`/`momentumTransport`), doubling the schema surface for a fraction of the audience. | Low — additive by design |
| **DEC-18** | **V&V module split across releases**: the turbulence advisor ships in v1.0 (it is case setup, and cheap); the GCI mesh study and experimental validation ship in v1.1. **Open question flagged for the owner:** whether to invert this and promote the GCI module (M11, 4 wk) into v1.0, deferring the content library or the second platform instead. | All three in v1.0; all three in v2.0; V&V as an optional plugin | The advisor prevents errors *before* a run and costs 3 weeks, so it earns its v1.0 place. GCI and validation are post-processing of completed runs, so they compose cleanly onto a shipped v1.0 without rework — the `RunPlan` batch machinery they need already exists from M5. Against that: §1.4 shows V&V is the *only* capability with no open-source competitor, which argues for leading with it. | Low — the modules are additive by construction |
| **DEC-19** | Implement the **Celik et al. (2008) JFE procedure** specifically, with the 1.25 three-mesh safety factor, rather than a simplified two-mesh Richardson extrapolation or a bespoke formulation. | Plain Richardson extrapolation; Roache's original GCI; a two-mesh estimate with assumed p | It is the procedure journal reviewers in this field expect, it is published in full with worked examples that double as test fixtures (§12.6), and it handles non-uniform refinement ratios via the q(p) term, which real mesh families need. A two-mesh estimate with assumed p is supported only as an explicitly-labelled fallback carrying the 3.0 safety factor. | Low |
| **DEC-20** | **No pass/fail verdicts on V&V output** (FR-VVM9, FR-VVE8). Report the number, its convergence class, its assumptions and its interpretation; the adequacy judgement stays with the engineer. | A green/red "validated" badge, which users will ask for | A GCI or a comparison error is only meaningful against an application-specific tolerance the tool cannot know. A boolean badge would be the most-used and least-defensible feature in the product, and in a teaching context it would train exactly the wrong instinct. | **High** — it is a product-philosophy commitment, not a UI detail |
| **DEC-16** | ParaView acquisition order: **detect an existing install → download at first run → offline bundle for labs**. Never bundled in the default installer, and always skippable. | Bundle ParaView in the installer; require it before setup completes | Detection is free and much of the target audience already has ParaView; a ~1 GB installer materially depresses download conversion; labs are served by the offline bundle (§14.2). Making it skippable keeps setup unblocked when a download fails. | Low |

---

## 17. Risk register

| ID | Risk | L | I | Mitigation | Trigger for the contingency |
|---|---|---|---|---|---|
| RISK-01 | **Scope exceeds capacity**; v1.0 never ships | High | High | Hard cut-line (§2.1); DEC-11 single-platform fallback; milestone exit criteria that permit honest slipping | M3 not complete by month 9 → drop the second platform from v1.0 |
| RISK-02 | **macOS tap is abandoned** by its maintainer | Medium | High | Docker fallback (FR-R10) built in v1.0, not deferred; monitor the upstream repo; be prepared to vendor the build recipe | No tap release within 3 months of an OpenFOAM release |
| RISK-03 | **WSL provisioning breaks** on a Windows update | Medium | High | Platform acceptance suite on clean VMs each release; provisioning is idempotent and resumable (NFR-R4); explicit E-R0x codes so failures are diagnosable in the field | Any acceptance-suite failure on a current Windows build |
| RISK-04 | **Round-trip parser is harder than estimated** | Medium | High | It is the M1 gate specifically so this surfaces in month 2, not month 12 | M1 exceeds 6 weeks → reduce v1.0 form editors to `controlDict` only and lead with the text editor |
| RISK-05 | **OpenFOAM changes dictionary structure** in a future release | Medium | Medium | Manifest + schema files (§3.4, §5.4); no version literals in code (NFR-M3) | — |
| RISK-06 | **Institutional IP claim** blocks an open release | Low | High | Obtain written clearance before M8, not after | Clearance unresolved at M7 |
| RISK-07 | **No adoption** — built, but unused | Medium | High | Pilot with a real cohort at M9 as a release gate; D2/D3 are the adoption hooks; DOI + `CITATION.cff` from v1.0 | Fewer than 2 institutions using it 6 months post-release → refocus entirely on the course-pack workflow |
| RISK-08 | **Single-developer bus factor** | High | High | Public repo from M0; documented architecture; the service layer is Qt-free and independently usable; no undocumented build steps | — |
| RISK-09 | **Support load exceeds capacity** after release | Medium | Medium | Error codes + diagnostics bundles + a troubleshooting index make issues self-serviceable; a published support policy sets expectations | > 5 h/week on support → require a diagnostics bundle before triage |
| RISK-10 | **A content package harms a user's machine** | Low | High | Data-only content (DEC-04), signed catalog, no install-time execution, honest sandboxing statement (§10.3) | — |
| RISK-11 | **The V&V module produces a confident wrong number** that a user publishes | Medium | **Very high** | This is the most serious risk in the document — a reputational failure that would discredit the whole tool. Controls: §12.6 verification against published worked examples as a release gate; mandatory caveats on every output (FR-VVM9); convergence classification always shown (FR-VVM6); iterative-convergence evidence required (FR-VVM10); no pass/fail verdicts (DEC-20); every degenerate input guarded and tested | Any §12.6 test failing blocks the module's release outright — no exceptions, no "ship with a known issue" |
| RISK-12 | **Mesh-family generation is harder than estimated** for anything but `blockMesh` | High | Medium | `snappyHexMesh` refinement levels give only r = 2 granularity and do not refine geometrically uniformly; imported meshes cannot be systematically refined at all. Mitigation: FR-VVM2 makes the manual three-mesh path first-class, so the module is useful even where automatic generation is impossible, and the limitation is disclosed rather than hidden | If automatic `snappyHexMesh` families fail the 2%-ratio criterion at M11, ship manual-only and document it |

---

## 18. Glossary

| Term | Meaning |
|---|---|
| **Case** | A directory tree holding one OpenFOAM simulation: `system/`, `constant/`, `0/`, plus time directories written during a run. |
| **Dictionary** | An OpenFOAM configuration file in its own key–value format, supporting includes, macros and embedded code. |
| **`boundaryField`** | A sub-dictionary *inside each field file* (`0/U`, `0/p`, …) assigning a boundary condition to every patch. Not a file. |
| **Patch** | A named region of the mesh boundary, defined in `constant/polyMesh/boundary`. |
| **Function object** | A runtime-loaded OpenFOAM plugin that computes and writes diagnostics during a solve, e.g. `solverInfo`, `forceCoeffs`. |
| **`.foam` stub** | An empty file at the case root that ParaView's reader uses to identify an OpenFOAM case. |
| **Lineage** | The two divergent OpenFOAM distributions: ESI/OpenCFD (`openfoam.com`, `vYYMM`) and the OpenFOAM Foundation (`openfoam.org`, `v13`, `v14`…). |
| **`RunPlan` / Stage** | BuildFOAM's internal representation of an execution as an ordered list of commands with success predicates. |
| **Course pack** | A signed bundle of cases, a worksheet and reference results, distributed by a lecturer and imported in one action. |
| **Runtime** | The provisioned environment in which OpenFOAM executes: a WSL distribution, a native macOS installation, or a Docker container. |
| **Verification** | Establishing that the equations are being solved correctly — i.e. quantifying numerical error. The mesh refinement study (§6.9.2) is verification. |
| **Validation** | Establishing that the right equations are being solved — i.e. comparing against physical reality. The experimental comparison (§6.9.3) is validation. |
| **Richardson extrapolation** | Estimating the exact (zero-grid-spacing) solution from two or more solutions on systematically refined meshes, assuming the error scales as a power of the cell size. |
| **GCI** | Grid Convergence Index. A discretization-uncertainty band derived from Richardson extrapolation with a safety factor — 1.25 for a three-mesh study with a computed apparent order, 3.0 for a two-mesh study with an assumed one. |
| **Apparent order (p)** | The convergence order actually observed from the mesh family, as distinct from the scheme's theoretical order. A large discrepancy signals that the solutions are not in the asymptotic range. |
| **Asymptotic range** | The regime of mesh fineness in which the discretization error genuinely scales as hᵖ. GCI is only meaningful inside it, which is why FR-VVM9 exists. |
| **QoI** | Quantity of Interest. The scalar output a convergence study or validation comparison is performed on — a drag coefficient, a pressure drop, a Nusselt number. |
| **y⁺** | Non-dimensional wall distance of the first cell centre. Determines which near-wall treatment is valid: roughly 30–300 for wall functions, ≈ 1 for a resolved near-wall model, and 5–30 is the buffer layer, which should be avoided. |
| **u_val** | Validation uncertainty (ASME V&V 20): the combined numerical, input-parameter and experimental uncertainty. It sets the floor below which a modelling error cannot be resolved. |

---

## Appendix A — Sources for factual claims

- [New OpenFOAM® v2606 release — openfoam.com](https://www.openfoam.com/news/main-news/openfoam-v2606)
- [Current Release — openfoam.com](https://www.openfoam.com/current-release)
- [OPENFOAM® Trade Mark Guidelines — openfoam.com](https://www.openfoam.com/openfoam-trade-mark-guidelines)
- [OpenCFD Limited Trade Mark Policy — openfoam.com](https://www.openfoam.com/opencfd-limited-trade-mark-policy)
- [gerlero/openfoam-app — Native OpenFOAM for macOS (GitHub)](https://github.com/gerlero/openfoam-app)
- [Working across Windows and Linux file systems — Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
- [WSL2: File operations on NTFS folders extremely slow — microsoft/WSL issue #4515](https://github.com/microsoft/WSL/issues/4515)
- [ParaView 6.1.1 Release Notes — Kitware](https://www.kitware.com/paraview-6-1-1-release-notes/)
- [Download ParaView — paraview.org](https://www.paraview.org/download/)
- Celik, Ghia, Roache, Freitas, Coleman & Raad (2008), ["Procedure for Estimation and Reporting of Uncertainty Due to Discretization in CFD Applications", *J. Fluids Eng.* 130(7):078001](https://asmedigitalcollection.asme.org/fluidsengineering/article/130/7/078001/444689/Procedure-for-Estimation-and-Reporting-of) — the source of the five-step GCI procedure in §6.9.2 and the worked examples used as test fixtures in §12.6
- [NASA Turbulence Modeling Resource — uncertainty procedure summary](https://turbmodels.larc.nasa.gov/uncertainty_summary.pdf) — independent restatement of the same procedure, used to cross-check the equations
- [Grid Convergence Index calculator — Volupe](https://volupe.com/support/grid-convergence-index-calculator/) — confirms the r > 1.3 minimum refinement ratio, the 1.25/3.0 safety-factor convention, and the monotonic/oscillatory/divergent classification by R
- ASME V&V 20-2009, *Standard for Verification and Validation in Computational Fluid Dynamics and Heat Transfer* — the framework for §6.9.3 (comparison error E = S − D; validation uncertainty u_val). See also [Coleman's overview of the standard](https://maretec.tecnico.ulisboa.pt/~maretec.daemon/html_files/CFD_workshops/html_files_2008/papers/COLEMAN.pdf). **The standard itself is paywalled — obtain a copy before implementing §6.9.3 rather than working from secondary summaries.**
