# Cases

Opening, editing and validating an OpenFOAM case.

## Not a case

**E-C01.** The chosen folder is not an OpenFOAM case.

A case has a `system` directory containing `controlDict`, and a `constant`
directory. If you chose the folder *above* the case — the one holding several
cases — open one of the folders inside it instead. Some tutorials keep the case
one level down, beside an `Allrun` script.

## Parse error

**E-C02.** A dictionary could not be read.

The message names the file and the line. The usual causes are a missing
semicolon at the end of an entry, an unclosed brace, and a comment started with
`#` instead of `//`.

Every file is left exactly as it was; nothing is repaired automatically, because
guessing at what a malformed file meant is how an editor destroys work.

## Missing boundary field

**E-C03.** A field file has no entry for a patch that exists in the mesh.

Every patch in `constant/polyMesh/boundary` needs an entry in every field's
`boundaryField`, or the solver stops at startup. Add the patch to the field in
*Boundary conditions*.

A `".*"` catch-all entry counts: OpenFOAM matches patch names against the keys as
regular expressions, and the last match wins.

## Missing field

**E-C08.** `system/fvSolution` names a field to solve for, and the initial
conditions directory has no file for it.

The solver stops before its first time step with *cannot find file*. This is one
of the most common ways a case fails, and it has a common cause: most tutorials
ship their initial conditions as `0.orig` rather than `0`, and expect you to copy
the directory before running. Opening a case here does that for you; a case
copied by hand may not have had it done.

Only unambiguous field names are checked. A solver block key like
`"(U|k|epsilon|omega)"` is a pattern that most cases only partly satisfy, so it
is skipped rather than reported.

## Patch BC mismatch

**E-C04.** A boundary condition is not legal on that type of patch.

Some patch types dictate their condition entirely:

| Patch type | The only legal condition |
|---|---|
| `empty` | `empty` |
| `symmetry`, `symmetryPlane` | matching the type |
| `wedge` | `wedge` |
| `cyclic`, `cyclicAMI` | matching the type |

These are geometric statements, not modelling choices. An `empty` patch marks the
front and back of a 2D case; giving it a real boundary condition means the case is
silently solving a three-dimensional problem on a one-cell-thick mesh.

Change the condition in *Boundary conditions*, or change the patch type in
*Regions and patches* — which will tell you which fields must follow.

## Modified externally

**E-C05.** The case changed on disk since it was opened.

Something else edited the files — another editor, a script, or a run started from
a terminal. Nothing has been lost. Choose whether to keep what is on disk or to
reload; the application does not decide for you, because either could be the
version you want.

## Slow storage

**E-C06.** The case is on a network drive, or on a path that is slow for many
small files.

An OpenFOAM write interval creates one file per field per process. On a network
share or a Windows drive seen from inside WSL, that is roughly an order of
magnitude slower than a local disk, and a long run may spend more time writing
than solving. Move the case to local storage.

## Version mismatch

**E-C07.** The case was written for an OpenFOAM release this runtime does not
support.

Cases are usually forward-compatible, and most will run. The risk is dictionary
keywords that were renamed between releases, which produce a *setup error* at
startup rather than a wrong answer. If the case is from the Foundation lineage —
`openfoam.org` rather than `openfoam.com` — expect differences in file names as
well as keywords.

## Geometry unreadable

**E-C09.** The file was found but is not a surface.

The usual causes, in the order they happen:

- The download did not finish, so the file ends part-way through a facet.
- The file is not geometry at all. A browser that met an error page while
  downloading will save that page under the name you asked for, so a `.stl` of a
  few kilobytes that opens as text in an editor is almost always HTML.
- The exporter wrote an empty surface, usually because nothing was selected.

The file is checked on import rather than when the mesh runs. `snappyHexMesh`
reads it several minutes into a meshing job and reports it as a meshing failure,
which points at the mesh settings instead of at the file.

## Geometry unsupported

**E-C10.** The file is a native CAD document, which nothing here can open.

Formats like `.sldprt`, `.catpart`, `.prt` and `.3dm` are private to the program
that wrote them. No converter on your machine will help, because the format is
not published.

Export a neutral format from the CAD package instead. In order of preference:

| Export as | Why |
|---|---|
| **STL** | Read directly. You control the tessellation tolerance in the exporter, where you can see the model. |
| **STEP** (`.step`, `.stp`) | Converted here, if a converter is installed. Keeps exact surfaces, so it can be re-tessellated later. |
| **IGES** (`.iges`, `.igs`) | Works, but older and more likely to arrive with unhealed surfaces. |

