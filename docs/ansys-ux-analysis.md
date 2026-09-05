# Ansys Fluent UI/UX analysis, and how BuildFOAM was converted to it

*Companion to DEC-21, DEC-22 and DEC-23. The PRD (§7.1, §7.2, §7.4, §7.5, §13.3) is the
specification; this is the analysis behind it and the record of what changed.*

## 1. What "the Fluent interface" is

Ansys is not one interface but three, and they share a grammar. Fluent is the
one that matters here, because it is the direct analogue of what BuildFOAM does:
a pre-processor, a solver driver and a monitor in one window.

### 1.1 The single window (Fluent 2019 R3 onwards)

```
┌ Ribbon: File | Domain | Physics | User-Defined | Solution | Results | View | Parallel ┐
├ Outline View ─────────┬ Graphics window (tabbed: Mesh · Scaled Residuals · Contour-1) ┤
│  Setup                │                                                              │
│    General            │                                                              │
│    Models             │                                                              │
│    Materials          │                                                              │
│    Cell Zone Cond.    │                                                              │
│    Boundary Cond.     │                                                              │
│    Reference Values   │                                                              │
│  Solution             │                                                              │
│    Methods            │                                                              │
│    Controls           │                                                              │
│    Monitors           │                                                              │
│    Initialization     │                                                              │
│    Calculation Activ. │                                                              │
│    Run Calculation    │                                                              │
│  Results              │                                                              │
├ Task Page ────────────┤                                                              │
│  (form for the        │                                                              │
│   selected node,      ├ Console ─────────────────────────────────────────────────────┤
│   OK / Apply / Close) │  > solver transcript, warnings, the TUI echo                  │
├───────────────────────┴──────────────────────────────────────────────────────────────┤
│ status bar                                                                           │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Six properties, in decreasing order of how much they change what a user can do
as opposed to how the window looks:

| # | Pattern | What it buys |
|---|---|---|
| A | **Outline View** is the primary navigation, and it is the *structure of the case in setup order* — not a set of places | A user who does not know what a CFD case consists of is told by the shape of the window |
| B | **Task Page** under the tree, changing with the selection | The settings for a thing sit under the name of that thing |
| C | **Graphics window** is the persistent centre, tabbed by document, never covered by a form | The mesh and the residual plot are one click apart, and a form never takes the screen |
| D | **Console** docked at the bottom, always reachable, collapsible | Everything the application did on your behalf is in one place |
| E | **Ribbon** grouping actions by stage, each button icon-over-label under a group caption | Discoverability: you can see what the application can do without opening a menu |
| F | Node **status glyphs** (✓ done, ○ outstanding) and a filter box on the tree | Progress is readable without a legend |

### 1.2 Fluent Meshing's Watertight Geometry Workflow

A guided task list — *Import Geometry → Add Local Sizing → Generate Surface Mesh
→ Describe Geometry → Update Boundaries → Update Regions → Add Boundary Layers →
Generate Volume Mesh* — each task with a status, each opening a small parameter
panel with one **Update** button, and each marking the tasks after it out of
date when its parameters change.

### 1.3 Workbench and Mechanical, for reference

Workbench's **Project Schematic** contributes the idea of *dependency-aware
status*: editing Geometry marks Mesh, Setup, Solution and Results as needing
update, and one *Update Project* verb runs whatever is stale, in order.
Mechanical contributes the **Details** pane under the outline, with required-
but-empty fields highlighted. The first of these is in (§4); the second is not.

### 1.4 What must not be copied

§13.3 governs. The interaction *patterns* above are industry convention and
predate Ansys — ribbons, outline trees, details panes and status glyphs are in
every engineering application — and the outline's vocabulary is the vocabulary
of the field, which is why P3 recognises it. Ansys's **icons, artwork, colour,
logos, product names and wording** are its own and none of them is used. The
application keeps its own palette (checked against WCAG in `test_theme.py`), its
own glyph icons drawn from Unicode in the interface font, and its own §9 error
codes. No screen names an Ansys product except where §1.4 of the PRD says what
BuildFOAM is *not*.

One deliberate departure: **Fluent's console accepts commands and this one does
not.** §1.1 promises a workflow that never opens a terminal, and a console with
a command line would be one. The transcript is read-only; a power user has the
Text tab and the file system (D4).

## 2. What the conversion actually changed

### 2.1 The window

| Before | After |
|---|---|
| Nav rail: Hub, Cases, Setup, Run, Post, V&V, Library, Guide | **Ribbon**: File ▾ · Domain · Physics · Solution · Results · View · Guide |
| Workflow panel (scFLOW-derived, ordered procedure) | **Outline View**: Workflow · Setup · Solution · Results · Files, with a filter box and a state glyph column |
| Property panel as one page of the case view | **Task Page** under the outline, always present, following the selection |
| A stack of full-window views | **Graphics window**: ten document tabs, never replaced by a form |
| Two log panes (Run, Post) plus a validation column on Preprocessor pages | **Console dock**: one transcript, one Messages list, collapsible |
| Back / Next buttons under the content | Gone — the outline and the ribbon are the navigation |
| Status footer | Unchanged |

### 2.2 The outline, node by node

Nodes carry Fluent's names; the file each one edits is named in the task page
underneath, so the user learns the OpenFOAM mapping rather than the interface
(D4).

| Fluent | BuildFOAM node | Reads |
|---|---|---|
| Import Geometry | Import Geometry | `constant/triSurface` |
| Describe Geometry | Describe Geometry | flow region, refinement, background cells |
| Add Local Sizing | Add Local Sizing | `system/blockMeshDict` |
| Update Boundaries | Update Boundaries | `constant/polyMesh/boundary` |
| Generate the Volume Mesh | Generate the Volume Mesh | runs `blockMesh` → `checkMesh` |
| Setup → General | General | `controlDict`: solver, time span |
| Setup → Models | Models | the turbulence dictionary *(from the manifest — the lineages name it differently, NFR-M3)* |
| Setup → Materials | Materials | the transport dictionary |
| Setup → Boundary Conditions | Boundary Conditions | `0/` × `polyMesh/boundary`, as a matrix |
| Setup → Reference Values | Reference Values | the turbulence advisor |
| Solution → Methods | Methods | `system/fvSchemes` |
| Solution → Controls | Controls | `system/fvSolution` |
| Solution → Monitors | Monitors | `controlDict`'s `functions` |
| Solution → Initialization | Initialization | `0/` internal fields |
| Solution → Calculation Activities | Calculation Activities | `controlDict`'s write settings |
| Solution → Run Calculation | Check Case · Run Calculation | validation; the `RunPlan` |
| Results → Graphics / Plots / Reports | Graphics · Plots · Reports | ParaView, residuals, post utilities |
| *(no counterpart)* | Files → Case Files | every dictionary, as it is on disk |

**Omitted rather than offered empty**: Fluent's *Cell Zone Conditions*, *Mesh
Interfaces*, *Named Expressions* and *Report Definitions*. Each would open on a
file most cases do not have, and a node that opens a void is the dead end §7.9
rule 1 forbids. They can be added as the property mapping learns those files.
Fluent Meshing's surface-mesh and boundary-layer tasks have no counterpart in a
`blockMesh`/`snappyHexMesh` chain and are not pretended.

### 2.3 One file, several nodes

Fluent splits `controlDict`'s concerns across three nodes. Showing the whole
file under each would make them look identical and teach the user that the
outline is decoration, so `STEP_SOURCES` now carries the top-level keys each
node owns:

- **General** — `application`, `startFrom`, `startTime`, `stopAt`, `endTime`, `deltaT`
- **Monitors** — `functions`
- **Calculation Activities** — `writeControl`, `writeInterval`, `purgeWrite`, `writeFormat`, `writePrecision`, `writeCompression`, `timeFormat`, `timePrecision`, `runTimeModifiable`, `adjustTimeStep`, `maxCo`, `maxAlphaCo`, `maxDeltaT`

An entry no node claims is still in the file, still editable in the Text tab,
and still byte-identical after a save (FR-P7).

A source may also name a *manifest role* rather than a filename —
`constant/@turbulence` — because ESI and the Foundation call that file different
things and NFR-M3 forbids the name appearing in code.

### 2.4 What did not change

Nothing below the shell. Services still import no Qt (NFR-M1); `FoamDict`'s
byte fidelity, the fenced writes, the `RunPlan`, the golden-case gates, the
error taxonomy and the status footer's honesty rule are all untouched. Every
label still comes from the catalogue (`check_translatable.py`); the ribbon added
about ninety strings. Every state still carries a glyph *shape* and a text label
as well as a colour (NFR-A2), and both palettes are still asserted against the
WCAG formula — the ribbon, outline, task page and console dock are in
`test_contrast_sweep.py` alongside every other view.

`CaseEditors` is the piece that made this affordable: it builds and wires every
editor and arranges none of them, so moving the boundary matrix from a tab into
the graphics window changed where it is placed and nothing about what it does.
`RunView`, `PostView` and `MeshPanel` take the window's console and residual
plot rather than owning private copies, and still construct standalone, which is
what their own tests use.

## 3. What the tests now guarantee

The layout is data in three places, and the tests close the triangle:

- every outline node names a task page **and** a document that exist;
- every ribbon action names a real node **or** has a handler, and nothing is
  handled that the ribbon offers nowhere;
- the task page's header names the selected node whatever page it opens — the
  regression this caught was a node with a missing page leaving the *previous*
  node's title over the previous node's form;
- the graphics window is never emptied by selecting a node;
- a disabled ribbon action explains itself in its tooltip, and re-enabling
  restores the sentence *with* its shortcut;
- no two shortcuts collide.

Full suite: 6 639 tests, all four guards, 92% coverage.

## 4. The Workbench half, added second

The two ideas Workbench contributes are now in (DEC-22).

**Dependency-aware status.** `services/freshness.py` dates a case's two computed
artefacts against the inputs they came from. `StepState.STALE` (↻, amber, "out
of date" on the row, the offending filename in the tooltip) is what the outline
draws, and it propagates downstream: editing `blockMeshDict` marks *Generate the
Volume Mesh* **and** *Run Calculation*. A stale node stops counting as progress
and becomes "what next?" again.

The input sets are deliberately asymmetric, and getting this wrong in either
direction would have made the mark useless:

| Artefact | Inputs | Not inputs |
|---|---|---|
| Mesh | the chain utilities' own `needs` (`blockMeshDict`, `snappyHexMeshDict`, `surfaceFeatureExtractDict`), `constant/triSurface/**` | `controlDict`, `fvSchemes`, `0/` — a mesh is not stale because the end time changed, and marking it would train the user to ignore the mark |
| Results | the whole case definition, mesh included | written time directories, `postProcessing/`, our own metadata — a solver's output is not one of its inputs, and writing a run record must not date the run it records |

Times, not hashes: this runs on every save (NFR-P7), and a hash costs a full read
of `constant/polyMesh`. The weaker test under-reports rather than crying wolf.

**One *Update* verb.** *Solution → Update* (F5) runs whatever is stale, in
order. It is the ordinary plan with the current stages *skipped* rather than a
shorter plan, so the strip still shows the whole run — "blockMesh — skipped"
says the mesh is current, where its absence says nothing. *Calculate* still means
the whole plan; the narrower one is given to a single run and never swapped into
the case's own. Update disables itself with "Everything is up to date." when
there is nothing to do, which is the answer to the question it exists to settle.

One thing Workbench does not do and this does: **every verdict names the file
that caused it.** A user who has edited four things needs to know which one.

## 5. The mesh in the graphics window

The last piece (DEC-23). *Geometry* and *Mesh* are now separate documents: the
first is the imported surface, the second is what the mesher built from it.
`services/polymesh.py` reads the boundary faces of `constant/polyMesh` and hands
back the same `Sample` an STL produces, so the projection, the picking and the
widget are all unchanged — the whole feature is a reader.

| Decision | Why |
|---|---|
| Boundary faces only | A volume mesh's boundary *is* a surface, and internal faces are between two cells where nothing can see them. OpenFOAM stores boundary faces contiguously at the end of `faces`, so each patch's `startFace`/`nFaces` says which part of the file to keep — the internal ones are stepped past, never turned into Python objects |
| Coloured by patch, clickable to select one | "Which patch is that?" is the question the boundary-condition matrix cannot answer. A row called `frontAndBack` says nothing about where on the model it is, and pointing at the face is the only explanation that always works. A click selects the patch in the patch list and does **not** move the user: they pointed at something to find out what it is |
| Thinned *within* each patch | A global stride takes faces in proportion to their number, so a thirty-face inlet beside a twenty-four-thousand-face wall loses every face it has — leaving a patch named in the matrix and nowhere on the model |
| Refused above a size cap | NFR-P3. Refusing in milliseconds with "too large to preview here — open it in ParaView" is honest; a minute of parsing with a frozen window is not, and NG3 already says ParaView opens large results |
| Re-read only when the mesh is written | The document would otherwise be rebuilt on every save, throwing away the angle the user turned the model to. `Freshness` carries the mesh's write time, so the test is exact |

Still a **preview, not a viewer** (NG1, NG3): no fields, no results, no colour
maps, no clipping. Measured at 24 ms for pitzDaily's 12 000-cell mesh.

### Still not taken from Ansys

Mechanical's **Details pane highlighting required-but-empty fields**. The
property table shows what a file contains; it does not yet mark what a schema
says is required and missing. That is the natural next thing, and it is
schema-layer work rather than layout.
