# Product Requirements Document — **BuildFOAM**
### A BIM-to-simulation suite for building-services engineers, built on OpenFOAM®

**Version:** 2.0 · **Status:** Draft — *not approved for build until the §0 decisions are taken* · **Date:** 23 September 2026
**Supersedes:** PRD v1.0 "A desktop workbench for OpenFOAM®", 10 August 2026, as amended by DEC-24
**Companion:** `PRD-v1.0.md` stays in the repository unchanged, because code cites it

> *BuildFOAM is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.* Nor is it approved or endorsed by the U.S. Department of Energy (EnergyPlus™), Lawrence Berkeley National Laboratory (Radiance), NIST (FDS), buildingSMART (IFC), or any body that owns a rating scheme or standard named in this document. Such names are used only to say what a feature reads, writes or calculates.

---

## How to read this document

This revision changes what the product *is*. It must not change what the code already *says*. Code comments cite v1.0 by section (`§7.5`) and by identifier (`FR-S3`, `DEC-14`, `NFR-M1`, `E-C02`). If this document renumbered anything, those citations would silently point at the wrong text. So five rules apply.

1. **Section numbers §1–§18 keep their v1.0 subjects.** New material is added as new subsections at the end of the section it belongs to (§3.6, §5.5, §6.11 …). The only new top-level sections are §0 and §19.
2. **Every identifier keeps its meaning.** This covers every FR, NFR, DEC, RISK, milestone number (M#) and §9 error code in v1.0, and the codes added during implementation (§9.1). None is renumbered, reused or redefined. Where v2.0 changes a v1.0 requirement's *priority*, §2.4 says so, and the requirement text stays as it was.
3. **v1.0 text is incorporated by reference.** A v1.0 section this document does not restate stays in force as written: §3.1–§3.5, §4.1–§4.3, §5.1–§5.4, §6.1–§6.10, §7.1–§7.9, §8.1–§8.6, §9, §10.1–§10.4, §12.1–§12.6, §13.1–§13.4, §14, §15.1–§15.5 and Appendix A. Where v2.0 amends one of them, the amendment is explicit and cites it.
4. **NFR-M8 is deliberately left unassigned.** `services/cad.py` cites "NFR-M8's size budget", which means **NFR-P8**. Assigning NFR-M8 to something else would make that citation false. New maintainability requirements therefore start at NFR-M9.
5. **"v2.0" means two things, so this document keeps them apart.** *PRD v2.0* is this document. *Release 2.0* is the first public release of the building suite. v1.0's ladder also had a "v2.0" (compiled extensions, cluster submission, plugin API). DEC-40 re-slots that content. Its old label is not reused.

> **Provenance.** The feature scope added in this revision came from the owner's feature-level inventory of **BIM HVACTool**, a commercial Windows product the owner states they own (§13.11). The inventory described features, inputs and outputs. It did not describe code. Everything below is specified in BuildFOAM's own terms. No UI text, artwork, names, file layouts or trade dress of that product is used, and BuildFOAM does not present itself as a copy or successor of it. Elsewhere in this document it is called "the owner's commercial product".

---

## 0. Open decisions for the owner

v1.0 ended with "no question is left open". This revision cannot, because several of its questions are commercial and legal rather than technical, and only the owner can answer them. None of the work that depends on them should start before they are answered. The **Blocks** column says what waits.

| # | Decision | Options (detail in the cited section) | Recommendation | Blocks | Decide by |
|---|---|---|---|---|---|
| **OD-1** | **Licence model** for the expanded product (DEC-09 is under review) | (A) GPL-3.0-or-later throughout, the status quo · (B) dual licence, GPL plus commercial · (C) open core: a GPL core, with proprietary add-ons that talk to it only across a process boundary · (D) a permissive licence · (E) proprietary. §13.5 | **A or C.** Whichever is chosen, a contributor licence agreement (CLA) is needed *now* if B or D is ever to stay possible | Porting any logic, template or data from the owner's commercial product; accepting the first external contribution | Before M13 starts |
| **OD-2** | **Written confirmation of IP rights**, and institutional clearance | The installers of the owner's commercial product name *Tian Building Engineering* as copyright holder. §13.11 lists what has to be confirmed in writing | Obtain it. Until it exists, implement only clean-room, from this document's feature descriptions plus public standards and literature | Any copying of code, templates, data tables or solver sources; any public release of 2.x | Before M15 |
| **OD-3** | **Replace or complement** the owner's commercial product | (i) BuildFOAM becomes the full suite (the whole ladder in §2.1). (ii) BuildFOAM becomes the open CFD, V&V and BIM→CFD core, and the commercial product keeps energy, daylight and compliance, exchanging data through the open project format (§5.5). §11.4 cut (a) | **(ii) first**, revisited after Release 2.0. At 15 h/week, (i) is about a decade of work (§11.3) | The shape of every release after 2.0 | Before M21 |
| **OD-4** | **Regional priority** for compliance, climate data and standards packs | Singapore and Malaysia (ETTV/RETV/OTTV, Green Mark, GBI) · Germany and DACH (VDI/DIN procedures, BNB) · International (ASHRAE 55, EN 16798, LEED daylight) | International first (2.1), then one regional pack chosen for the owner's market (2.2). Each pack is gated on the standards-content licence (§13.9) | FR-K, and the DE/SG/MY items in FR-E and FR-T | Before M30 |
| **OD-5** | **Native Windows OpenFOAM build**: who builds and publishes it, and whether it becomes the default Windows runtime | Owner-built with a published reproducible recipe and source · an upstream Windows build, if one is published for the target release · WSL only (no native) | Native becomes the default when a *verified* build exists for the manifest's default version, and WSL stays as the fallback (DEC-26). The build **must** ship with Corresponding Source (§13.7) | M13 | Before M13 |
| **OD-6** | **Custom OpenFOAM solvers** (comfort, humidity, wind-driven rain and others) | Publish their source under GPL and ship them · re-implement the comfort indices in services and do not ship the solvers (DEC-32) · both | Implement comfort in services (DEC-32). Publish the source of any solver that is still distributed, **including in the owner's commercial product today** (§13.7) | FR-T, FR-W8, and the humidity physics | Before M20 |
| **OD-7** | **macOS in 2.x** | Full parity · Windows-first, with each engine brought to macOS when it is verified there · freeze macOS at the 1.x feature set | Windows-first. The engines (EnergyPlus, Radiance, FDS) all have macOS builds, so parity costs acceptance-testing time rather than design | Every 2.x acceptance suite | Before M21 |
| **OD-8** | **Proprietary BIM formats** (Revit, DWG, SketchUp) | Rely on IFC, DXF and OBJ exports from the authoring tools · the owner builds separately licensed, out-of-process converter plug-ins (DEC-31), paying for ODA membership · a Revit-side add-in that exports the open project format | IFC-first in 2.0. A converter plug-in only under OD-1 (C) and only if demand is shown | FR-B15 | Any time; not on the critical path |
| **OD-9** | **Sequencing of v1.1 against 2.0** (and DEC-18, which is still open) | Ship v1.1 (M10–M12: parallel runs, GCI, validation) before 2.0 · interleave · defer the GCI and validation modules until after 2.0 | M10 (parallel) **must** precede M19, because a building-scale case needs it (§2.4). Ship M11 and M12 before 2.0. They are D5, and 7 weeks | M19 | Now |
| **OD-10** | **Legacy project files** from the owner's commercial product | A BuildFOAM reader for its binary format · an exporter *inside the commercial product* that writes BuildFOAM's open format, plus BuildFOAM's `.hvacobj` importer (DEC-37) | The exporter route. BuildFOAM never deserialises a platform binary serialiser (§10.7) | FR-B10 | Before M16 |

**Implementation status at this revision.** The repository's history contains commits labelled against M3 (the WSL bridge), M5, M6, M7 and M8, plus DEC-21 to DEC-24 (the Fluent-style shell and the MCP agent interface), on top of M0–M2. Whether each milestone's *exit criterion* is met has not been audited for this revision. §11.1 therefore carries an explicit allowance, **R1**, for residual v1.0 gaps. M9 (pilot) and M10–M12 (v1.1) have not started.

---

## 1. Product definition

### 1.1 One-sentence definition

BuildFOAM is a desktop application that takes a building information model, turns it into simulation-ready studies, and runs them. OpenFOAM is the CFD engine at its core; EnergyPlus, Radiance and FDS are added as external engines. BuildFOAM also carries forward v1.0's promises: no terminal, no trapped files, and numbers that come with their uncertainty.

v1.0's definition still holds, but now as a subset. Everything a v1.0 user could do, a 2.x user can still do, in the same window, with the same guarantees.

### 1.2 The problem

v1.0's three barriers (installation, environment, case authoring, §1.2) still apply, and all three get *worse* for a building-services engineer. Four more barriers arrive with the building:

4. **Geometry re-entry.** The building already exists as a BIM model. Today each analysis tool gets its own re-drawn or re-exported copy, so the CFD, energy and daylight models of one building disagree about its geometry within a week.
5. **BIM is not simulation-ready.** An architectural model has overlapping walls, rooms that are not closed, and openings modelled as holes in a solid. An STL export throws away the one thing CFD setup needs, which is *what each surface is*. A wall, a window and a supply diffuser become indistinguishable triangles, and the engineer names patches by hand.
6. **Tool fragmentation.** Energy, daylight, comfort, wind and compliance each live in a separate tool with its own inputs. The constructions typed into the energy model are not the ones the CFD thermal boundaries use.
7. **Corporate Windows machines.** Many practices do not allow virtualisation or WSL on engineers' laptops. v1.0's Windows runtime (WSL2, §3.2) is unavailable exactly where the building-services audience works.

BuildFOAM addresses 4–7 with one open building model (§5.6), a mapping from building elements to OpenFOAM patches and boundary conditions that lives in data (§5.7), external engines behind a common abstraction (§4.4), and a native Windows OpenFOAM runtime (§3.6). It still does not replace the OpenFOAM command line, ParaView, a CAD or BIM authoring tool, or the engineer's judgement (§2.2).

### 1.3 Target users

v1.0's personas are unchanged. P1 and P2 stay primary for the 1.x line and for teaching. P3 stays secondary. **P4 is still a constraint, not a feature**, and it now extends to every engine: a generated `epJSON`, Radiance scene or FDS input must be as hand-editable and as honestly written as an OpenFOAM dictionary.

| Persona | Description | Primary need | Success looks like |
|---|---|---|---|
| **P5 — Building-services / HVAC engineer** (primary for 2.x) | Designs ventilation, heating and cooling in a consultancy or contractor. Uses Windows and BIM. Knows ASHRAE and CIBSE, not Linux. Has run commercial CFD occasionally | Show that a room's air distribution and thermal comfort work before it is built, from the architect's IFC | Goes from an IFC of one office floor to a converged indoor comfort study in an afternoon, without drawing geometry or naming a patch by hand (M-6) |
| **P6 — Façade and compliance consultant** (secondary, from 2.2) | Produces envelope-performance, daylight and green-rating submissions | A defensible, submission-ready calculation with the rule edition stated | Produces an envelope-compliance report whose every number traces to an input and to a named edition of the rule (FR-K10) |
| **P7 — Fire engineer** (tertiary, 3.0) | Performance-based smoke-control design | FDS and OpenFOAM fire cases from the same building model, with no second model to build | Builds an FDS input from the building model with meshes, obstructions and vents placed. The tenability judgement stays the engineer's (FR-F5) |

### 1.4 Competitive positioning

v1.0's table (§1.4) stands. The building-suite landscape adds these rows.

| Tool or category | What it is | Why BuildFOAM is different |
|---|---|---|
| **Ladybug Tools** (Honeybee etc.) | Open-source environmental analysis inside Rhino/Grasshopper, driving EnergyPlus, Radiance and OpenFOAM. AGPL-3.0 | BuildFOAM needs no CAD host and no visual programming. It is BIM-first rather than geometry-first, and it carries the V&V discipline (D5) and byte-faithful files (D4) that a scripting toolkit leaves to the user |
| **OpenStudio** (application and SDK) | Open-source EnergyPlus front-end and model SDK | Energy only. BuildFOAM treats energy as one engine beside CFD and daylight, all reading the same building model |
| **Commercial building-performance suites** | Integrated energy, daylight and CFD, usually proprietary and Windows-only | BuildFOAM is open (subject to OD-1), its CFD is OpenFOAM, and every input file stays a valid, hand-editable engine file |
| **Commercial BIM-to-CFD tools** | Proprietary CFD for rooms and buildings | BuildFOAM's CFD numbers carry their GCI, their y⁺ audit and their provenance (D5, §7.9 rule 6). Its cases run from a bare solver invocation |

**The differentiators.** D1–D5 stand unchanged. Three are added, and they too must not be cut:

- **D6. Semantics survive the trip to the solver.** A surface keeps what it *is* (external wall, glazed door, supply terminal) from IFC import through to the OpenFOAM patch and its boundary condition. Clicking a patch shows the building elements it came from (FR-B22).
- **D7. One open model, many engines.** CFD, energy, daylight and compliance read the same spaces, constructions and openings, from a documented, diffable, non-binary project format (DEC-28).
- **D8. Compliance numbers with provenance.** Every compliance result names its rule set, its edition and its input data, and it never overstates what it proves (DEC-33).

### 1.5 Success metrics

M-1 to M-5 stand. They are joined by:

| Metric | Target | Measurement |
|---|---|---|
| M-6 BIM to first indoor result | ≤ 4 h from an IFC of a single office floor (≤ 20 spaces) to a converged indoor study, for a P5 new to the tool | Timed acceptance test with the reference IFC corpus (§12.9) |
| M-7 Simulation-ready import | ≥ 80% of spaces in the reference IFC corpus import as closed air volumes with no manual repair; the rest are named with their defect located (E-B05) | Automated (§12.9) |
| M-8 Native Windows first run | ≤ 20 min from installer to a converged `cavity` run, **with no elevation and no reboot** | Timed, on the M-2 reference machine |
| M-9 Engine interop | 100% of generated EnergyPlus, Radiance and FDS inputs run unmodified from the engine's own command line | Automated (§12.8) |

---

## 2. Scope and release plan

### 2.1 Release ladder

| Release | Audience | Contents | Hard cut-line |
|---|---|---|---|
| **v0.9, v1.0, v1.1** | As in v1.0 §2.1 | Unchanged, except that v1.0's "v2.0" row is replaced by the rows below (DEC-40) | Unchanged |
| **2.0 — BIM→CFD for HVAC** | Public | **Native Windows runtime** (FR-N) · engine abstraction and component manager · open project format · **IFC import**, gbXML and `.hvacobj` import · building workspace with a 3D view · HVAC terminal and heat-source library · **automatic derivation of indoor CFD studies** (element → patch → BC) · result maps on planes · ISO 7730 PMV/PPD/DR from CFD · study report | No energy engine. No daylight. No compliance. No outdoor wind. No remote runs. **Requires v1.1's parallel runs (M10)** |
| **2.1 — Energy, comfort, wind** | Public | EnergyPlus engine (epJSON writer, results, one-way coupling to CFD boundary conditions) · construction, material, glazing and schedule libraries · ASHRAE 55 / EN 16798 / local discomfort · EPW analysis · urban context import · wind domain builder and pedestrian wind comfort · scripting API, CLI and variants · DXF and 3DM import | No daylight. No compliance verdicts. No wind-driven rain |
| **2.2 — Daylight and compliance** | Public | Radiance engine (daylight factor, climate-based metrics, glare) · sun and shadow · compliance framework plus the first regional pack (OD-4) · natural ventilation · wind-driven rain · compiled extensions (FR-L8) · parameter sweeps · glTF export | No fire. No remote runs |
| **3.0 — Fire** | Public | FDS engine and input generation from the building model · fire outputs · OpenFOAM fire (`fireFoam`) design fires | No evacuation modelling |
| **3.x** | Public | Remote and HPC runs (SSH, Slurm, PBS) · further regional packs (OD-4) · user-supplied FMU co-simulation | — |

### 2.2 Non-goals — revised

v1.0 said these were permanent. Five of them are now changed, and each change says why. None is dropped silently.

| ID | v1.0 text (short) | v2.0 disposition | Boundary and reason |
|---|---|---|---|
| **NG1** | No geometry creation or interactive CAD | **Relaxed** | The building is the input, so BuildFOAM now *edits building semantics*: element classification, spaces, openings by window-to-wall ratio, HVAC terminals and heat sources placed on surfaces, simple spaces from footprint polygons, and a parametric generic building (FR-B11). It does **not** become a modeller. There is no free-form surface editing, no NURBS, no drafting, no wall, roof or stair authoring tools, and no Boolean modelling beyond what healing needs. The line is this: *BuildFOAM changes what geometry means, not what shape it has.* Authoring stays in the BIM tool, because a second modeller would be a second source of truth for the building |
| **NG2** | No cloud or remote compute in v1.x | **Relaxed from 3.x** (DEC-36) | Runs may go to **hosts the user controls**: SSH, Slurm and PBS. BuildFOAM never operates a cloud service, never holds a cloud account on the user's behalf, and never opens a listening socket (§10.1 still holds). Building-scale transient CFD and annual daylight outgrow a laptop, and a practice with a cluster should not have to leave the tool to use it |
| **NG3** | Not replacing ParaView; BuildFOAM launches it | **Relaxed** (DEC-34) | In-app display of **results on planes and surfaces** with colour maps: comfort at occupied-zone heights, wind comfort at pedestrian height, daylight on work planes, façade catch ratios. Compliance and study reports need exactly these images, and a report that must be assembled in a second program is not reproducible. There is no volume rendering, no in-app streamline integration and no general field exploration. **ParaView remains the viewer for everything else** and is still launched as before |
| **NG4** | No native Linux desktop build | **Retained** | Unchanged in substance. The headless paths (the MCP server, and FR-X1's CLI and API) run on Linux, because the services layer is Qt-free (NFR-M1) and CI already runs there. That is not a desktop build. The re-evaluation trigger (≥ 3 institutional requests) stands |
| **NG5** | ESI lineage only in v1.x | **Retained** | The native Windows build (FR-N) is an ESI-lineage build. Foundation support stays additive by design (DEC-15) |
| **NG6** *(new)* | — | **Permanent** | **No licence enforcement, activation, dongle or telemetry-gated features.** A GPL core cannot meaningfully enforce a licence (OD-1 (A) and (C)). Under (C), a proprietary add-on does its own licensing inside its own process |
| **NG7** *(new)* | — | **Permanent** | **No photoreal rendering, VR or multi-user VR in-app** (DEC-38). glTF export (FR-Y1) hands the model to a renderer |
| **NG8** *(new)* | — | **Permanent** | **No executable content in a project, study, pack or template**, and no binary platform serialiser (§10.7). The owner's commercial product embeds compiled scripts in report layouts and serialises projects with a runtime serialiser. Both are code-execution vectors that BuildFOAM will not reproduce |
| **NG9** *(new)* | — | **Permanent** | **No reproduction of an authority's form, logo or seal**, and no claim that a building or the product is "certified", "approved" or "compliant" (DEC-33, §13.12) |

### 2.3 Exclusions — revised

| v1.0 exclusion | v2.0 disposition |
|---|---|
| Mesh-quality visualisation beyond `checkMesh` text | **Retained.** FR-P9 (the pass/warn/fail panel) is the ceiling |
| Chemistry and combustion setup wizards | **Retained**, with one exception: OpenFOAM fire design fires (FR-F6, 3.0). There is still no general combustion wizard |
| Multiphase wizards beyond the `interFoam` template | **Retained**, with one exception: wind-driven rain (FR-W8, 2.2), a fixed template rather than a wizard |
| Optimisation loops | **Retained.** Sweeps (FR-X4) evaluate a grid; they do not search it |
| Scripting and macro recording | **Relaxed.** A documented Python API and a CLI over the services layer (FR-X1), extending DEC-24's agent interface. **Macro recording of GUI actions stays excluded**, and so does a visual node-graph language (DEC-41) |
| Multi-case parameter sweeps | **Relaxed** in 2.2 (FR-X4). They reuse the batch machinery already required by FR-VVM3 |

### 2.4 Priority changes to existing requirements

| ID | v1.0 priority | v2.0 priority | Why |
|---|---|---|---|
| FR-S9 parallel execution | v1.1 | **v1.1, and a prerequisite of Release 2.0** | An indoor study of one office floor is typically 2–10 M cells, and serial runs of that size do not finish in a working day |
| FR-V4 decomposed-case viewing | v1.1 | v1.1 (unchanged). Also applies to the native runtime | — |
| FR-L8 compiled extensions | v2.0 (old ladder) | **2.2** | Needed to build open-source custom solvers (FR-W8) inside WSL and macOS runtimes. On the native runtime they arrive prebuilt, with source (FR-N13) |
| FR-V3 WSL UNC translation | MUST | MUST for WSL. **Not applicable** to the native runtime, where ParaView reads the case directly | — |
| FR-AG1 agent interface | SHOULD | SHOULD, and extended by FR-AG7 | — |

---

## 3. Platform and runtime strategy

§3.1–§3.5 stand. Two amendments apply.

- **Windows is the primary platform for 2.x** (OD-7). macOS gets each engine when that engine passes the platform acceptance suite (§12.4) there. ARM64 Windows is still unsupported: the native build is x86-64.
- **Minimum requirements rise for building studies.** RAM goes to **16 GB minimum, 32 GB recommended** when any 2.x study is used, and free disk to **40 GB**. The v1.0 minimum still applies to v1.x use, and the setup wizard (§7.3 step 2) checks against the tier the user selects.

### 3.6 Native Windows runtime (DEC-26)

A MinGW cross-compiled build of ESI OpenFOAM runs directly on Windows. It needs no WSL, no virtualisation and no Linux distribution. The owner already distributes such a build: ESI-lineage OpenFOAM for platform `linux64MingwDPInt32Opt` (double precision, 32-bit labels), with MS-MPI for parallel runs. It is a fourth `RuntimeSession` implementation, `WindowsNativeSession`, beside `NativeSession`, `WslSession` and `DockerSession`.

| Component | Approach |
|---|---|
| OpenFOAM | **Adoption first.** The runtime manifest's `windows_native` block lists search roots and the MPI launcher's locating variable, and an installed build is found by its layout (FR-N3). An installation put there system-wide by another installer, such as the owner's commercial product, is **adopted**, not duplicated. **Provisioning** adds per-release archive entries to the same block (URL, sha256, signature with the catalog key per FR-L4, and `source`/`recipe` per FR-N13). An archive is unpacked **per user** under the application's local data directory, so it needs **no elevation** (FR-N4) |
| Command bridge | **Direct process creation, with no shell.** `argv[0]` is resolved to `<root>\platforms\<platform>\bin\<name>.exe`. The environment is built *per process* (FR-N2). There is no `bashrc` and no `cmd.exe` |
| Parallel | MS-MPI `mpiexec -n N <solver>.exe -parallel`. The serial and parallel Pstream libraries are chosen by `PATH` order (FR-N5). Installing MS-MPI needs one elevation, requested **only** the first time the user enables parallel runs. A machine that only runs serial needs none |
| ParaView | Native Windows ParaView opens the case by its ordinary path. FR-V3's UNC translation does not apply |
| Case storage | NTFS, under `%USERPROFILE%\<app>\cases` by default. DEC-05's 9p penalty does not exist on this path. What remains of DEC-05 does apply: NTFS is case-insensitive, the build opens files through the ANSI code page, and symlink and path-length behaviour depend on the MinGW runtime. These are handled by FR-N9–N11, not assumed away |

**Why both native and WSL (DEC-26).** The native runtime removes the three worst first-run failures in §9: E-R01 (virtualisation disabled), E-R02 (no administrator rights) and E-R03 (reboot required). It also serves managed lab machines (§14.1) and corporate laptops (§1.2, barrier 7) with no IT request at all. What it costs:

- **The build has to be maintained.** Someone must rebuild it for every ESI release (RISK-17), where WSL gets GPG-signed upstream packages for free.
- **No dynamic code.** `#codeStream`, `coded*` boundary conditions and `codedFunctionObject` need a compiler at run time, and the build has none.
- **Stub decomposition libraries.** `scotch`, `metis` and `kahip` are stubs in the build, so only `simple`, `hierarchical`, `manual`, `multiLevel` and `structured` decomposition works.
- **POSIX shell scripts do not run.** `Allrun`, `foamJob` and `foamLog` are unusable.

WSL therefore stays the fallback on Windows. A case that needs something the native build lacks is detected *before* launch and pointed at WSL (FR-N7, FR-N8), rather than failing mid-run.

> ⚠ **Consequence that must be handled, and a narrowing of NFR-C4.** A MinGW build of OpenFOAM opens files through the active **ANSI code page**. A case path containing a character outside that code page (for example Chinese on a Western-European system) cannot be opened, and `blockMesh` exits 1 without saying why. NFR-C4 promises Unicode paths, and on this runtime that promise is narrowed to *characters representable in the active code page*. FR-N9 refuses any other path **before the run starts**, with E-C18, naming the folder and offering to move the case. The alternative is a solver failure whose message names nothing the user could fix.

### 3.7 Engine manifest

Every external engine is described the same way OpenFOAM is: in data, versioned, and shipped over the content channel independently of the application (§3.4, NFR-M3). `engine-manifest.json` sits beside `runtime-manifest.json`:

```jsonc
{
  "schema": 1,
  "engines": {
    "energyplus": {
      "role": "energy",
      "default": "<version>",
      "support_window": 2,                      // current + previous release
      "releases": {
        "<version>": {
          "windows": { "archive": "<official release zip URL>", "sha256": "…",
                       "exe": "energyplus.exe" },
          "macos":   { "archive": "…", "sha256": "…", "exe": "energyplus" },
          "linux":   { "archive": "…", "sha256": "…", "exe": "energyplus" },
          "input": "epJSON", "schema_file": "Energy+.schema.epJSON",
          "licence": "BSD-3-Clause-like (DOE/NREL)", "redistributable": true
        }
      }
    },
    "radiance":     { "role": "daylight",   "…": "…" },
    "fds":          { "role": "fire",       "…": "…" },
    "ifcopenshell": { "role": "bim-reader", "…": "…" }
  }
}
```

`redistributable` is not decoration. An engine whose licence forbids redistribution (for example, a GPU daylight build that is free for non-commercial use only) is marked `false`. BuildFOAM then only *detects* it and never downloads it (DEC-30).

---

## 4. Architecture

### 4.1 Layers — amended

The rule in §4.1 stands without exception: **the service layer imports no Qt** (NFR-M1, `check_no_qt.py`). 2.x adds services below the same line and engines beside `RuntimeSession`:

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Presentation — PySide6 (foamwb/ui/, the only Qt importer)                 │
│ Shell · Outline · Task pages · Graphics window (Building, Mesh, Maps …)   │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ callbacks / return values (never signals)
┌──────────────────────────────┴────────────────────────────────────────────┐
│ Services (pure Python)                                                    │
│  v1.x: Runtime · Case · FoamDict · Run · Monitor · Content · Guide · V&V │
│  2.x:  Project · Building · Import(ifc|gbxml|hvacobj|…) · Libraries      │
│        Derive(cfd|energy|daylight|fds) · Comfort · Wind · Compliance      │
│        Results(maps) · Report · Script(API/CLI) · Remote (3.x)            │
└───────┬────────────────────┬──────────────────────┬───────────────────────┘
        │                    │                      │
┌───────┴────────┐  ┌────────┴────────┐   ┌─────────┴──────────────────────┐
│ RuntimeSession │  │ Engine sessions │   │ Out-of-process plug-ins        │
│ native · wsl · │  │ EnergyPlus ·    │   │ (optional converters, add-ons; │
│ docker ·       │  │ Radiance · FDS  │   │  never linked, §4.7)           │
│ windows-native │  │ (same contract) │   │                                │
└────────────────┘  └─────────────────┘   └────────────────────────────────┘
```

The three views of the service layer, which are the window, the test suite and the agent interface (DEC-24), become four with FR-X1's CLI and API. All four call the same services and get the same guarantees.

### 4.4 The Engine abstraction (DEC-30)

`RuntimeSession` answered one question: how to run a command in an OpenFOAM environment. Every external engine asks the same question with a different environment, so every engine gets the same contract. Nothing about OpenFOAM's session changes. It becomes one implementation of a more general interface.

| Interface | Responsibility | Key members |
|---|---|---|
| `EngineSession` | Run an engine's command in its environment, own the process tree, translate paths | `run(argv, cwd, env) -> Process`, `to_engine_path()`, `to_host_path()`, `close()`. Identical in shape to `RuntimeSession` (§4.2), which now implements it |
| `EngineLocator` | Find an installed engine; absence is a state, not an error (the pattern of `ParaViewService.locate` and `CadConverter.locate`) | `locate() -> Installation \| None`, `verify(inst) -> EngineStatus` (a canary command, as FR-R5) |
| `EngineProvisioner` | Download, verify and unpack an engine that the manifest marks redistributable | `plan() -> ProvisionPlan` (bytes and paths, shown before anything is written, §7.3 step 4), `provision(plan, progress_cb)`, `remove()` |
| `EngineStatus` | The same contract as `RuntimeStatus`: never "not ready" without a §9 code (FR-R2, §7.9 rule 4) | `state`, `code`, `version` |
| `InputWriter` / `ResultReader` | Per engine: building model → engine input; engine output → result objects | Pure functions over the model. Written input is deterministic, so identical model ⇒ identical bytes (NFR-C7) |

`RunPlan` (§4.3) is engine-neutral already: a stage is an argv, a working directory and a success predicate. A study that runs EnergyPlus for boundary conditions and then OpenFOAM is one plan with two kinds of stage, so DEC-06's machinery and DEC-22's staleness cover it unchanged.

### 4.5 New services

| Service | Responsibility | Notes |
|---|---|---|
| `ProjectService` | Open, save, migrate and validate the project directory (§5.5). Owns the recent-projects list and the project journal (NFR-R3) | Atomic writes (NFR-R2). Unknown keys preserved (NFR-C5) |
| `BuildingModel` | The engine-neutral model (§5.6): queries, adjacency, closure checks, classification | No engine knowledge. No geometry-kernel dependency in the core path |
| `Importers` | IFC (through IfcOpenShell, an optional component), gbXML, `.hvacobj`, STL/OBJ/STEP (existing FR-P3), DXF and 3DM (2.1), OSM and CityGML (2.1) | Each importer writes a provenance record (§5.5) |
| `Libraries` | Materials, constructions, glazing, schedules, zone templates, HVAC terminal types, rule sets, as signed data content (FR-L3, FR-L4) | Each record carries source and licence (§13.10) |
| `Derivation` | Building model → study input: an OpenFOAM case (§5.7), epJSON, a Radiance scene, FDS input | Generator-owned entries only, written through `FoamDict.set` (FR-B26) |
| `Comfort` | ISO 7730, ASHRAE 55, EN 16798 and UTCI indices from sampled fields or point inputs (DEC-32) | Verified against published reference values (§12.7) |
| `Wind`, `Daylight`, `Compliance`, `Fire` | Domain procedures per §6.14–§6.19 | Coefficients and limits come from rule data, never from code (NFR-M9) |
| `ResultMaps` | Sample result fields onto planes and surfaces; colour scales; images for reports | Reads OpenFOAM `surfaces` output, Radiance grids and FDS slices |
| `ReportService` | Extended from v1.1 (FR-V6) to study reports (FR-V7) and compliance reports (FR-K4) | Generated from templates that are data. No layout scripts (NG8) |

### 4.6 Project, study and case

A **project** holds one building model and any number of **studies**. A **CFD study is exactly a v1.0 case**: a directory holding a plain OpenFOAM case tree with its `.buildfoam/case.json`. It therefore gets every v1.0 editor, guarantee and test for free. An energy, daylight or fire study is likewise a directory holding that engine's native input, plus BuildFOAM's metadata.

Deleting the project file leaves every study runnable from its engine's own command line. This is FR-C7 generalised (NFR-C2).

### 4.7 Out-of-process plug-ins (DEC-31)

Anything whose licence cannot sit inside a GPL-3.0 process runs as a **separate program**. That includes proprietary format converters and, under OD-1 (C), proprietary add-ons. The contract is deliberately narrow: files in, files out, progress on stdout.

- **Discovery.** A plug-in ships a manifest naming its role (`converter:rvt→ifc` and so on), its version, its licence and its executable. BuildFOAM *finds* plug-ins; it never downloads or bundles one (the `cad.py` precedent).
- **Invocation.** `argv` only, as a token list. Input and output are **open formats** (IFC, STL, JSON). Progress and errors are JSON lines on stdout and stderr.
- **Never** loaded into BuildFOAM's process, never passed a Python object, never handed credentials. A plug-in's failure is a §9 code (E-B08), not an exception.

---

## 5. Data model

§5.1–§5.4 stand. A CFD study's case keeps §5.1's classification, and §5.2's `case.json` gains a `derived_from` block (§5.7).

### 5.5 The project format (DEC-28)

A project is a **directory** of UTF-8, LF-terminated JSON files and plain asset files, exchanged as a zip. It is never a binary serialisation. The directory extension (`.bfproj`) is a constant beside `APP_ID` in `branding.py` (NFR-M5).

```
riverside-office.bfproj/
├── project.json            # schema, app version, units (SI), site, north angle, weather ref, ids
├── building/
│   ├── model.json          # buildings, storeys, spaces, zones, surfaces, openings, components
│   └── bodies/<id>.ply     # non-planar bodies only: context, furniture, imported meshes
├── libraries/              # project-local copies of every library record the model uses
│   ├── materials.json · constructions.json · glazing.json · schedules.json · terminals.json
├── mappings/
│   └── element-bc.json     # the user's overrides of the default mapping (§5.7), nothing else
├── climate/<name>.epw      # weather files the user supplied (never bundled, §13.10)
├── sources/<sha256>.<ext>  # imported files, byte-for-byte, by content hash (optional)
├── provenance.json         # every import: file hash, importer version, mapping used, healing done
└── studies/
    ├── s-0001-level3-ventilation/   # a plain OpenFOAM case (+ .buildfoam/case.json)
    └── s-0002-annual-energy/        # an epJSON study (+ .buildfoam/study.json)
```

Rules, each the consequence of an alternative the owner's commercial product exhibits:

1. **No binary serialiser, ever. No `pickle`, no code.** A binary platform serialiser ties the format to one runtime and version, cannot be read by anything else, and is a known remote-code-execution class on load (§10.7). JSON can be read by every language and every future version of this tool.
2. **Stable, diffable output.** Keys are sorted within each object, indentation is two spaces, and there is a trailing newline. A project kept in version control produces a meaningful diff, which is D4 carried from dictionaries to projects.
3. **Unknown keys are preserved (NFR-C5).** A newer version's fields survive a save by an older version. This is FR-P7's byte-fidelity promise, restated for JSON as fidelity of *content*.
4. **Versioned schema, forward migration only.** `schema` is an integer. An older project is migrated on open, and the original is kept as `project.json.v<N>.bak`. A project from a *newer* schema opens read-only with E-B09, never half-understood.
5. **Geometry is honest about what it is.** Building surfaces are planar polygons with holes, stored as coordinate loops in metres in project coordinates, and the georeference offset is recorded in `project.json` (FR-B8). Meshes that are not planar surfaces are PLY files, never base64 inside JSON.
6. **Studies are directories, not archive members.** OpenFOAM cases must be directories, so the zip is only for exchange and archiving.
7. **A published JSON Schema** (`docs/schema/project-<N>.json`) is part of each release. The format is documented to the point where a third party (including the owner's commercial product, OD-10) can write it.

### 5.6 The building model

| Entity | Key properties | Notes |
|---|---|---|
| **Project** | id, name, schema, units (always SI internally), site (latitude, longitude, elevation, time zone), north angle, weather file reference, georeference offset | One building model per project |
| **Building** | id, name, use type (from a data catalogue), year, gross and net areas (derived) | A campus is several buildings |
| **Storey** | id, elevation, nominal height | From IFC `IfcBuildingStorey` or user-defined |
| **Space** | id, name, number, storey, use-template reference, **air volume (a closed polyhedron)**, derived floor area and volume, occupancy | The unit a CFD study selects. Must be closed to be derivable (FR-B7) |
| **Zone** | id, member spaces, use template | Thermal zoning for energy (FR-E2). Independent of spaces, because thermal zoning is a modelling decision |
| **Surface** | id, **element type** (§5.7), polygon, owning space(s), **adjacency** (outdoors, ground, another space, adiabatic), construction reference, source element (IFC `GlobalId`) | The unit a patch is built from. Second-level space boundaries where available (FR-B2) |
| **Opening** | id, kind (window, door, skylight, louvre, open void), parent surface, polygon, glazing or construction reference, state (closed, open, fraction open) | An open opening becomes a flow boundary. A closed one becomes a wall of its construction |
| **ShadingSurface** | id, polygon or body, kind (overhang, fin, neighbour, tree canopy) | Context and external shading |
| **Component** | id, **type** (HVAC terminal, heat source, sensor, obstruction), placement (host surface and position, or free), parameter set, library type reference | HVAC terminals and heat sources (FR-H) |
| **Construction** | id, layers (material and thickness), derived U-value (ISO 6946 procedure), surface properties (absorptance, emissivity, roughness), source and licence | Shared by CFD thermal boundaries and energy |
| **Material**, **GlazingSystem**, **Schedule**, **UseTemplate** | Physical and optical properties; hourly profiles; bundles of loads and setpoints | Library records (§4.5) |
| **SensorGrid** | id, plane or surface, spacing, height | Used by comfort maps, daylight and wind comfort |

The **element-type catalogue** (external wall, internal wall, ground floor, intermediate floor, roof, window, glazed door, door, skylight, shading, supply terminal, return terminal, exhaust terminal, heat source, person, obstruction, opening and others) is a data file with display names, colours and default mappings. The owner's commercial product has a 45-value classification. `.hvacobj` import maps it onto this catalogue through a mapping table in data (§5.8), not in code.

### 5.7 Mapping the building to an OpenFOAM case (DEC-29)

Derivation is a pipeline. Each step writes to `provenance.json`, so every patch can be traced back to the building elements it came from.

1. **Scope.** The user selects spaces, a storey, or the building exterior (for wind studies).
2. **Fluid domain.** For an indoor study, the union of the selected spaces' air volumes. Openings between selected spaces are merged; openings to unselected spaces or to outdoors become boundaries. The result is a closed, oriented surface. BuildFOAM places `locationInMesh` automatically inside the largest selected space, and the user can override it.
3. **Patch grouping.** Surfaces are grouped by *(element type, construction, adjacency, the BC parameters that matter)*, not one patch per element. A floor with 400 identical wall panels gets one external-wall patch per orientation, not 400 patches. The grouping keys are data. The user can split any group (FR-B22).
4. **Boundary conditions.** For each group, the **default BC set for the chosen solver family** comes from a mapping data file keyed by manifest version (NFR-M3). **Turbulence-field BCs are not in this mapping.** They remain owned by the turbulence advisor (FR-VVT4), so model, wall treatment and mesh cannot disagree, as §6.9.1 requires.
5. **Write.** Generator-owned entries are written through `FoamDict.set`, and nothing else in the file is touched (FR-P7, FR-B26).

The mapping data, abridged. **The data file is authoritative**; this table illustrates its shape, and the BC names are drawn from the ESI stock set that the manifest says the release provides:

| Element type (adjacency) | Patch group name | `U` | `p_rgh` | `T` |
|---|---|---|---|---|
| External wall / roof (outdoors) | `wallExt_<orientation>` | `noSlip` | `fixedFluxPressure` | `externalWallHeatFluxTemperature` (coefficient mode, h and T from climate, layers from the construction) |
| Internal wall (to an unselected space) | `wallInt` | `noSlip` | `fixedFluxPressure` | `zeroGradient` (adiabatic) or `fixedValue`, per the user's choice |
| Ground floor (ground) | `floorGround` | `noSlip` | `fixedFluxPressure` | `fixedValue` (ground temperature) |
| Window, closed | `glazing_<orientation>` | `noSlip` | `fixedFluxPressure` | `externalWallHeatFluxTemperature` (U-value). Solar gain is a heat-flux term, stated as simplified (FR-B24) |
| Window or door, open (outdoors) | `opening_<id>` | `pressureInletOutletVelocity` | `prghTotalPressure` | `inletOutlet` |
| Supply terminal | `supply_<id>` | `flowRateInletVelocity` | `fixedFluxPressure` | `fixedValue` (supply temperature) |
| Return or exhaust terminal | `extract_<id>` | `flowRateOutletVelocity` | `fixedFluxPressure` | `inletOutlet` |
| Person / heat source | `heat_<type>` | `noSlip` | `fixedFluxPressure` | `externalWallHeatFluxTemperature` (power mode, W) |

```jsonc
// data/bim/element-bc/esi/buoyant.json — abridged
{ "schema": 1, "solver_family": "buoyant", "fields": ["U","p_rgh","T"],
  "rules": [
    { "element": "supply_terminal",
      "patch": { "name": "supply_{id}", "type": "patch" },
      "bc": { "U": { "type": "flowRateInletVelocity",
                     "volumetricFlowRate": "{component.flow_rate}" },
              "T": { "type": "fixedValue", "value": "uniform {component.supply_temperature}" } } }
  ] }
```

A derived case records its origin in `.buildfoam/case.json`: `"derived_from": {"project": "<id>", "model_hash": "sha256:…", "mapping": "<file>@<hash>", "elements": {"supply_12": ["<surface ids>"]}}`. This record is what lets a patch click select building elements, and what lets DEC-22 mark the case **↻ out of date** when the model changes (FR-B26).

### 5.8 The `.hvacobj` importer

The owner's `.hvacobj` format is line-oriented text. The owner has documented it and supplies the specification for this implementation (§13.11). BuildFOAM **reads** it from 2.0 so that object libraries and device models carry across, and **writes** it from 2.1 (FR-B4) for round-trips during any transition period.

- **Read:** `//` comments; section tags with `(name[,parent])`; mesh, polyface and polyline geometry with their index rules (indices in triples, no repeated closing vertex, normal and UV list lengths); the tree tags (group, building, floor, space); classification (mapped through a data table onto §5.6's catalogue); material colours and maps; construction names (resolved against the libraries); the CFD primitives (`searchableBox`, `searchableSphere`, `searchableCylinder`, `triSurfaceMesh`) as refinement regions; location points; sensors.
- **Refused, and reported, never executed:** any `[Data]` block. It is a base64 binary-serialiser payload, and decoding it is exactly the code-execution risk §10.7 forbids. It is skipped with an E-B10 finding that names the line. `[BoundaryCondition]` payloads are preserved as opaque notes until the owner documents their encoding.
- **Embedded files** (`[Texture]`, `[Filedata]`) are kept only when their bytes are a recognised image format, and are otherwise dropped with a finding.

---

## 6. Functional requirements

v1.0's §6.1–§6.10 stand unchanged, with the priority changes in §2.4. For new requirements the **Pri** column names the **release tier** (2.0, 2.1, 2.2, 3.0, 3.x) and MUST or SHOULD within it. "MUST (whenever it ships)" means the same as in v1.0: whenever the module ships, this ships with it.

### 6.11 Native Windows runtime (FR-N)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-N1 | Implement `WindowsNativeSession`: create each process directly from an argv token list, with no shell and no `cmd.exe`. | 2.0 MUST | A case path containing a space, `&`, `%` and `^` reaches the solver as one argument. No code path builds a command string (asserted by test). |
| FR-N2 | Build each process's environment from the manifest: `WM_PROJECT_DIR`, the other `WM_*`/`FOAM_*` variables the build needs, and `PATH` **prepended** with the build's `bin` and `lib` directories and the selected Pstream directory. **Never** modify the system environment, and never depend on it. | 2.0 MUST | With a second, different OpenFOAM installation on the system `PATH`, every stage runs the manifest's build (verified from the banner). With the system variables removed, runs still succeed. |
| FR-N3 | Detect native builds: `WM_PROJECT_DIR` first, then the manifest's search roots, then a user-specified root. Recognise a build **by its layout** (`platforms/<arch>/bin/blockMesh.exe`), not by the architecture string, and read its release from `META-INFO/api-info`, not from the directory name. Verify it with a canary (`blockMesh -help`). The shell-script `foamVersion` is not usable. | 2.0 MUST | A corrupted `bin` directory is reported `broken` (E-R07), not `ready`. An API mismatch is E-C07. |
| FR-N4 | Provision a build per user from its signed archive with **no elevation**. Adopt an existing installation in place instead of duplicating it. | 2.0 MUST | On a standard-user account on a clean Windows 11 machine, the wizard reaches `ready` with no UAC prompt (M-8). An existing system-wide install is adopted with no download. |
| FR-N5 | Parallel runs through MS-MPI: `mpiexec -n N <solver>.exe -parallel`, with `mpiexec` located through the manifest's variable (`MSMPI_BIN`). Parallel stages put the MS-MPI Pstream first on `PATH`. Serial stages use it when MS-MPI is present and the serial stub otherwise, so a machine without MS-MPI still runs serially rather than failing with a missing-DLL status. Install MS-MPI only on first use of parallel, with one elevation. | 2.0 MUST | A corpus case on 4 processes matches its serial result within §12.3 tolerances. With MS-MPI absent, parallel is disabled with E-N02 and serial runs are unaffected. |
| FR-N6 | Own the whole process tree, including the ranks `mpiexec` starts. *Stop & Write*, the default, is unchanged (the `abort` trigger file, FR-S5). Windows console programs have no SIGTERM, and a child without its own console cannot be sent a break, so *Stop Now* and *Force Kill* both end the tree forcefully (`taskkill /T /F`). The UI must say so, since *Stop Now* is not graceful here. The tree SHOULD also be held in a **Job Object** with kill-on-close, so the application's own crash ends it too. | 2.0 MUST | FR-S10 passes on the native runtime. Force-quitting the application mid-run under `mpiexec` leaves no `mpiexec`, `smpd` or solver process. |
| FR-N7 | The decomposition methods a build supports are declared in the manifest. The UI offers **only** those. | 2.0 MUST | Choosing `scotch` on a build whose manifest lacks it is impossible, not merely warned about. A hand-edited `decomposeParDict` naming it produces E-N04 before launch. |
| FR-N8 | Detect dynamic code (`#codeStream`, `coded*` BCs and function objects) before launch on a build declared `dynamic_code: false`, and offer the WSL runtime for that case. | 2.0 MUST | A corpus case containing `#codeStream` yields E-N05 at plan time, never a solver crash. |
| FR-N9 | Before any stage starts, refuse a case path containing characters outside the active ANSI code page, with E-C18 naming the offending folder and offering *Move to a supported location* (§3.6). | 2.0 MUST | A case under a folder named in a script outside the code page is refused before launch. A path inside the code page, including accented Latin characters on a Western-European system, runs. |
| FR-N10 | Detect field or file names that differ only by case (for example `U` and `u`) and would collide on NTFS. | 2.0 MUST | Importing a case with such a pair yields E-N08, naming both files, before any write. |
| FR-N11 | Warn when a case path approaches the Windows path-length limit, or sits under real-time antivirus scanning known to slow small-file writes. **Advisory only**: BuildFOAM never changes antivirus exclusions. | 2.0 SHOULD | A case whose deepest expected file path exceeds 240 characters triggers E-N07. The antivirus guide page says what to ask IT for. |
| FR-N12 | The M2 acceptance suite and the §12.3 golden-case gate pass **unchanged** on `WindowsNativeSession`. | 2.0 MUST | CI (or the §12.4 manual suite until a Windows runner exists) records a pass. |
| FR-N13 | Any native build BuildFOAM downloads or adopts by manifest carries a `source` URL for its Corresponding Source and a `recipe` reference for its reproducible build (§13.7). | MUST (whenever it ships) | A release check fails if any `windows_native` entry lacks `source` or `recipe`. |
| FR-N14 | `RunPlan` never depends on a POSIX script (`Allrun`, `foamJob`). Importing a tutorial whose `Allrun` holds steps a plan cannot represent lists those steps. | 2.0 MUST | Every corpus case with an `Allrun` either plans fully or names the unrepresentable lines. |
| FR-N15 | Choose the default runtime: native when the manifest holds a verified native build for the default version, otherwise WSL. A case may be pinned to a runtime kind in `case.json`. | 2.0 MUST | The wizard's plan screen (§7.3 step 4) names the chosen kind and why. A pinned case opens on its runtime. |

### 6.12 Building model and derivation (FR-B)

#### 6.12.1 Import and model

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-B1 | Import IFC2x3 and IFC4, and IFC4.3 SHOULD, through IfcOpenShell as an optional component: storeys, spaces, elements and their classes, material layer sets, property sets, openings, and each element's `GlobalId`. Off the GUI thread, cancellable. | 2.0 MUST | Every file in the reference IFC corpus (§12.9) imports, or fails with a specific E-B code. Element counts per class match an independent IfcOpenShell query. |
| FR-B2 | Use second-level space boundaries when present. Otherwise derive surfaces and adjacency from space and element geometry. The import report states which method each space used. | 2.0 MUST | For corpus files that carry boundaries, derived adjacency agrees with them for ≥ 95% of surface area. |
| FR-B3 | Import gbXML (campus, building, space, surface, opening, construction references). | 2.0 SHOULD | The gbXML corpus files import with surface-type and adjacency agreement to their source. |
| FR-B4 | Import `.hvacobj` per §5.8. Export it from 2.1. | 2.0 MUST (import), 2.1 SHOULD (export) | The owner's sample library imports. `[Data]` blocks are skipped with a finding and never decoded. Re-exporting an imported object round-trips its geometry, tree and classification. |
| FR-B5 | Existing STL, OBJ and STEP imports (FR-P3) enter the building model as **unclassified bodies**, which can then be classified. | 2.0 MUST | An STL room can be classified surface by surface and derived like an IFC space. |
| FR-B6 | Classify every surface through a data mapping from source class to element type. An unmapped class becomes *Other* with a finding, never a silent default. Mapping overrides are saved in the project. | 2.0 MUST | Every corpus element receives a type or a finding. An override survives save and reopen and re-derivation. |
| FR-B7 | Check each space for closure, overlaps, gaps and normal orientation. Heal gaps below a stated tolerance, and record each healing action in `provenance.json`. Locate every defect in the 3D view. | 2.0 MUST | M-7 holds. Every unhealed defect is an E-B05 finding that selects its location in one click. |
| FR-B8 | Detect IFC units. Translate a georeferenced model far from the origin to a local origin and record the offset. | 2.0 MUST | A corpus model placed 10⁶ m from the origin meshes without precision loss, and exports back in its original coordinates. |
| FR-B9 | Read and write the project format (§5.5) with schema migration, preservation of unknown keys, and a published JSON Schema. | 2.0 MUST | Round-trip: open and save with no edit ⇒ byte-identical JSON. A project from a newer schema opens read-only with E-B09. |
| FR-B10 | Provide no reader for the owner's legacy binary project format (DEC-37). Import the open format written by any exporter the owner provides (OD-10). | 2.0 MUST | No code path deserialises a binary platform serialiser (asserted by the dependency and AST guard, §10.7). |
| FR-B11 | Light authoring (NG1's boundary): a space from a footprint polygon and height; openings by window-to-wall ratio on selected façades; storeys. A parametric generic building from template data follows in 2.1. | 2.0 SHOULD, 2.1 MUST (generic building) | A single-room study can be built and derived with no import at all. |
| FR-B12 | Import urban context: OSM footprints and heights (with ODbL attribution), CityGML LOD1 and LOD2, and terrain from a DEM grid. | 2.1 MUST | A 500 m radius of an OSM city block becomes a closed context model. Attribution appears in the project and in every report that uses it. |
| FR-B13 | Import DXF (through ezdxf) as a tracing underlay for footprints. Import 3DM (through rhino3dm). | 2.1 SHOULD | A DXF floor plan's closed polylines become space footprints. |
| FR-B14 | Export gbXML (2.1) and IFC (2.2), with study results attached as property sets. | 2.1/2.2 SHOULD | The exported file re-imports with no loss of classification. |
| FR-B15 | Revit, DWG and SketchUp formats **only** through an out-of-process converter plug-in (§4.7, OD-8). With none installed, E-B08 names the IFC or DXF export route from the authoring tool. | Any tier | No proprietary SDK is linked into, or shipped with, the application (asserted by an SBOM check). |

#### 6.12.2 Derivation to CFD

Identifiers start at FR-B20, so import requirements can grow without renumbering.

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-B20 | Create a CFD study from a scope (spaces, a storey, or the exterior) and a physics choice (isothermal or buoyant; steady or transient; with or without humidity or scalars). The solver is chosen from a data table of solver capability flags, filtered by the installed manifest. | 2.0 MUST | Every combination the table offers produces a case that passes `checkMesh` and runs. A combination the installed build cannot run is not offered. |
| FR-B21 | Extract the fluid domain per §5.7 step 2, with `locationInMesh` placed automatically. Doors between selected spaces are open or closed as the user chooses. | 2.0 MUST | For every closed corpus space, `snappyHexMesh` produces a single region containing the location point. A leak is reported with the gap located (E-B05), never as a mesh of the outside world. |
| FR-B22 | Group surfaces into patches per §5.7 step 3, and record the element ids behind each patch. Clicking a patch in the Mesh document selects its elements in the Building document, and the reverse. | 2.0 MUST | Patch count is independent of element count for identical elements. Selection is two-way on every corpus study. |
| FR-B23 | Default BCs come from the mapping data (§5.7 step 4). A missing rule is an E-B07 finding, never an invented default. | 2.0 MUST | Deleting a mapping rule yields E-B07 naming the element type and the solver family. |
| FR-B24 | Thermal BCs from constructions: external surfaces take the construction's layers and a climate-derived exterior condition. Glazing takes its U-value and a solar-gain flux from sun position and g-value. The UI and the report label this **simplified**. It is superseded by FR-E5 when an energy study exists. | 2.0 MUST | For a single-layer wall, the steady conductive heat flux through it matches the hand value within 2%. |
| FR-B25 | Physics beyond the stock solvers (for example coupled humidity) is offered **only** where the installed build provides a solver *with published source* (DEC-32, §13.7), or as a labelled approximation (humidity as a passive scalar). | 2.1 SHOULD | The approximation is labelled on every result derived from it. |
| FR-B26 | Changing the building model marks derived studies **↻ out of date** (DEC-22). Re-derivation rewrites only generator-owned entries through `FoamDict.set`, and shows a diff before writing. Hand edits to other entries survive. | 2.0 MUST | Hand-edit an `fvSolution` tolerance, change a diffuser flow rate, re-derive: the tolerance is byte-identical and only the `U` entry changed (FR-P7). |
| FR-B27 | A derived study is a plain OpenFOAM case. Deleting the project and `.buildfoam/` leaves a case that runs from a bare solver invocation. | 2.0 MUST | Automated for every study template (§12.3, FR-C7). |
| FR-B28 | Mesh sizing defaults come from the model: background cell size from room size, refinement near terminals and heat sources, surface layers per wall treatment (FR-VVT4). The cell count and memory are estimated **before** meshing. | 2.0 MUST | The estimate falls within ±30% of the actual cell count on the corpus. An estimate beyond available RAM warns before launch. |

### 6.13 HVAC objects and libraries (FR-H)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-H1 | A library of terminal types (square and linear diffusers, swirl diffuser, jet nozzle, grille, displacement unit, exhaust valve). Each is data: a geometry proxy, a BC template, and parameters with units. | 2.0 MUST | Each type places, derives and runs in a single-room study. |
| FR-H2 | Place terminals on host surfaces (snapped, oriented), with flow rate, supply temperature and, optionally, humidity and scalar concentration. Each terminal becomes its own patch. | 2.0 MUST | Moving a terminal after derivation marks the mesh stale (DEC-22). |
| FR-H3 | State the diffuser modelling method explicitly: simple opening, box method or momentum method. Name the method's known limitations. Throw data comes from the manufacturer only if the user supplies it. | 2.0 MUST | Every terminal's task page and the study report name the method. |
| FR-H4 | Heat sources: people (activity level from a data table, sensible heat), equipment, lighting and heaters. Each is a surface flux on a proxy body or a volumetric source (`fvOptions`), chosen explicitly. | 2.0 MUST | The total heat input the case receives equals the sum of the declared sources within 1% (a heat-balance function-object check). |
| FR-H5 | Air quality: CO₂ per person and user contaminants as passive scalars. Age of air where the installed release provides a function object for it (from the manifest). Air-change effectiveness and contaminant removal effectiveness computed in services. | 2.0 SHOULD | In a perfectly mixed test room, air-change effectiveness is 1.0 ± 0.05. |
| FR-H6 | Supply–extract balance check before launch: Σ supply = Σ extract + declared leakage. | 2.0 MUST | An unbalanced room produces a finding with the imbalance in m³/s, before any run. |
| FR-H7 | Recirculation links (extract temperature feeds supply) only through stock BCs available in the manifest. | 2.1 SHOULD | The linked case runs on the default release with no custom library. |
| FR-H8 | Libraries are signed data content (FR-L3, FR-L4), with user import and export in JSON and `.hvacobj`. | 2.0 MUST | A tampered library pack is rejected (E-L01). |
| FR-H9 | Manufacturer product data is **user-supplied only**. No manufacturer name or data is bundled without written permission. | MUST (whenever it ships) | The bundled catalogue contains generic types only. |
| FR-H10 | System-level plant (boilers, chillers, loops, pipes) exists only as EnergyPlus ideal loads in FR-E. Detailed plant modelling is not planned. | — | — |

### 6.14 Thermal comfort (FR-T) — DEC-32

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-T1 | ISO 7730 PMV, PPD and draught rate from CFD fields: through the release's stock comfort function object where the manifest lists one, and otherwise through the services implementation over sampled fields. | 2.0 MUST | Both paths agree within 0.05 PMV on the corpus. Both match §12.7's reference values. |
| FR-T2 | Mean radiant and operative temperature, from the radiation model's fields or from surface temperatures and view factors. The method is always stated. | 2.0 SHOULD, 2.1 MUST | For a uniform-temperature enclosure, MRT equals the wall temperature within 0.1 K. |
| FR-T3 | A point calculator with no CFD: all FR-T1 and FR-T4 indices, clothing and activity from data tables. | 2.0 MUST | Matches §12.7 exactly. |
| FR-T4 | ASHRAE 55 (PMV with SET-based elevated air speed, adaptive model) and EN 16798-1 (categories, adaptive). | 2.1 MUST | Matches §12.7. |
| FR-T5 | Outdoor UTCI from air temperature, humidity, wind at 10 m equivalent and MRT outdoors. It draws on FR-W and FR-D9. | 2.2 MUST | Matches the published UTCI reference implementation to its stated precision. |
| FR-T6 | Local discomfort: vertical air-temperature difference, radiant asymmetry and floor temperature, each against its standard's bands (from data). | 2.1 SHOULD | Each is computed for the corpus study and appears in the report. |
| FR-T7 | **Inputs outside an index's validity range are flagged (E-T01), never silently extrapolated.** The value is shown with the violated bound. | MUST (whenever it ships) | A test with activity outside ISO 7730's stated range shows the flag on the point value, the map and the report. |
| FR-T8 | Comfort maps at occupied-zone heights and wall offsets, defined per standard in data, with the occupied-zone definition drawn on the map. | 2.0 MUST | Maps render at every height the standard defines. The legend states the standard and edition. |
| FR-T9 | Human thermophysiology co-simulation through a **user-supplied** FMU (FMI 2.0 or 3.0, loaded in a separate process). None is bundled (§13.6). | 3.x SHOULD | A reference FMU exchanges per-segment fluxes and temperatures with a running case. |

### 6.15 Energy simulation (FR-E)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-E1 | Detect, verify and provision EnergyPlus through the Engine abstraction and the engine manifest (§3.7). | 2.1 MUST | As FR-R1 and FR-R5, for EnergyPlus on Windows and macOS. |
| FR-E2 | Write epJSON from the building model: zones, surfaces with adjacency, constructions, materials, glazing, schedules, internal loads from use templates, ideal-loads systems, and site and weather. | 2.1 MUST | M-9: every study input runs unmodified with `energyplus`. Identical model ⇒ identical bytes (NFR-C7). |
| FR-E3 | Run it with streamed output. Parse `.err` by severity, and summarise a fatal error by its first severe message, with a guide link. | 2.1 MUST | An induced missing-construction error yields E-E03 naming the object. |
| FR-E4 | Read results from EnergyPlus's SQLite output: zone temperatures, loads, surface temperatures and energy by end use. Show charts, and colour the 3D model by result. | 2.1 MUST | Values match EnergyPlus's own tabular report on the corpus. |
| FR-E5 | One-way coupling to CFD: surface temperatures or heat fluxes at a chosen hour become a CFD study's thermal BCs, with the hour and weather file recorded. | 2.1 MUST | The coupled case's wall BCs equal the SQLite values for that hour. The provenance strip names them. |
| FR-E6 | Libraries for materials, constructions (with the ISO 6946 U-value shown), glazing, schedules and use templates, each record carrying source and licence (§13.10). | 2.1 MUST | No record without `source` and `licence` loads (a library validator). |
| FR-E7 | Design days and ideal-loads sizing: peak heating and cooling per zone. | 2.1 MUST | Matches EnergyPlus's own sizing report. |
| FR-E8 | Import existing epJSON or IDF models into the building model (geometry, constructions, schedules). | 2.2 SHOULD | The corpus IDFs import, and re-export runs. |
| FR-E9 | Append raw epJSON objects, fenced and disclosed (NFR-C3's rule applied to engine input). | 2.1 SHOULD | Removing the fence restores the generated input byte-identically. |
| FR-E10 | Condensation risk by the Glaser method (ISO 13788) in the construction editor. | 2.2 SHOULD | Matches a worked example (§12.11). |
| FR-E11 | Regional load and summer-overheating procedures (for example VDI 2078, DIN 4108-2, EN 12831) as rule packs under OD-4 and §13.9. | 3.x | Each pack reproduces its standard's worked examples. |

### 6.16 Wind, urban flow and wind-driven rain (FR-W)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-W1 | Analyse an EPW's wind: sectors, wind rose, calm hours, quantiles and the dominant sector. | 2.1 MUST | Sector frequencies match an independent computation. |
| FR-W2 | Build an exterior domain per published best-practice guidelines (COST 732, AIJ): upstream, downstream and lateral distances and height in multiples of H, and a blockage-ratio limit. All values in data, with the guideline cited. | 2.1 MUST | A domain violating the blockage limit is refused with E-W02, stating the ratio. |
| FR-W3 | Atmospheric-boundary-layer inflow through the stock ABL BCs and rough-wall functions, with z₀ consistent between inlet and ground. Offer an **empty-domain homogeneity test**, and report the profile decay. | 2.1 MUST | The empty-domain test reports the velocity-profile change at the building position. A decay beyond 10% is flagged (E-W04). |
| FR-W4 | Run several wind directions as one batch through the `RunPlan` batch machinery (FR-VVM3's), surviving a failed direction. | 2.1 MUST | Twelve directions complete, or report which failed. |
| FR-W5 | Pedestrian wind comfort: combine per-direction speed-up factors with EPW frequencies into exceedance probabilities, classified by a criteria set from data (Lawson and Davenport; others per §13.9). Maps at 1.5–2 m. | 2.1 MUST | For a synthetic climate with a single direction, the exceedance equals that direction's frequency. |
| FR-W6 | Trees and vegetation as porous canopy sources, where the release provides them. | 2.1 SHOULD | A canopy case runs on the default release. |
| FR-W7 | Natural ventilation: flow through openings and air change rates of spaces in an indoor–outdoor coupled study. | 2.2 MUST | Per-opening flows sum to zero within 1% per space. |
| FR-W8 | Wind-driven rain with an Eulerian multiphase solver **whose source is published** (GPL). Drop-size classes are literature data with citation. The output is catch ratios on façades. Built through FR-L8 on WSL and macOS, and prebuilt with source on native Windows. | 2.2 SHOULD | The solver's published validation case reproduces within its paper's reported tolerance. |

### 6.17 Daylight and solar (FR-D)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-D1 | Detect, verify and provision Radiance through the Engine abstraction. | 2.2 MUST | As FR-E1. |
| FR-D2 | Export a Radiance scene from the building model: geometry, optical properties from constructions and glazing, and sensor grids on work planes. | 2.2 MUST | M-9 for `rtrace` on the corpus. |
| FR-D3 | Daylight factor under a CIE overcast sky, illuminance at a time, luminance images and false colour. | 2.2 MUST | §12.10's analytic cases pass. |
| FR-D4 | Climate-based metrics from an EPW through daylight coefficients: annual illuminance, spatial daylight autonomy, annual sunlight exposure and useful daylight illuminance. Metric definitions and thresholds are data. | 2.2 MUST | Results match a reference run of the same Radiance commands to 1%. |
| FR-D5 | Daylight glare probability via `evalglare` for a stated view. | 2.2 SHOULD | Matches `evalglare` run by hand on the same image. |
| FR-D6 | Daylight provision per EN 17037, with targets as data. | 2.2 SHOULD | Worked example (§12.11). |
| FR-D7 | 360° panoramas from Radiance. This replaces the owner's VR use case (NG7). | 2.2 SHOULD | An equirectangular image opens in a standard viewer. |
| FR-D8 | GPU-accelerated Radiance builds are **detected only**, never downloaded, where their licence restricts redistribution (§3.7). | MUST (whenever it ships) | Manifest entries with `redistributable: false` are never offered for download. |
| FR-D9 | Sun position, shadow studies, sunlight hours and annual irradiance on surfaces, computed internally with no engine. | 2.2 MUST | Sun position matches a published algorithm's reference values to 0.01°. |

### 6.18 Compliance (FR-K) — DEC-33, DEC-39

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-K1 | A rule-set framework. Each rule set is a signed data pack: jurisdiction, name, **edition**, coefficients, limits, tables, source citation and **licence**. Calculators implement named procedures and take all numbers from the pack. | 2.2 MUST | A calculator run with a modified pack changes its output accordingly. `grep` finds no rule coefficient in code (NFR-M9). |
| FR-K2 | Envelope heat-gain rules (for example ETTV and RETV), including external-shading coefficients from table look-up or from BuildFOAM's own sun-path ray trace. | 2.2 MUST (first pack per OD-4) | The pack's published worked examples reproduce exactly (§12.11). |
| FR-K3 | Further envelope packs (for example OTTV variants), gated by §13.9. | 2.2 SHOULD / 3.x | As FR-K2. |
| FR-K4 | A calculation report: the inputs, per-façade tables, the U-value appendix and the cited rule edition. It does **not** reproduce an authority's form, logo or seal (NG9). | 2.2 MUST | The report lists every input with its source (model element, library record or user entry). |
| FR-K5 | Verdict wording per DEC-33: "computed value V meets / does not meet the numerical limit L of <rule, edition, clause>". Never "compliant", "certified" or "approved". | MUST (whenever it ships) | A string check over the rendered report finds none of the forbidden words. |
| FR-K6 | A natural-ventilation simulation procedure for rating schemes that prescribe one, using FR-W7. | 2.2 SHOULD | The procedure's prescribed outputs are produced and labelled. |
| FR-K7 | Daylight-credit summaries (for example sDA and ASE thresholds) using FR-D4. | 2.2 SHOULD | Thresholds come from the pack. |
| FR-K8 | Sustainability ratings, LCA and LCC (for example BNB, or EPD-based LCA): 3.x, under OD-4 and §13.9/§13.10. | 3.x | — |
| FR-K9 | A rule set whose licence is missing or unverified cannot load (E-K04). | MUST (whenever it ships) | An unsigned or unlicensed pack is refused. |
| FR-K10 | Every compliance output carries a provenance strip: rule-set id and edition, pack hash, model hash, library record hashes and tool version (as §7.7 does for V&V). | MUST (whenever it ships) | Changing any input changes the strip. |

### 6.19 Fire (FR-F)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-F1 | Detect, verify and provision FDS and Smokeview through the Engine abstraction. | 3.0 MUST | As FR-E1. |
| FR-F2 | Generate FDS input from the building model: meshes aligned to the model, obstructions voxelised from elements at cell size, vents from openings, surfaces from constructions, a fire with an HRR ramp (t² growth classes as data), and devices (sprinklers, detectors, thermocouples). | 3.0 MUST | M-9 for `fds` on the corpus. Identical model ⇒ identical input bytes. |
| FR-F3 | Cell size from the characteristic fire diameter, with the D*/δx ratio shown and a warning below the guidance range (from data). | 3.0 MUST | E-F02 fires on a coarse mesh, stating the ratio. |
| FR-F4 | Run serially or through MPI (MS-MPI on Windows), stream the output, and launch Smokeview. | 3.0 MUST | A corpus case runs in both modes. |
| FR-F5 | Tenability outputs: times at which visibility, temperature and gas thresholds at a stated height are first crossed. **No pass/fail on life safety.** The judgement belongs to the fire engineer (DEC-20's principle). | 3.0 MUST | No UI path displays a boolean safety verdict. |
| FR-F6 | OpenFOAM fire design fires: a volumetric heat-release source with a ramp, through the stock fire solver in the manifest. | 3.0 SHOULD | The corpus design fire runs on the default release. |
| FR-F7 | Evacuation modelling is **dropped**: the FDS evacuation module has been removed upstream (DEC-38). | — | — |

### 6.20 Scripting and automation (FR-X) — DEC-41

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-X1 | A documented, semver-versioned Python API over the services layer, and a headless CLI that opens a project, derives a study, runs it and writes a report. | 2.1 MUST | The CLI reproduces a GUI-created study byte-for-byte on the pinned toolchain. |
| FR-X2 | Scripts are the user's own files, run explicitly in a separate process. **Projects, packs and templates never carry executable code, and nothing runs on open** (NG8). | MUST (whenever it ships) | Opening a project containing a `.py` file executes nothing (a test). |
| FR-X3 | Variants: named deltas of a project's model and settings, with results compared side by side. | 2.1 MUST | Two variants differing in one construction show the difference in every affected result. |
| FR-X4 | Parameter sweeps: parameter × values → a batch of derived studies, run through `RunPlan` batches, producing a results table. Not optimisation (§2.3). | 2.2 MUST | A three-by-three sweep produces nine results, and survives one failure (as FR-VVM3). |
| FR-X5 | Extend the agent interface (FR-AG) to the building model and studies, with the same guarantees (FR-AG4). This is FR-AG7. | 2.1 SHOULD | An agent derives and runs a study using tools alone. |

### 6.21 Remote and HPC runs (FR-Q) — DEC-36

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-Q1 | SSH hosts the user controls: key authentication through the OS agent or keychain, and host-key verification with an explicit first-use confirmation. | 3.x MUST | A changed host key is refused (E-Q02). No private key or password appears in a project, a log or a diagnostics bundle. |
| FR-Q2 | Transfer a study with checksums, and run the same `RunPlan` remotely when the remote OpenFOAM matches the manifest. | 3.x MUST | A version mismatch is E-Q04 before transfer. The results match a local run within §12.3 tolerances. |
| FR-Q3 | Slurm and PBS Pro job scripts generated from the `RunPlan` and **shown before submission** (FR-S1's rule). Submit, poll, cancel and fetch. | 3.x MUST | The script shown equals the script submitted, byte for byte. |
| FR-Q4 | Stop & Write remotely, through the `abort` trigger file (FR-S5). | 3.x MUST | Produces a complete final time directory remotely. |
| FR-Q5 | No BuildFOAM-operated cloud. A commercial cloud VM is used as an ordinary SSH host. There is no cloud SDK in the core. | Permanent | The SBOM contains no cloud-provider SDK. |
| FR-Q6 | Offline mode (§10.4) disables every remote feature. | 3.x MUST | With offline mode on, no outbound connection is attempted (`check_offline.py`). |

### 6.22 Visual output and rendering (FR-Y) — DEC-38

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-Y1 | Export the building model and result colours as glTF 2.0, for external renderers and viewers. | 2.2 SHOULD | The file validates with the Khronos validator. |
| FR-Y2 | Export images of the 3D view and result maps at report resolution (≥ 300 dpi at the report's size). | 2.0 MUST | Every report image is regenerated from data, not screen-captured. |
| FR-Y3 | In-app photoreal rendering, VR, multi-user VR and scene streaming: **dropped** (NG7). | — | — |

### 6.23 Additions to existing families

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-V7 | **Study report**: the building scope, terminals and heat sources, the mapping used, mesh statistics, the V&V section (§14.4), result maps and comfort summaries, and the full provenance fingerprint. | 2.0 MUST | Opens in any PDF reader. Its model hash matches an independent recomputation. |
| FR-V8 | Export a ParaView state file (`.pvsm`) that reproduces a result map in ParaView. | 2.1 SHOULD | ParaView opens it with the same plane and colour scale. |
| FR-A8 | **Component manager**: install, verify, update and remove optional components (IfcOpenShell, and the engines) with sizes shown before any download (§7.3 step 4's rule). | 2.0 MUST | Each component's bytes are stated before download and reclaimed on removal (FR-R9's rule). |
| FR-L9 | New content kinds (libraries, rule packs, mapping data) are data only, and are signed (FR-L3, FR-L4). | 2.0 MUST | The installer rejects a pack with an executable or a script (E-L04). |
| FR-AG7 | See FR-X5. | 2.1 SHOULD | — |

---

## 7. User interface specification

§7.1–§7.9 stand. The shell's grammar (DEC-21) and the three-way agreement of outline, ribbon and documents (all declared as data, and asserted by `test_shell.py`) extend to the building workspace without exception.

### 7.10 The building workspace

**Outline.** A project adds groups *above* v1.0's case groups:

| Group | Nodes | Reads |
|---|---|---|
| **Project** | Site and Climate · Building Model · Classification · Checks · Libraries | `project.json`, `building/`, `libraries/` |
| **HVAC** | Terminals · Heat Sources · Air Balance | `building/model.json` components |
| **Studies** | one node per study; a CFD study expands into v1.0's *Workflow · Setup · Solution · Results · Files* groups **unchanged** | the study directory |

A CFD study's subtree *is* the v1.0 outline, so every v1.0 rule applies inside it: done means evidence on disk, done is revocable (DEC-22), blocked nodes stay visible and say why. The building model becomes one more input to freshness. Editing a terminal marks the derived mesh and results ↻, and the tooltip names the element that changed.

**Ribbon.** Two tabs are added before *Domain*, both declared in `ui/ribbon.py` as data: *Building* (Import BIM, Classify, Spaces, Openings, Checks, Context) and *Studies* (New CFD Study, and from 2.1 Energy, Wind, Daylight and Compliance). Every action selects an outline node or has a handler; there is no third kind.

**Documents.** These are added to the graphics window: *Building* (the 3D model, coloured by element type, construction, patch group or result, with picking), *Result Maps*, *Energy Charts* (2.1) and *Compliance* (2.2). *Building* and *Mesh* are separate documents for DEC-23's reason: they are separate things.

**Two additions to §7.9's principles:**

7. **A compliance verdict always names its rule and edition** in the same visual unit as the number (DEC-33). A verdict whose provenance is one click away is a verdict that will be screenshotted without it.
8. **Every generated engine input is one click away**, in a Text tab, exactly as dictionaries are (DEC-07). A study whose `epJSON` cannot be read in-app would trap P4, which D4 forbids.

---

## 8. Non-functional requirements

§8.1–§8.6 stand. Additions:

| ID | Requirement | Target |
|---|---|---|
| NFR-P10 | IFC import, off the GUI thread, cancellable | ≤ 120 s for a 50 MB IFC on the reference machine |
| NFR-P11 | Project open (parse, validate, freshness) | ≤ 5 s for 500 spaces and 20 000 surfaces |
| NFR-P12 | 3D view interaction (DEC-35) | ≥ 30 fps orbiting 1 M triangles on an OpenGL 3.3 GPU, with level of detail beyond that |
| NFR-P8 *(amended)* | Installer size | ≤ 250 MB **excluding optional components** (FR-A8). IfcOpenShell and every engine are downloaded on demand |
| NFR-C5 | Project JSON round-trip | Open and save with no edit ⇒ byte-identical files. Unknown keys preserved |
| NFR-C6 | Units | SI internally, everywhere. Units are converted only at import and display boundaries, and the unit is shown next to every number |
| NFR-C7 | Engine-input determinism | Identical model and settings ⇒ byte-identical engine input, for every engine |
| NFR-M9 | Engine versions, rule coefficients, limits and standard tables live **only** in manifests and data packs. `check_version_literals.py` is extended to engine version strings | Enforced by the guard and by review |
| NFR-M10 | Each engine integration is exercised headlessly in CI against a real engine where the licence permits, with tests marked `requires_<engine>` | EnergyPlus, Radiance and FDS on the Linux runner |
| NFR-M11 | Every library and data record carries `source` and `licence` | A record without them fails to load |
| NFR-S1 | Imported building files are untrusted input: size caps, parse timeouts, no network fetch of referenced resources | §10.5 |

NFR-M5 (the product name appears exactly twice) is unchanged. Every new path, extension and namespace derives from `APP_ID`.

---

## 9. Error taxonomy and failure UX

§9's principles and every existing code stand, with the same meaning. **Codes are never renumbered or reused.** Guide anchors follow the existing `<area>/<slug>` pattern.

### 9.1 Codes added during v1.0 implementation (recorded here, unchanged)

`src/foamwb/codes.py` is authoritative. These codes exist in it beyond v1.0's abridged table:

| Code | Condition | Anchor |
|---|---|---|
| E-R10 | No runtime provisioned yet | `runtime/first-run` |
| E-C08 | A field the solver solves has no initial condition | `cases/missing-field` |
| E-C09 | Geometry file could not be read | `cases/geometry-unreadable` |
| E-C10 | Geometry format not supported | `cases/geometry-unsupported` |
| E-C11 | No CAD converter is installed | `cases/cad-converter-missing` |
| E-C12 | CAD conversion failed | `cases/cad-conversion-failed` |
| E-C13 | A case is already there | `cases/new-case-exists` |
| E-C14 | That name cannot be used as a folder | `cases/new-case-name` |
| E-C15 | The case could not be written there | `cases/new-case-not-writable` |
| E-C16 | There is no geometry to mesh around | `cases/no-geometry-to-mesh` |
| E-C17 | The meshing dictionaries are already there | `cases/mesh-dict-exists` |
| E-S09 | Solver rejected the case setup | `running/setup-error` |
| E-S10 | Solver failed for an unstated reason | `running/solver-failed` |
| E-C18 | The case path has characters this runtime cannot open (the native Windows build's code page, FR-N9) | `cases/path-not-representable` |
| E-L04 | Package contains something other than data | `library/not-data` |
| E-L05 | A case of that name is already there | `library/destination` |

### 9.2 New code families

**Native Windows runtime (N)**

| Code | Condition | Message and remedy | Anchor |
|---|---|---|---|
| E-N01 | Native build not found, or `WM_PROJECT_DIR` invalid | Names the root searched; offers Install, Locate, or WSL | `native/not-found` |
| E-N02 | MS-MPI not installed | "Parallel runs need Microsoft MPI." Install (one elevation) or keep running serially | `native/msmpi-missing` |
| E-N03 | A runtime DLL is missing | Names the DLL; offers Repair (re-verify the archive) | `native/dll-missing` |
| E-N04 | Decomposition method unavailable in this build | Names the methods this build has; offers to switch | `native/decomposition-method` |
| E-N05 | Case uses dynamic code this build cannot compile | Names the file and line; offers to run on WSL | `native/dynamic-code` |
| E-N06 | Real-time scanning is slowing case I/O (advisory) | What to ask IT for; never changes settings | `native/antivirus` |
| E-N07 | Path length near the Windows limit | Offers to move the case to a shorter path | `native/path-length` |
| E-N08 | File names that differ only by case | Names both files | `native/case-collision` |

**BIM and project (B)**

| Code | Condition | Anchor |
|---|---|---|
| E-B01 | Building file could not be read (names the parser's message and position) | `bim/unreadable` |
| E-B02 | IFC schema or version not supported | `bim/schema` |
| E-B03 | Model has no spaces, so nothing can be derived (offers space-from-geometry) | `bim/no-spaces` |
| E-B04 | Space boundaries missing or inconsistent (states the fallback used) | `bim/space-boundaries` |
| E-B05 | Space not closed: gap, overlap or orientation defect, located in 3D | `bim/not-closed` |
| E-B06 | Units ambiguous or missing | `bim/units` |
| E-B07 | No boundary-condition rule for this element type and solver family | `bim/no-mapping` |
| E-B08 | Format needs a converter plug-in that is not installed (names the open export route) | `bim/converter-missing` |
| E-B09 | Project written by a newer schema (opened read-only) | `bim/newer-project` |
| E-B10 | `.hvacobj` line could not be imported, or a block was refused (names the line) | `bim/hvacobj` |
| E-B11 | Optional component (IfcOpenShell) not installed | `bim/component-missing` |

**Energy (E), Comfort (T), Wind (W), Daylight (D), Compliance (K), Fire (F), Remote (Q), Scripting (X)**

| Code | Condition | Anchor |
|---|---|---|
| E-E01 | EnergyPlus not found | `energy/not-found` |
| E-E02 | EnergyPlus version outside the manifest's support window | `energy/version` |
| E-E03 | EnergyPlus reported a severe or fatal error (first severe message shown) | `energy/severe` |
| E-E04 | Weather file invalid or incomplete | `energy/weather` |
| E-E05 | A zone surface has no construction | `energy/construction-missing` |
| E-T01 | Comfort input outside the index's validity range | `comfort/validity` |
| E-T02 | A field the index needs is absent from the results | `comfort/field-missing` |
| E-W01 | Weather file lacks usable wind data | `wind/no-wind-data` |
| E-W02 | Blockage ratio exceeds the guideline | `wind/blockage` |
| E-W03 | Estimated cell count exceeds the budget | `wind/cell-budget` |
| E-W04 | Inflow profile not maintained over the empty domain | `wind/homogeneity` |
| E-D01 | Radiance not found | `daylight/not-found` |
| E-D02 | Radiance library path incomplete | `daylight/raypath` |
| E-D03 | No sensor grid defined | `daylight/no-grid` |
| E-D04 | Optical properties missing for a material | `daylight/optics` |
| E-K01 | Rule set or edition not installed | `compliance/rule-missing` |
| E-K02 | An input the rule needs is missing (names it) | `compliance/input-missing` |
| E-K03 | Envelope classification incomplete | `compliance/classification` |
| E-K04 | Rule pack unsigned or its licence unverified | `compliance/pack-licence` |
| E-F01 | FDS not found | `fire/not-found` |
| E-F02 | Mesh too coarse for the fire size (states D*/δx) | `fire/resolution` |
| E-F03 | FDS run failed | `fire/run-failed` |
| E-F04 | Smokeview not found | `fire/smokeview` |
| E-Q01 | Remote host unreachable | `remote/unreachable` |
| E-Q02 | Authentication failed or host key changed | `remote/auth` |
| E-Q03 | Scheduler rejected the job (scheduler message shown) | `remote/scheduler` |
| E-Q04 | Remote OpenFOAM version differs from the study's | `remote/version` |
| E-Q05 | Transfer failed or checksum mismatch | `remote/transfer` |
| E-X01 | A user script raised an error (traceback in the console) | `scripting/error` |

FR-G2 applies to every new code: 100% have a guide page, enforced by M7's link check.

---

## 10. Security, privacy and trust

§10.1–§10.4 stand. The threat model gains the rows below. §10.3's honesty statement is amended: **on the native Windows runtime, as with the macOS tap, there is no boundary between the solver and the host.**

### 10.5 Untrusted building files

IFC, gbXML, `.hvacobj`, DXF and OSM files come from third parties. Parsers run with size caps and timeouts, never fetch referenced URLs, and never evaluate expressions embedded in a file. Imports run in a worker, and a crash there becomes E-B01 rather than taking down the application.

### 10.6 Remote credentials

Keys and passwords stay in the OS keychain or agent (FR-Q1). They are never written to a project, a log, a study report or a diagnostics bundle (FR-A4's rule). The diagnostics bundle lists remote *host names* only with consent.

### 10.7 Executable content policy

A project, study, pack, library, rule set or template is **data**. It never contains code that BuildFOAM executes, and no file format BuildFOAM reads is decoded with a platform object serialiser. This is FR-L3 (v1.0) extended to every new content kind. It is enforced by an AST guard: `pickle`, `marshal`, `shelve` and `yaml.load` without a safe loader are forbidden in `services/`. The owner's commercial product embeds compiled scripts in report layouts and uses a binary serialiser for projects. Neither pattern is reproduced (NG8).

### 10.8 Privacy additions

Weather files, site coordinates and building models can identify a client's project. None is included in telemetry, ever. The §10.4 payload list is exhaustive and unchanged. Agent access (FR-AG3) stays confined to user-granted roots, and projects are subject to the same confinement.

---

## 11. Milestones and exit criteria

### 11.1 Where v1.x stands

Units are as in v1.0: **developer-weeks of 40 focused hours**.

| Item | Status | Remaining est. |
|---|---|---|
| **R1** Residual v1.0 gaps against M3–M8 exit criteria (an assumption until audited) | Not audited | **4 wk** |
| M9 Beta and v1.0 (pilot cohort) | Not started | 4 wk |
| M10 v1.1 core, incl. **parallel runs** (a prerequisite of 2.0, §2.4) | Not started | 8 wk |
| M11 Mesh refinement study (GCI) | Not started | 4 wk |
| M12 Experimental validation | Not started | 3 wk |
| **v1.x residual** | | **23 wk** |

### 11.2 New milestones

Every exit criterion must pass, as in v1.0. The ordering again proves the riskiest unknowns first: the native build (M13) and IFC closure (M16) are the two things that would make everything after them moot.

| M# | Deliverable | Exit criteria (all must pass) | Est. |
|---|---|---|---|
| **M13** | Native Windows runtime | `WindowsNativeSession`, per-user provisioning and adoption, MS-MPI, process-tree ownership. **The M2 acceptance suite and the §12.3 golden gate pass unchanged (FR-N12).** The reproducible build recipe runs in CI and publishes its source (FR-N13). Paths outside the code page are refused before launch (FR-N9). M-8 measured | 7 wk |
| **M14** | Engine abstraction and component manager | `EngineSession`, `EngineLocator` and `EngineProvisioner`, with `RuntimeSession` refactored onto them with **zero behaviour change** (the full suite unchanged). The component manager installs and removes IfcOpenShell with stated bytes | 3 wk |
| **M15** | Building model and project format | §5.5 and §5.6 implemented. NFR-C5 round-trip over a generated corpus. Schema published. Migration from a fixture schema-0 project | 5 wk |
| **M16** | BIM import | IFC, gbXML and `.hvacobj`. **M-7 met on the reference corpus.** Every defect located. No `[Data]` block decoded. NFR-P10 met | 9 wk |
| **M17** | Building workspace and 3D view | Outline, ribbon and documents per §7.10, asserted by `test_shell.py` in all three directions. NFR-P12. Two-way selection between patches and elements | 7 wk |
| **M18** | HVAC objects and libraries | FR-H1–H6 and H8. The heat-balance check within 1%. The signed library pack is rejected when tampered | 4 wk |
| **M19** | Derivation to indoor CFD | FR-B20–B28. **Every corpus space derives, meshes into one region and runs. A hand edit survives re-derivation byte-for-byte (FR-B26).** FR-B27 automated | 8 wk |
| **M20** | Result maps, ISO 7730 and study report | FR-T1, T3 and T8, FR-V7, FR-Y2. **§12.7's ISO 7730 gate passes**, blocking release. The report checksum is independently recomputed | 5 wk |
| **M21** | Release 2.0 | Installer with the component manager. Guide pages for every new code. The platform suite on native Windows. **Pilot with at least one practice (P5): M-6 met** | 5 wk |
| | **Release 2.0 subtotal** | | **53 wk** |
| **M22** | EnergyPlus engine | FR-E1–E3, E6, E7 and E9. M-9 for epJSON. NFR-C7 | 10 wk |
| **M23** | Energy results and coupling | FR-E4 and E5. The coupled wall BCs equal the SQLite values | 4 wk |
| **M24** | Comfort standards | FR-T2, T4 and T6. §12.7 passes for ASHRAE 55 and EN 16798 | 5 wk |
| **M25** | Wind and urban | FR-B12, FR-W1–W6. Empty-domain homogeneity reported. A twelve-direction batch survives one failure | 9 wk |
| **M26** | Scripting, CLI and variants | FR-X1–X3 and X5. CLI and GUI byte-identity | 4 wk |
| **M27** | More import and authoring | FR-B11 (generic building), B13, B14 (gbXML) and B4 export | 3 wk |
| | **Release 2.1 subtotal** | | **35 wk** |
| **M28** | Radiance: static daylight | FR-D1–D3. §12.10 analytic cases | 6 wk |
| **M29** | Climate-based daylight, glare, sun | FR-D4–D7 and D10 | 6 wk |
| **M30** | Compliance framework and first pack | FR-K1, K2, K4, K5, K9 and K10. **The pack's worked examples reproduce exactly (§12.11). No forbidden verdict word in any output.** Pack licence verified (§13.9) | 7 wk |
| **M31** | Natural ventilation, wind-driven rain, compiled extensions | FR-W7 and W8, FR-L8, FR-K6. The rain solver's published validation reproduced | 7 wk |
| **M32** | Sweeps, glTF, epJSON import | FR-X4, FR-Y1, FR-E8 | 3 wk |
| | **Release 2.2 subtotal** | | **29 wk** |
| **M33** | FDS engine and input generation | FR-F1–F4. M-9 for FDS | 9 wk |
| **M34** | Fire outputs and OpenFOAM design fires | FR-F5 and F6. No boolean safety verdict | 5 wk |
| | **Release 3.0 subtotal** | | **14 wk** |
| **M35** | Remote and HPC | FR-Q1–Q6 | 6 wk |
| **M36** | Further regional packs (only if licensed, OD-4) | FR-E11, FR-K3 and K8 | 8 wk |
| **M37** | FMU co-simulation (user-supplied) | FR-T9 | 3 wk |
| | **3.x subtotal** | | **17 wk** |

### 11.3 What this means in calendar time

| Scope | Dev-weeks | 1 FTE (40 h/wk) | 20 h/wk | **15 h/wk** |
|---|---|---|---|---|
| v1.x residual (R1, M9–M12) | 23 | ~5 months | ~11 months | **~14 months** |
| Release 2.0 alone (M13–M21) | 53 | ~12 months | ~24 months | **~33 months** |
| Through Release 2.0 (v1.x residual + 2.0) | 76 | ~18 months | ~35 months | **~47 months (≈ 3.9 years)** |
| Through Release 2.2 | 140 | ~32 months | ~65 months | **~86 months (≈ 7.2 years)** |
| Full ladder through 3.x | **171** | ~40 months | ~79 months | **~105 months (≈ 8.8 years)** |

That is 171 developer-weeks, or 6 840 focused hours: **almost four times v1.0's 44 weeks**. The estimates carry no contingency. v1.0 §11 showed that the parser and the platform bridge were the places where estimates are least reliable. For 2.x those places are IFC closure (M16) and each engine's input writer (M22, M28, M33). A planning factor of **1.3×** is prudent there, which takes the full ladder past **eleven years at 15 h/week**.

**Said plainly: at 15 h/week the full suite is a decade of one person's work, and it will not be finished that way.** It is also longer than the support life of every engine version it would be built against (RISK-18).

### 11.4 Cut options

- **(a) Complement, do not replace (OD-3 (ii)). Recommended.** BuildFOAM owns CFD, V&V and BIM→CFD, which is everything through Release 2.0 plus wind (M25). The owner's commercial product keeps energy, daylight and compliance, and the two exchange data through the open project format (§5.5) and MCP. Scope ≈ 76 + 9 = **85 wk ≈ 4.4 years at 15 h/wk**. This also resolves most of §13's hardest questions, because nothing needs porting.
- **(b) Windows-only for 2.x (OD-7).** Removes macOS acceptance work for each engine and the WSL/macOS path for FR-L8: roughly **−12 wk** across the ladder.
- **(c) Fund help.** The engine milestones (M22, M28, M30, M33) are separable, and each has an *external* oracle: the engine's own CLI (M-9), the standard's worked examples (§12.11), the published comfort reference values (§12.7). v1.0 §11 made the same observation about M11. These are the safest milestones to hand to a postgraduate or a contractor.
- **(d) Reuse open-source libraries.** Examples: comfort indices (§13.8) and EnergyPlus model tooling. The saving is estimated at 10–15 wk. Each candidate's licence constrains OD-1: an AGPL toolkit would make options (B) and (D) impossible.
- **(e) Narrow Release 2.0 to "IFC → indoor CFD on native Windows".** gbXML and `.hvacobj` move to 2.1, and the 3D view is simplified to picking without interaction targets: Release 2.0 ≈ **45 wk**.
- **(f) Defer M11 and M12 behind 2.0.** **Not recommended.** It cuts D5, the one differentiator with no open-source competitor (v1.0 §1.4), and saves 7 weeks.

**Sequencing rationale.** M13 comes first because the building-services audience cannot use a WSL runtime at all (§1.2, barrier 7), so without it every later milestone has no user. M16 precedes M17–M19 because a model that does not close cannot be derived, and discovering that at M19 would waste two milestones.

---

## 12. Verification and test plan

§12.1–§12.6 stand. The golden-case gate (§12.3) and the V&V gate (§12.6) are unchanged and run on every runtime kind, including `WindowsNativeSession`.

### 12.7 Comfort-index verification (blocks FR-T releases)

The comfort module computes numbers that end up in design reports. Like §12.6, it can be tested almost entirely against published values:

| Test | Method | Gate |
|---|---|---|
| ISO 7730 PMV and PPD | The standard's published computed examples, entered as inputs | Match to the published precision. **Blocks M20** |
| Draught rate | Published examples | As above |
| ASHRAE 55 PMV, SET and adaptive | The standard's published verification tables, cross-checked against an independent open implementation | As above. **Blocks M24** |
| EN 16798-1 adaptive and categories | Worked examples | As above |
| UTCI | The published reference implementation's own test data | To its stated precision |
| Validity ranges | Each bound ± ε | E-T01 fires exactly at the bound, never NaN, never silence |
| FO against services | ISO 7730 via the stock function object and via services on the same fields | ≤ 0.05 PMV |

**The published tables are copyrighted.** They are used as test fixtures under §13.9's policy (a small number of cited values), subject to counsel.

### 12.8 Engine-input invariance

This is the analogue of §12.3's last row, for every engine. It proves the *writer* changed nothing numerical, independently of engine reproducibility.

| Test | Gate |
|---|---|
| Identical model ⇒ identical engine input bytes (NFR-C7) | Exact |
| Every generated input runs from the engine's own CLI (M-9) | Exit 0 |
| No-op project save ⇒ identical engine inputs on re-derivation | Exact |
| Pinned-toolchain engine outputs for the corpus (captured and stored with a fingerprint, like `tests/golden/references.json`) | Within stated tolerances. **Skip, naming the mismatch, on a different toolchain** |

### 12.9 BIM import corpus

A vendored set of IFC and gbXML files, drawn from openly licensed sources only, with each file's licence recorded beside it. It spans IFC2x3, IFC4 and IFC4.3, several authoring tools, models with and without second-level space boundaries, a georeferenced model, and deliberately defective models: an unclosed room, overlapping slabs and missing units. It gates M-7 and FR-B1 to B8. Like `tests/corpus/`, it is **data with recorded hashes**, updated only through a vendoring tool.

### 12.10 Daylight analytic cases

Daylight factor on an unobstructed horizontal plane under a CIE overcast sky (100% by definition), and simple rooms with published analytic or benchmark solutions (for example the CIE 171 test cases), gate M28.

### 12.11 Compliance calculators

Each rule pack ships the **worked examples from its own source document** as fixtures. The calculator must reproduce every intermediate quantity exactly, as §12.6 requires of the GCI module. A pack without worked examples cannot ship (RISK-19). U-value (ISO 6946) and Glaser (ISO 13788) calculators are gated the same way.

### 12.12 Platform acceptance additions

§12.4's manual suite gains: native Windows first run as a standard user (M-8); native parallel with MS-MPI; adoption of an existing system-wide native install; a case path outside the active code page (FR-N9, refused) and one inside it (runs); force-quit under `mpiexec` (FR-N6); and each engine's provision → run → remove cycle.

---

## 13. Licensing and legal

§13.1–§13.4 stand. This section is where the expanded scope is most likely to go wrong, and where going wrong is least reversible.

### 13.5 The licence decision (OD-1) — OPEN

DEC-09 chose GPL-3.0-or-later for a CFD workbench whose code was all new. Porting a commercial product's features changes what that choice *costs*. **Under the GPL, every piece of logic ported into BuildFOAM is published**: the element-to-BC defaults, the wind domain sizing, the solver-selection flags, the comfort and compliance calculators. Anyone may then use it under the GPL, including the owner's competitors.

| Option | What it means | For | Against |
|---|---|---|---|
| **(A) GPL-3.0-or-later throughout** (status quo) | Everything is open. Revenue comes from support, training, institutional LTS (§15.2) and consulting | Simplest. DEC-09's rationale holds (academic adoption, institutional clearance, Qt relinking moot). The owner, as copyright holder, can still license *their own* code to others separately | Ported know-how becomes public. Proprietary SDKs can never be linked (§13.6) |
| **(B) Dual licence** (GPL plus commercial) | The same code is under both. Commercial buyers get non-GPL terms | Revenue from a commercial edition, which could bundle the owner's licensed SDKs in-process, subject to *their* licences | **Requires the owner to hold copyright in 100% of the code**, so every contributor must sign a CLA or assign copyright *from the first contribution*. Excludes any GPL or AGPL third-party library from the core, now, which constrains §13.8. Contributors are often deterred |
| **(C) Open core** | A GPL core, plus proprietary add-ons that are **separate programs** communicating only through open files and a documented protocol (§4.7) | The core stays fully open and fully functional. The commercial value moves into add-ons: proprietary format converters, licensed standards packs (§13.9), and the owner's commercial product as a peer | The line between "aggregate" and "derivative" turns on how intimately the programs communicate (the FSF's own guidance). Add-ons must not contain or be derived from GPL code. Needs counsel review of the protocol. **Do not rely on this without counsel**, which is v1.0 §13.1's caution restated |
| **(D) Permissive** (Apache-2.0 or MIT) | Anyone may make proprietary derivatives, including the owner | Maximum reuse | Loses copyleft. The Qt/PySide6 LGPL relinking obligation becomes real (§13.2). Possible only because the repository's history currently shows a **single author**, which will not stay true |
| **(E) Proprietary** | — | — | Reverses every reason for DEC-09. Listed for completeness |

**What does not depend on the choice:**

1. Any version already published under GPL-3.0 **remains available under GPL-3.0 irrevocably**. A licence change applies to future versions only.
2. OpenFOAM's GPL obligations on *distributed OpenFOAM binaries* (§13.7) apply under every option.
3. **Decide before the first external contribution is merged, and before any ported code, template or data enters the repository.** After either event, options narrow and cannot be widened again.

### 13.6 Third-party SDKs in the owner's commercial product

None of the following can ship inside a GPL-3.0 BuildFOAM process. Each needs a replacement, an out-of-process optional plug-in (§4.7, DEC-31), or removal.

| Component | Used there for | Why it cannot ship here | Disposition and open replacement |
|---|---|---|---|
| **ODA SDKs** (BimRv, Drawings, DWF modules) | Revit RVT/RFA read and write; DWG | Proprietary. Per-member licence. GPL-incompatible | **IFC** through **IfcOpenShell** (LGPL-3.0) is the primary route: Revit exports IFC. DWG via the user-installed ODA File Converter or **LibreDWG** (GPL-3.0), either run as a separate process; DXF via **ezdxf** (MIT). An ODA-based converter plug-in only under OD-1 (C) and OD-8 |
| **Trimble SketchUp C SDK** | SKP read and write | SDK licence terms (registration, no sublicensing) | SketchUp's own IFC, OBJ or DAE export. A converter plug-in only under OD-8, after reading the SDK terms |
| **SoftGold CAD .NET** | DWG and DXF import | Commercial per-developer licence | **ezdxf** (MIT) for DXF, plus the DWG route above |
| **NVIDIA Iray / Iray+ / Iray Server / vMaterials** | Photoreal rendering | Proprietary. The OEM grant is not transferable | **Dropped** (NG7). glTF export (FR-Y1) to an external renderer. Radiance for physically based daylight images (FR-D3) |
| **NVIDIA Omniverse connector** | USD publishing, smoke visualisation | Proprietary terms | **Dropped** |
| **NVIDIA OptiX and CUDA NVRTC** | Ray-traced solar calculation | Proprietary SDK | CPU ray casting in services (FR-D9), or Radiance |
| **3Dconnexion SDK** | SpaceMouse input | Proprietary SDK | **Dropped.** The vendor's driver can map the device to standard input |
| **ISL Online client** | Vendor remote-desktop support | Proprietary | **Replaced** by the diagnostics bundle (FR-A4) and coded errors (§9) |
| **USB dongle runtime** and licence activation | Licence enforcement | Proprietary. Pointless in a GPL core | **Dropped** (NG6) |
| **Dymola-generated FMU** (human thermoregulation model) | Comfort co-simulation | Redistribution depends on the Dymola export licence option, and the model is third-party IP. **Unverified** | **Not shipped.** FR-T9 accepts a *user-supplied* FMU. **fmpy** (BSD-2-Clause) as host, in a separate process |
| **Outdoor-comfort calculator executables** (vendor unidentified) and their material library | SVF, MRT, UTCI | Licence unknown. Not shipped even by the owner's commercial product | **Re-implement** from the published literature (FR-T5, FR-D9). Use the library only with written permission |
| **GPU-accelerated Radiance build** | Faster daylight runs | Free for non-commercial use only (check the current terms) | Detect only, never download (FR-D8) |
| **TRNSYS** | Export target | Commercial | **Dropped.** EnergyPlus is the energy engine |
| **AWS SDK, cloud-HPC and reservation portals** | Remote runs | Apache-2.0 (the SDK), but it drives paid services, and DEC-36 excludes operated cloud | SSH and schedulers (FR-Q). **paramiko** (LGPL-2.1) |
| **OpenAI API** (boundary-condition review) | AI assistance | A service that sends project data off-machine using a key | **Replaced** by the MCP interface (FR-AG), with the user's own agent, local stdio and confined roots |
| **Online catalogues and model servers** (BIMserver, Forge/APS, BIMobject, city-model service, texture API) | Model and object sources | Service terms, and outside the offline promise (NFR-R5) | **Dropped.** Files are imported instead |
| **.NET libraries of uncertain licence** (GIS, OSM, Excel readers) | Various | Not reusable in Python, and licences unverified | Python equivalents: **pyshp** (MIT), **shapely** (BSD-3-Clause), **pyproj** (MIT), **pyosmium** (BSD-2-Clause). No `.xls` input: tables become JSON data |
| **7-Zip with the unRAR restriction** | Archive import | The unRAR licence restricts use | RAR is **not supported**. zip and gz come from the Python standard library |

### 13.7 GPL obligations on distributed OpenFOAM binaries

This applies **regardless of OD-1**, and it applies to the owner's commercial product *today*.

1. **The native Windows build is a GPL-3.0 work.** Whoever distributes it (the owner, or BuildFOAM by download) must provide the **Corresponding Source**. GPL-3.0 §1 defines this to include the scripts used to control compilation and installation. For a MinGW cross-build that means the ESI source *plus* every Windows-specific patch, the toolchain configuration and the build recipe. Shipping ESI's source archives alone is not sufficient if anything was patched.
2. **Custom solvers and libraries that link OpenFOAM's libraries are derivative works when distributed.** The owner's native build ships, according to the inventory, **binaries with no source in the bundle** for: comfort solvers (ISO 7730, ASHRAE 55, ISO 7243, ISO 7933, UTCI), an age-of-air solver, humidity solvers, a wind-driven-rain solver, aerosol solvers, several calculation utilities, heat-addition boundary conditions, a thermostat source, a custom-functions library and several turbulence-model libraries. **If that is so, every recipient of those binaries is entitled to their source, and it must be provided.** The owner should have counsel assess the current distribution independently of BuildFOAM. BuildFOAM will not distribute, download or adopt-by-manifest any binary whose source it cannot link to (FR-N13, DEC-32).
3. **Third-party provenance must be honoured.** The wind-driven-rain solver appears to derive from a solver published under GPL by an academic building-physics group (Kubilay et al., 2013). Their copyright notices and GPL terms must be kept, and the derivation confirmed. The cfMesh and other modules in the build are GPL and need the same treatment.
4. **Method: publish, do not merely offer.** A written offer (GPL-3.0 §6(b)) creates a three-year obligation to answer requests. Publishing source at a stable URL next to the binary discharges the obligation with no ongoing work. The manifest's `source` field (FR-N13) makes that URL part of the release gate.

### 13.8 Open-source components added by 2.x

| Component | Licence | Use | Obligation |
|---|---|---|---|
| IfcOpenShell (Python) | LGPL-3.0 | IFC reading (optional component) | Compatible with GPL-3.0. Notice. Replaceable module |
| Open CASCADE (through IfcOpenShell, or pythonocc-core) | LGPL-2.1 with exception / LGPL-3.0 | Geometry kernel for IFC and STEP | As above |
| ezdxf | MIT | DXF | Attribution |
| rhino3dm | MIT | 3DM | Attribution |
| trimesh, numpy, shapely, pyproj, pyshp | MIT / BSD | Mesh operations, arrays, 2D geometry, projections, shapefiles | Attribution |
| pyosmium | BSD-2-Clause | OSM | Attribution. **OSM data is ODbL**: attribution, and share-alike on derived *databases* (FR-B12) |
| EnergyPlus | BSD-3-Clause-like (DOE/NREL) | Engine, downloaded | Notice. "EnergyPlus" is a DOE trade mark: nominative use only |
| Radiance | Radiance licence (BSD-like, LBNL) | Engine, downloaded | Notice |
| FDS and Smokeview | Public domain (NIST, US government work) | Engine, downloaded | None legally. Cite as the authors request |
| MS-MPI redistributable | Microsoft redistributable licence | Parallel on native Windows | Redistribution per its terms. Installed on demand |
| fmpy | BSD-2-Clause | FMU host (3.x) | Attribution |
| paramiko, keyring | LGPL-2.1 / MIT | SSH, credentials (3.x) | Notice |
| *Considered, not adopted by default:* Ladybug Tools (AGPL-3.0), OpenStudio SDK (BSD-3-Clause-like), pythermalcomfort (MIT) | — | Reuse candidates (§11.4 (d)) | **AGPL rules out OD-1 (B) and (D)** if adopted. pythermalcomfort is the preferred *cross-check oracle* for §12.7 rather than a dependency |

### 13.9 Standards content

Implementing a procedure a standard describes is ordinary engineering. **Copying a standard's tables, text or forms is copying a copyrighted publication.** The owner's commercial product bundles tables transcribed from several standards. None of them enters BuildFOAM without the check below.

| Content | Examples | Status | Policy |
|---|---|---|---|
| German and European standard tables | VDI 2078 cities and climate zones, VDI 6007/6020 parameters, VDI 2089 coefficients, DIN V 18599 use profiles, DIN 4108-2 regions, DIN 1946-6 district list, DIN 276 cost groups, EN 12831 templates | Copyrighted (VDI; DIN, published by Beuth) | Procedure implemented; **tables only through a licensed data pack** (FR-K1), or with written permission |
| International comfort standards | ISO 7730, ASHRAE 55, EN 16798-1 | Copyrighted | Procedures implemented. A few cited values used as test fixtures (§12.7), subject to counsel |
| Envelope codes and their data | Singapore envelope thermal performance code (solar data by orientation, shading-coefficient tables, the submission form), Malaysian MS 1525 tables, Indonesian solar-factor tables | Government or standards-body copyright; the forms are an authority's documents | Procedures implemented. **Tables with permission, or user-supplied packs. Forms never reproduced** (NG9). Report wording per DEC-33 |
| Rating-scheme criteria | Green Mark, LEED, BNB, DGNB, BREEAM | Scheme owners' copyright **and trade marks** | Criteria as licensed packs. Scheme names used nominatively only (§13.12) |
| Metric definitions | IES LM-83 (sDA, ASE), EN 17037, CIE sky models | Copyrighted documents | Definitions implemented. Thresholds in data with citation |
| Wind-comfort criteria | NEN 8100 (paid), Lawson, Davenport | NEN copyrighted. Lawson and Davenport published in the literature | Lawson and Davenport from the literature, with citation. NEN 8100 only as a licensed pack |
| Design fires and drop-size data | t² growth classes; digitised HRR curves (source not named in the inventory); raindrop spectra | t² classes are in the public literature. **The digitised curves' provenance is unknown** | Literature values with citation. **Unattributed curves are not imported** |

**Rule:** a pack whose `licence` field is missing or unverified cannot load (FR-K9). A pack that carries a standard's tables must name the permission it relies on.

### 13.10 Data licences

| Data | Issue | Policy |
|---|---|---|
| Weather files (EPW, test reference years) | The German national test-reference years have **restrictive redistribution terms**. Public EPW collections vary by source | **No weather file is bundled.** The user supplies EPWs, and the guide links to public sources |
| Material and construction databases | The owner's product mixes sources: standards tables, a university material generator, an open research dataset (MIT-licensed), a regional construction catalogue of unknown origin, a heritage-construction website | Each record needs `source` and `licence` (NFR-M11). Records of unknown origin are **not imported** |
| Glazing optical data | International glazing database terms | Import tool only. Terms honoured |
| EPD / LCA databases | National database terms | 3.x, after checking the terms (FR-K8) |
| OpenStreetMap | ODbL | Attribution in the UI and in reports. Derived-database share-alike respected |

### 13.11 IP ownership — confirmation required (OD-2)

The owner asserts ownership of the commercial product. **This PRD does not verify that assertion, and nothing may be ported on the strength of it alone.**

The inventory records the following facts. The installers name **Tian Building Engineering** (also styled TIAN Building Engineering) as manufacturer and copyright holder, © 2012–2027. The native OpenFOAM package's licence text describes the build as a service of a differently named CFD add-on. Code namespaces indicate work by **more than one developer**. The bundle also contains third-party IP: an FMU model, an outdoor-comfort material library, and design-fire curves of unstated origin.

Before any code, template, data table, solver source or algorithm derived from that product enters this repository, the owner must provide:

1. **Written confirmation from the legal copyright holder** (the company, if it is not the owner personally) that grants the right to publish the material under OD-1's licence.
2. **Confirmation that every contributor's work vests in the holder** (employment terms or assignment), or individual written permission from each contributor.
3. **An exclusion list of third-party IP** that is not the holder's to license (§13.6, §13.9, §13.10).
4. **Institutional clearance (§13.4), extended.** Work the owner does in university employment may vest in the institution. A university-released open product that competes with the owner's own company also needs a **conflict-of-interest declaration**.
5. **The `.hvacobj` specification** contributed to `docs/` under a licence that permits an open implementation.

**Until all five exist, the safe path is clean-room.** Implement from this document's feature descriptions, from public standards (§13.9) and from the published literature, and copy nothing: no code, no XML templates (the owner's product ships 885 template files per OpenFOAM version), no data tables, no solver sources. The inventory describes *what* the product does, which is not copyrightable. How it does it may be.

### 13.12 Trade marks

v1.0 §13.3 stands for OpenFOAM and for Ansys. Three additions:

- **Rating schemes and standards bodies** (LEED, Green Mark, BREEAM, DGNB, BNB, ASHRAE, CIBSE, and others) are named **only nominatively**, to say what a calculation follows. There are no logos, no "certified" or "approved" wording, and no implication of endorsement (FR-K5, NG9).
- **Engine names** (EnergyPlus, Radiance, FDS, Smokeview) are named nominatively, with each owner's notice in the About dialog and in Third-Party Notices.
- **The owner's commercial product's name, artwork and UI text** are not used in the product (see the provenance note under *How to read this document*).

---

## 14. Teaching and laboratory deployment

§14.1–§14.6 stand. The native runtime (FR-N) is the largest single improvement for labs: E-R01, E-R02 and E-R03 disappear on a managed Windows image, and FR-R7/FR-R8's `lab.json` gains `"runtime": "windows-native"`.

### 14.7 Building physics and building services teaching

- **Course packs carry projects** (§5.5) as well as cases, so a week's exercise can be "this IFC, this terminal layout, compare two diffuser types".
- **The V&V discipline carries over.** A comfort map is a CFD result like any other: its study report (FR-V7) carries the y⁺ audit, the GCI where a study family exists, and the provenance strip. A student learns that a PMV map is only as good as the mesh under it.
- **Compliance exercises use the worked examples of openly licensed rule packs only** (§13.9). A licensed pack in a teaching deployment needs the licence to cover teaching.

---

## 15. Release, update and support

§15.1–§15.5 stand. Additions:

- **Engine support window.** For each engine, the current release and the previous one (§3.7's `support_window`), announced as §15.5 already announces OpenFOAM deprecations.
- **Rule-set editions are versioned content.** A project pins the edition it was assessed under. A new edition installs *beside* the old one, never replacing it, because a submission must be reproducible against the edition it cited. Superseded editions carry a banner, not a block.
- **LTS (from 2.0)** includes the engine versions and rule editions it shipped with, for its 12-month life.

---

## 16. Decision log

v1.0's DEC-01 to DEC-24 stand, with these status updates:

- **DEC-03 is settled.** The name was kept at M8 (see the repository history). The 2.x scope does not reopen it.
- **DEC-09 is under review** (OD-1). It stays in force until the owner decides.
- **DEC-18 is still open** (OD-9).
- **DEC-23's** "preview, not viewer" still governs the Mesh document. DEC-34 adds result maps as a *separate* document.

| ID | Decision | Alternatives rejected | Rationale | Reversal cost |
|---|---|---|---|---|
| **DEC-25** | **BuildFOAM becomes a BIM-to-simulation suite for building services**, with OpenFOAM as its core engine, the V&V module kept as a differentiator, and scope delivered on a release ladder with owner decisions gating it (§0) | Stay a CFD workbench; port the whole commercial product in one release | The owner has decided on the product direction. The ladder makes each release useful on its own, and puts BIM→CFD, the part nearest the existing code, first | Medium. Each release is additive |
| **DEC-26** | **`WindowsNativeSession`** for a MinGW OpenFOAM build, preferred on Windows when a verified build exists for the default version. WSL retained | WSL only; native only; Docker on Windows | Removes the virtualisation, admin and reboot failures (E-R01 to E-R03) that make WSL unusable on corporate and lab machines. WSL stays for dynamic code and full decomposition. The build's cost (rebuilding for each release) is RISK-17 | Low. A fourth implementation behind an existing interface |
| **DEC-27** | **An engine-neutral building model in services**, with studies *derived* from it and each CFD study a plain v1.0 case | Build each engine's input directly from the imported file; make the OpenFOAM case the master model | One model is what makes D7 possible. Keeping each case plain keeps D4 and FR-C7. Derivation (rather than a live link) keeps hand edits safe (FR-B26) | High once projects exist in the field |
| **DEC-28** | **Open project format**: a directory of sorted, LF, UTF-8 JSON plus plain asset files, zip for exchange, a published schema, unknown keys preserved | A binary serialiser; SQLite; one monolithic JSON; IFC as the native format | Diffable, language-neutral and safe to open. IFC is an exchange format, too loose for engine settings and study state, and it round-trips poorly | High after release; enforce from M15 |
| **DEC-29** | **Element → patch → BC mapping as versioned data per lineage and solver family**. Patches are grouped by attributes, not per element. Turbulence BCs stay with the advisor | Mapping in code; one patch per element; mapping turbulence fields too | NFR-M3. Patch count and legibility. A single owner for turbulence BCs is what keeps FR-VVT4's consistency guarantee | Low. Data |
| **DEC-30** | **Engine abstraction; external engines found or downloaded as optional components, never linked, never in the default installer** | Bundle the engines; bind the engines' C APIs | Size (NFR-P8), licences (§13.8), independent version cadence (§3.7). The `ParaViewService` and `CadConverter` precedents already work | Low |
| **DEC-31** | **Proprietary SDKs only in separately distributed, out-of-process plug-ins over open files**. IFC is the primary BIM exchange | Link the SDKs; drop the formats entirely | A GPL process cannot contain them (§13.6). Authoring tools already export IFC. A plug-in boundary keeps OD-1 (C) possible without deciding it now | Low |
| **DEC-32** | **Comfort indices computed in services** (plus the stock comfort function object where available). Custom solvers are not required, and any solver shipped is shipped with source | Ship custom comfort solvers per platform | Custom solvers need a compiler per platform (FR-L8), carry GPL source obligations (§13.7), and turn a post-processing formula into a solver run. Services code is verifiable against published tables (§12.7) | Low |
| **DEC-33** | **Compliance verdicts are allowed for code-defined numerical limits**, worded "meets or does not meet limit L of <rule, edition, clause>", always shown with the edition. DEC-20 is **unchanged** for V&V | No verdicts (as for V&V); a "compliant" badge | A regulatory limit is set by the code, not by the tool, so reporting against it is a statement of arithmetic, unlike an adequacy judgement on numerical uncertainty (DEC-20). "Compliant" would claim more than one calculation can: approval is the authority's act | High. A product-philosophy commitment, as DEC-20 was |
| **DEC-34** | **In-app result maps on planes and surfaces** (NG3 relaxed). ParaView stays the general viewer | ParaView-only; an embedded ParaView/VTK viewer | Reports need reproducible images generated from data (FR-Y2). Planes cover the building metrics that matter. An embedded full viewer breaks NFR-P8 and NG3's intent | Low |
| **DEC-35** | **3D view: a lightweight OpenGL widget in `ui/`, surfaces only**. No VTK in the default install | VTK/pyvista; Qt Quick 3D (excluded by NFR-P8's module stripping) | The 3D view shows planar building surfaces, meshes' boundary faces and colour maps, which fit a small renderer. VTK costs about 100 MB. It may return later as an optional component | Medium |
| **DEC-36** | **Remote compute only on user-controlled SSH and scheduler hosts; outbound only**. No operated cloud | A vendor cloud service; cloud SDKs | §10.1's no-listening-sockets rule, NFR-R5 offline operation, and no credentials held for the user. A cloud VM is still usable as an SSH host | Low |
| **DEC-37** | **No reader for the legacy binary project format**. Migrate through an exporter in the owner's product (OD-10), plus the `.hvacobj` importer | A reverse-engineered deserialiser | Deserialising a platform binary serialiser is a code-execution class (§10.7). The format is undocumented. The owner controls the exporting side | Low |
| **DEC-38** | **Dropped**: photoreal rendering, VR and multi-user VR, scene streaming, acoustics, the in-app GPU lattice-Boltzmann solver, TRNSYS and NANDRAD export, evacuation, the AI boundary-condition checker (replaced by FR-AG), licence activation | Port them all | Outside the building-services core, dependent on proprietary SDKs (§13.6), or superseded upstream (FDS evacuation). Each would cost a milestone and serve a fraction of P5 | Low. Any can return as an add-on under OD-1 (C) |
| **DEC-39** | **Standards content policy** (§13.9): implement procedures; tables only with permission or through user-supplied licensed packs; never reproduce forms | Transcribe tables as the owner's product did | Copyright in standards is actively enforced, and a GPL release would republish the tables to the world | Medium |
| **DEC-40** | **Re-slot v1.0's planned "v2.0"**: compiled extensions (FR-L8) → Release 2.2; cluster submission → FR-Q (3.x); plugin API → FR-X and §4.7. Release numbers are independent of PRD numbers | Keep the old v2.0 content in Release 2.0 | Release 2.0 is the BIM→CFD release. FR-L8 is needed exactly when open custom solvers are (FR-W8) | Low |
| **DEC-41** | **Scripting is a Python API, a CLI and MCP**. No visual node-graph language, no macro recording | Port the node-graph scripting | The services layer already *is* the API (NFR-M1). A node language is a second programming environment to build, document and secure, for users who have a real one | Low |

---

## 17. Risk register

RISK-01 to RISK-12 stand. **RISK-01** (scope exceeds capacity) is re-rated to **Very high likelihood** by §11.3. **RISK-08** (bus factor) is intensified by every engine added.

| ID | Risk | L | I | Mitigation | Trigger for the contingency |
|---|---|---|---|---|---|
| RISK-13 | **Suite scope never converges**: 2.x ships piecemeal and nothing is complete | Very high | High | The release ladder with hard cut-lines (§2.1). OD-3 (ii) as the default. Cut options (§11.4) | M21 slips more than 6 months → adopt §11.4 (a) formally |
| RISK-14 | **Licence decided late**, after contributions or ports make options irreversible | Medium | Very high | OD-1 is gated before M13. A CLA from now if B or D are live | Any external PR before OD-1 → hold it unmerged |
| RISK-15 | **IP claim** by the company, a co-developer or the institution against ported material | Medium | Very high | OD-2. Clean-room by default (§13.11) | Any copied artefact found without the five confirmations → remove it before release |
| RISK-16 | **GPL non-compliance** of distributed OpenFOAM binaries (existing exposure in the owner's product; future exposure in BuildFOAM) | High (current evidence) | High | §13.7. FR-N13's release gate | A binary without a source URL in any manifest → the release fails |
| RISK-17 | **The native Windows build lags ESI releases** | High | Medium | Reproducible recipe in CI (M13). The manifest pins verified builds. WSL fallback | No verified native build 3 months after an ESI release → the wizard defaults to WSL for that version |
| RISK-18 | **Engine version churn**: epJSON schema changes, Radiance and FDS output changes | High | Medium | The engine manifest's support window. The writer targets a pinned schema. §12.8 gates | A new engine release fails M-9 → pin the previous one, publish a notice |
| RISK-19 | **Standards currency**: a rule edition is superseded or mis-transcribed, and a user submits against it | Medium | **Very high** | Editions pinned per project (§15). Worked-example gates (§12.11). Provenance strip (FR-K10). DEC-33's wording | Any worked-example failure blocks the pack. No pack without worked examples |
| RISK-20 | **IFC quality**: real models do not close | High | High | FR-B7 healing and located defects. M-7 measured on real files. The FR-B11 authoring fallback | M-7 below 60% at M16 → narrow 2.0 to gbXML and authored spaces, with IFC as underlay only |
| RISK-21 | **A comfort or compliance number is wrong and is used in design** (the RISK-11 analogue) | Medium | Very high | §12.7 and §12.11 as release gates. Validity flags (FR-T7). Provenance. No overclaiming verdicts | Any gate failure blocks the module. No "ship with a known issue" |
| RISK-22 | **Commercial conflict**: an open BuildFOAM erodes the owner's product revenue, or company stakeholders object | Medium | High | OD-1 (C) or OD-3 (ii). The conflict-of-interest declaration (§13.11) | Stakeholder objection → pause porting and continue clean-room CFD work only |
| RISK-23 | **Installer and dependency bloat** (IfcOpenShell, the OCCT kernel, engines) | Medium | Medium | The component manager (FR-A8). NFR-P8 excludes optional components. SBOM checks | Core installer beyond 250 MB → strip or move to optional |
| RISK-24 | **Third-party data takedown** (weather, materials, criteria) | Low | Medium | NFR-M11 provenance on every record. No bundled weather | A notice received → withdraw the record by signed catalog update (FR-L6) |

---

## 18. Glossary

v1.0's glossary stands. Additions:

| Term | Meaning |
|---|---|
| **BIM** | Building information model: geometry plus semantics (element classes, spaces, materials) from an authoring tool. |
| **IFC** | Industry Foundation Classes, the open BIM exchange schema maintained by buildingSMART. |
| **gbXML** | An XML schema for building energy-analysis geometry: spaces, surfaces, openings. |
| **Space boundary (2nd level)** | An IFC relationship giving each space's bounding surface pieces with their thermal adjacency. The ideal input for energy and CFD derivation. |
| **Project / Study** | A project holds one building model. A study is one engine run context derived from it; a CFD study is a v1.0 case. |
| **Derivation** | Generating an engine input (an OpenFOAM case, epJSON, Radiance scene, FDS input) from the building model, with provenance. |
| **Element type** | BuildFOAM's classification of a surface or component (external wall, supply terminal, …), from which patch grouping and default BCs follow. |
| **Engine** | An external simulation program behind `EngineSession` (OpenFOAM, EnergyPlus, Radiance, FDS). |
| **Rule set / pack** | Signed data carrying a standard's or scheme's coefficients, limits and tables for one edition, with its licence. |
| **PMV / PPD** | Predicted Mean Vote and Predicted Percentage Dissatisfied (ISO 7730 / ASHRAE 55). |
| **SET** | Standard Effective Temperature (ASHRAE 55), used for elevated air speed. |
| **UTCI** | Universal Thermal Climate Index, for outdoor thermal stress. |
| **MRT** | Mean radiant temperature. |
| **sDA / ASE** | Spatial daylight autonomy and annual sunlight exposure (IES LM-83). |
| **DGP** | Daylight glare probability. |
| **ABL** | Atmospheric boundary layer. The inflow profile of an outdoor wind study. |
| **WDR** | Wind-driven rain; the catch ratio is the rain intensity on a façade relative to free-field. |
| **MinGW** | A Windows port of the GNU toolchain, used to build OpenFOAM as native Windows executables. |
| **MS-MPI** | Microsoft's MPI implementation, used by the native Windows build for parallel runs. |
| **Job Object** | A Windows kernel object grouping processes so they can be terminated together. The native equivalent of a POSIX process group. |
| **Corresponding Source** | GPL-3.0's term for the complete source needed to build and install a distributed binary, including build scripts. |
| **CLA** | Contributor licence agreement, needed for dual licensing. |

---

## 19. Feature coverage matrix

The disposition of each area of the owner's feature inventory. "Tier" is the release that delivers it. **Dropped** items give their reason in the cited decision.

| Area | Inventory feature (summarised) | Disposition | Where |
|---|---|---|---|
| **CFD setup** | Solver selection from physics flags | Data-driven capability table | FR-B20 |
| | RAS and LES models, coefficients | Existing advisor | FR-VVT1–VVT9 |
| | Transport and thermo properties per region | Existing editors; derivation fills them | FR-P1, FR-B20 |
| | Initial conditions, turbulence calculator | Existing | FR-VVT6 |
| | Potential-flow initialisation | A plan stage | FR-S1 (2.0) |
| | Schemes and solution presets (1st/2nd order) | Presets as data | FR-P1 (2.0) |
| | Radiation (fvDOM, P1, solar load, view factors) | Derived where the release provides it | FR-T2 (2.1) |
| | Age of air, passive scalars, CO₂ | — | FR-H5 (2.0) |
| | Humidity | Only a solver with source, or a labelled approximation | FR-B25 (2.1) |
| | Reactions, general combustion | **Dropped**, except fire | §2.3 |
| | OpenFOAM fire (HRR ramps, pyrolysis, film) | Design fires only | FR-F6 (3.0) |
| | Lagrangian particles and aerosols | Deferred | 3.x, unplanned |
| | CHT multi-region | Deferred | 3.x, unplanned |
| | MRF, SRF, AMI, dynamic and overset mesh | **Dropped** (outside the HVAC core) | DEC-38 |
| | Porous media, plant canopy | Canopy with wind | FR-W6 (2.1) |
| | Baffles, external coupling | Deferred / replaced by one-way coupling | FR-E5 (2.1) |
| | Inlet–outlet mapping (recirculation) | Stock BCs only | FR-H7 (2.1) |
| | Building-element default BCs | Mapping data | §5.7, FR-B23 (2.0) |
| | BC editor, patch types | Existing matrix | FR-P4 |
| **Meshing** | blockMesh, snappyHexMesh, refinement regions, feature extraction, location points, leak detection | Existing, with derivation defaults | FR-P2, P3, P5, FR-B21, B28 |
| | cfMesh | Not planned; snappyHexMesh covers it | — |
| | topoSet, setFields, createPatch, extrudeMesh | Text tab (D4) | FR-P6 |
| | Voxelisation | For FDS obstructions only | FR-F2 (3.0) |
| **Running** | controlDict and function-object library | Existing editors; comfort and scalar objects from data | FR-P1, FR-T1 |
| | MS-MPI and Open MPI, decomposition | Native MS-MPI; WSL Open MPI | FR-N5, FR-S9 |
| | Run recipes | `RunPlan` | §4.3 |
| | Live log and residual, min/max and probe plots | Existing | FR-S2, FR-S4 |
| **Results** | In-app mesh and field import, slices | Result maps on planes | DEC-34, FR-T8 (2.0) |
| | Streamlines, glyphs, video | ParaView | NG3 |
| | ParaView state export | — | FR-V8 (2.1) |
| | CFD and slice reports (layout designer) | Generated reports; no layout designer | FR-V7 (2.0), NG8 |
| **Wind** | Three-step wind wizard, EPW sector analysis, ABL profiles, cylindrical domains, wind rose | Wind studies | FR-W1–W5 (2.1) |
| | Wind comfort criteria (NEN 8100, Lawson, Davenport) | Lawson and Davenport; NEN only if licensed | FR-W5, §13.9 |
| | Wind-driven rain | Solver with source | FR-W8 (2.2) |
| | Outdoor urban comfort pipeline | Re-implemented | FR-T5 (2.2) |
| | GPU lattice-Boltzmann solver | **Dropped** | DEC-38 |
| **BIM import** | IFC 2x3/4 (IfcOpenShell) | — | FR-B1 (2.0) |
| | gbXML | — | FR-B3 (2.0) |
| | `.hvacobj` | — | FR-B4 (2.0) |
| | STL, OBJ, STEP, IGES | Existing | FR-P3, FR-B5 |
| | Rhino 3DM, DXF | — | FR-B13 (2.1) |
| | Revit, DWG, SketchUp | Converter plug-ins only | FR-B15, OD-8 |
| | FBX, PDF underlay, point clouds, MetaImage, FDS/Smokeview input | **Dropped** | NG1 |
| | CityGML, OSM, shapefile, DEM, XYZ | Urban context | FR-B12 (2.1) |
| | Online model servers and catalogues | **Dropped** | §13.6 |
| **BIM export** | STL, OBJ | Existing | FR-P3 |
| | gbXML, IFC | — | FR-B14 (2.1/2.2) |
| | SKP, RVT, STEP, IGES, SMESH, USD, others | **Dropped** | DEC-38 |
| | glTF | — | FR-Y1 (2.2) |
| **Modelling** | Spaces from footprints, openings by WWR, storeys, generic building | Light authoring | FR-B11 (2.0/2.1) |
| | Walls, roofs, ramps, swept solids, CSG, primitives, UV mapping, texture editing | **Dropped** | NG1 |
| | Mesh repair, normals | Healing | FR-B7 (2.0) |
| | Transform, mirror, array | Existing transform | FR-P5 |
| | Variants, layers, saved views | Variants; camera bookmarks | FR-X3 (2.1) |
| **Building physics data** | Materials, constructions (ISO 6946 U-value), glazing, gases, templates | Libraries | FR-E6 (2.1) |
| | Shading systems | With energy and daylight | FR-E2, FR-D2 (2.1/2.2) |
| | Pipes, surface heating, HVAC plant schema, pipelines, PV | **Not planned** beyond ideal loads | FR-H10 |
| | LCA / EPD | Licence-gated | FR-K8 (3.x) |
| **Energy** | Zones, templates, people, equipment, lighting, infiltration, ventilation, thermostats, fresh air and CO₂, ideal loads, daylight control, shading control, schedules, general settings, solver settings, design days, outputs, raw input code, results import, charts | EnergyPlus engine | FR-E1–E9 (2.1/2.2) |
| | Energy management system scripts | Raw epJSON, fenced | FR-E9 |
| | Stochastic occupancy units, load profiles | Deferred | 3.x |
| | TRNSYS and NANDRAD export | **Dropped** | DEC-38 |
| | VDI 2078, DIN 4108-2, DIN 1946-6, DIN 18017-3, SWKI car park, VDI 2089, EN 12831 | Licensed regional packs | FR-E11 (3.x), OD-4 |
| **Climate** | EPW import | Site and climate node | §7.10 (2.0) |
| | Weather editor, world map, TRY maps, artificial weather | **Dropped** (user-supplied EPW) | §13.10 |
| | Wind rose, climate analysis | — | FR-W1 (2.1) |
| | Psychrometric chart, ground temperature | With energy | 2.1 SHOULD |
| **Solar and daylight** | Sun path, shadows, sunlight hours, irradiance | Internal | FR-D9 (2.2) |
| | Radiance DF, illuminance, luminance, sDA, ASE, DGP, annual irradiance, panoramas, EN 17037 | Radiance engine | FR-D1–D7 (2.2) |
| | GPU Radiance | Detect only | FR-D8 |
| **Fire** | FDS namelists, meshes, fires and ramps, devices, HVAC, outputs, run, Smokeview | FDS engine | FR-F1–F5 (3.0) |
| | Evacuation | **Dropped** (removed upstream) | FR-F7 |
| **Comfort** | ISO 7730 and ASHRAE 55 fields and point calculator, EN 16798, radiant asymmetry, clothing and activity tables | Services implementation | FR-T1–T8 (2.0/2.1) |
| | Thermophysiology FMU | User-supplied only | FR-T9 (3.x) |
| **Compliance** | Envelope heat-gain rules with shading coefficients and reports | First pack | FR-K2, K4 (2.2) |
| | Natural-ventilation rating procedure, daylight credits | — | FR-K6, K7 (2.2) |
| | National sustainability ratings, LCC | Licence-gated | FR-K8 (3.x) |
| **Automation** | C# scripts | Python API and CLI | FR-X1 (2.1) |
| | Visual node-graph scripts | **Dropped** | DEC-41 |
| | AI boundary-condition review | MCP agent interface | FR-AG |
| **Remote** | SSH console, PBS job manager | SSH plus Slurm and PBS | FR-Q (3.x) |
| | Cloud accounts, spot instances, cost explorer, reservation portals | **Dropped** | DEC-36 |
| **Platform** | Photoreal renderers, VR, multi-user VR, mobile mode, 3D mouse and game controller | **Dropped** | NG7, DEC-38 |
| | Wizards and in-app tutorials | Outline plus study templates; Guide | FR-G, §7.10 |
| | Licensing, activation, dongle | **Dropped** | NG6 |
| | Localisation (de, ko, zh) | Strings externalised (NFR-A5); languages on demand | NFR-A5 |
| | XML data editor | Text tab and JSON | DEC-07 |
| | Remote-desktop support | Diagnostics bundle | FR-A4 |

---

## Appendix A — Sources for factual claims (additions)

v1.0's Appendix A stands. Added for this revision:

- The owner's feature inventory of their commercial product (four documents: CFD, BIM, physics, platform), produced for this revision. Not public. It was the source of every statement in §0, §13.6, §13.7, §13.11 and §19 about what that product contains.
- [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html), §1 (Corresponding Source) and §6 (conveying non-source forms); [GPL FAQ — aggregation and "intimate communication"](https://www.gnu.org/licenses/gpl-faq.html#MereAggregation)
- [IfcOpenShell](https://ifcopenshell.org/) — LGPL-3.0
- [EnergyPlus](https://energyplus.net/) and its [licence](https://github.com/NREL/EnergyPlus/blob/develop/LICENSE.txt)
- [Radiance](https://www.radiance-online.org/) — Radiance licence (LBNL)
- [Fire Dynamics Simulator](https://pages.nist.gov/fds-smv/) — NIST
- [Microsoft MPI](https://learn.microsoft.com/en-us/message-passing-interface/microsoft-mpi)
- ISO 7730:2005, *Ergonomics of the thermal environment — Analytical determination and interpretation of thermal comfort using calculation of the PMV and PPD indices and local thermal comfort criteria*
- ANSI/ASHRAE Standard 55, *Thermal Environmental Conditions for Human Occupancy* (current edition)
- EN 16798-1:2019, *Energy performance of buildings — Ventilation for buildings — Part 1*
- Bröde, P. et al. (2012), "Deriving the operational procedure for the Universal Thermal Climate Index (UTCI)", *Int. J. Biometeorology* 56:481–494 — the UTCI reference procedure used by §12.7
- Franke, J. et al. (2007), *Best practice guideline for the CFD simulation of flows in the urban environment*, COST Action 732 — FR-W2
- Tominaga, Y. et al. (2008), "AIJ guidelines for practical applications of CFD to pedestrian wind environment around buildings", *J. Wind Eng. Ind. Aerodyn.* 96:1749–1761 — FR-W2
- Kubilay, A., Derome, D., Blocken, B. & Carmeliet, J. (2013), "CFD simulation and validation of wind-driven rain on a building facade with an Eulerian multiphase model", *Building and Environment* 61:69–81 — FR-W8, §13.7
- IES LM-83, *Approved Method: IES Spatial Daylight Autonomy (sDA) and Annual Sunlight Exposure (ASE)* — FR-D4
- EN 17037:2018, *Daylight in buildings* — FR-D6
- [OpenStreetMap copyright and ODbL](https://www.openstreetmap.org/copyright) — FR-B12, §13.10
- **Standards documents are paywalled.** As v1.0 said of ASME V&V 20: obtain each standard before implementing its procedure, rather than working from secondary summaries, and record in the rule pack which edition was used.
