# Running a case

What happens when you press Run, and what the failures mean.

## Divergence

**E-S03.** The solution stopped being physical: a residual became `nan`, or the
solver hit a floating-point exception and stopped.

OpenFOAM does not announce this. It has no divergence message at all — a run
either dies with a C++ stack trace or quietly fills its residuals with `nan` and
keeps iterating. That is why this application says it instead.

Divergence almost always means the numerics were asked for more than they can
do. In rough order of how often it is the cause:

- **The time step is too large.** For a transient run, halve `deltaT`, or turn on
  `adjustTimeStep` with a `maxCo` of about 1 and let the solver choose.
- **Relaxation is too aggressive.** For a steady run, lower the relaxation
  factors in `fvSolution`. 0.3 for pressure and 0.7 for velocity is the usual
  starting point; 1.0 for both will diverge on most cases.
- **The mesh is poor.** Check the *Check setup* step and the `checkMesh` output.
  High non-orthogonality needs matching `nNonOrthogonalCorrectors`.
- **The initial conditions are far from anything physical.** A velocity field
  that starts at the inlet value everywhere converges more readily than one that
  starts at zero, on some cases.
- **The boundary conditions do not balance.** A case with a fixed velocity at
  every boundary and no pressure reference has no unique solution.

Divergence is not a bug in the solver, and re-running unchanged will reproduce
it exactly.

## Floating point

**E-S04.** The solver performed an arithmetic operation with no finite result —
a division by zero, or the square root of a negative number.

In practice this is [divergence](#divergence) caught at the exact moment it
happened, because OpenFOAM enables floating-point trapping by default. The stack
trace in the log names C++ internals rather than anything in your case; it is not
useful to read. Treat this as a divergence and work through the causes above.

## Mesh failed

**E-S01.** `blockMesh` or the mesher could not produce a mesh.

The log names the reason and usually the line. The most common causes are a
`blockMeshDict` whose vertex list and block topology disagree, a face defined in
the wrong rotational order, and a patch that names a face already claimed by
another patch.

Mesh settings edits the scalar entries; the vertex and block lists are edited in
the Text tab, because a form that offered to change one vertex would invite edits
that leave the topology inconsistent.

## checkMesh errors

**E-S02.** The mesh was generated, but `checkMesh` found faults in it.

This gates the solver deliberately. A mesh with errors produces a run that
either diverges twenty minutes later or converges to something wrong, and
learning about it now costs seconds.

The faults that matter most:

- **Negative volume cells** — the mesh is invalid and no solver setting rescues
  it.
- **High non-orthogonality** (above about 70) — usable with
  `nNonOrthogonalCorrectors` raised, unstable without.
- **High skewness** (above about 4) — degrades accuracy near the offending cells.

Warnings about aspect ratio on a deliberately thin 2D mesh are expected.

## Solver not found

**E-S05.** The named solver is not in the runtime's path.

Check the spelling in the *Basic settings* step. OpenFOAM's solver names are
case-sensitive: `simpleFoam`, not `simplefoam`. If the name is right, the
runtime may be incomplete — run the system check in Setup.

## Out of memory

**E-S06.** The run exhausted available memory and was stopped.

A rough guide is one gigabyte per two to four million cells for an
incompressible steady case, more for transient, multiphase or compressible runs.
Options, cheapest first: run in parallel across more cores so each holds a
smaller piece, coarsen the mesh, or write results less often.

## Disk full

**E-S07.** The disk filled while the run was writing.

A transient case writing every time step can produce hundreds of gigabytes.
Raise `writeInterval`, set `purgeWrite` to keep only the last few times, or move
the case to a larger disk. Results already written are intact; the run stopped
rather than corrupting them.

## Decomposition mismatch

**E-S08.** The number of processes asked for does not match
`numberOfSubdomains` in `system/decomposeParDict`.

The two must agree. Change the process count in the run options, or edit
`numberOfSubdomains` and run `decomposePar` again.

## Setup error

**E-S09.** OpenFOAM rejected the case before it could run — a missing file, an
unknown keyword, a value it could not parse.

The message quotes what the solver said, which normally names the file and the
line. This is not a numerical problem: the case has not started solving. The
most common instances are a field the solver needs that has no file in `0`, and
a keyword misspelled in a dictionary.

## Solver failed

**E-S10.** The solver stopped without saying why.

Deliberately vague, because the exit status alone cannot distinguish a diverged
run from a mistyped keyword — OpenFOAM exits with status 1 for both. Rather than
name a cause that was never established, this code says the log did not explain
it. Read the end of the log directly; the answer is usually in the last twenty
lines.
