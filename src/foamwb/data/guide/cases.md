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