When exporting STL, choose a *fine* or *custom* tolerance rather than the
default. A coarse tessellation shows as flat facets on curved surfaces, and the
mesher will faithfully reproduce every one of them.

## CAD converter missing

**E-C11.** The file is a STEP or IGES model, and no geometry kernel was found.

OpenFOAM meshes triangulated surfaces. A STEP file describes exact trimmed
surfaces, so something has to tessellate it first, and that converter is not part
of this application — it is a large component under a different licence, and most
users never need it because they export STL from their own CAD package.

Two ways forward:

- **Export STL** from whatever produced the STEP file. This is usually better
  anyway: the exporter can see the model, so you can judge the tolerance.
- **Install Gmsh** from `gmsh.info`, which is free and available for Windows,
  macOS and Linux. It is found automatically once installed; on macOS, put
  `Gmsh.app` in Applications.

## CAD conversion failed

**E-C12.** The converter ran but produced no usable surface.

The output from the converter is shown with the error, and the reason is
generally in it. The common ones:

- **The solid is not closed.** Exchange formats often arrive with small gaps
  between surfaces. Most CAD packages have a *heal* or *sew* operation; run it
  before exporting.
- **The tolerance could not be met.** Very small features against a large model
  make the kernel subdivide until it gives up. Set a maximum element size on
  import, or simplify the features that do not matter to the flow.
- **The file holds no solid geometry** — only curves, sketches or reference
  planes. There is nothing to tessellate.

Nothing is left behind by a failed conversion: no partial surface is written into
the case, so there is no half-model to find and delete before trying again.

## New case exists

**E-C13.** There is already something in the folder you asked to create.

Nothing was written. A new case is only ever created into an empty folder,
because merging into an existing one would overwrite files you may still need and
there is no undo for that.

Either pick a different name, or open what is already there — if it is a case,
*Open Case* will read it.

## New case name

**E-C14.** The name cannot be used as a folder name.

Case names become folder names, and folder names become paths that OpenFOAM's own
utilities pass around. These characters are refused:

```
< > : " / \ | ? *
```

Leading and trailing spaces are refused too. They survive on macOS and Linux and
are silently dropped by Windows, so the same case would live at two different
paths depending on the machine.

Letters, digits, hyphens and underscores are always safe.

## New case not writable

**E-C15.** The folder could not be created where you asked.

The destination exists but cannot be written to. The usual causes are a
read-only volume, a network share mounted without write permission, or a folder
owned by another user.

Choose somewhere inside your home directory. Avoid creating cases inside the
OpenFOAM installation itself — on most systems that needs administrator rights,
and a case there is lost when the runtime is updated.

## No geometry to mesh

**E-C16.** There is no surface in the case to build a mesh around.

`snappyHexMesh` cuts a background mesh down onto a surface, so it needs one.
Import an STL, OBJ, STEP or IGES file in the *Geometry* tab first.

If you imported something and it is not listed, it was rejected as unreadable —
see **Geometry unreadable** above.

You do not need this path at all if your case is meshed by `blockMesh` alone.
A case with its own `blockMeshDict` already offers *blockMesh* in the *Mesh* tab.

## Mesh dict exists

**E-C17.** The case already has `blockMeshDict`, `snappyHexMeshDict`, or both.

Nothing was written. These may be dictionaries you or a tutorial tuned, and
regenerating them would discard that work — the generated pair is a sensible
starting point, not an improvement on something already set up.

Choose *Replace* if you want the generated versions. The existing files are
overwritten at that point, so copy them elsewhere first if you may want them
back.

## The generated mesh is empty or inside out

Not an error code — `snappyHexMesh` reports success and produces a mesh that is
empty, or that contains the inside of your solid rather than the fluid around it.

Almost always `locationInMesh`, in `system/snappyHexMeshDict`. It names a point
in the region to **keep**:

- **Flow around a body** (external): the point must be outside the surface,
  somewhere in the open space of the domain. Generated near a corner, which the
  padding keeps empty.
- **Flow through a duct** (internal): the point must be inside the surface.
  Generated at the centre of the geometry's bounding box, which is right for a
  straight duct and can fall in the solid for a strongly curved one.

If the generated point is wrong, set it yourself in the *Mesh* tab or edit the
entry directly. Choosing the wrong *flow region* when generating produces exactly
this symptom, and switching it and regenerating is the quickest fix.

A second cause, much rarer: the surface is not closed, so there is no inside and
outside to separate. `surfaceCheck` on the STL reports this.
