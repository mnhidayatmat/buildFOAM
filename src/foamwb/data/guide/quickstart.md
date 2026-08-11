# Quick start

From nothing to a finished simulation, in the order the workflow panel lists.

## What a CFD case is

An OpenFOAM case is a folder of text files, not a document. Three directories
matter:

| Directory | Holds |
|---|---|
| `system` | How to solve: end time, time step, schemes, linear solvers |
| `constant` | What is being solved: fluid properties, turbulence model, and the mesh |
| `0` | Where the solution starts: one file per field |

Nothing is hidden. Every setting you change here is a line in one of those
files, and the property panel names the file each setting came from so you can
find it again from a terminal, in a paper, or on someone else's machine.

## Open a case

Start from a case that already works. The Library has several, installed and
ready to run in one action; the lid-driven cavity is the traditional first one
and takes seconds to solve.

Most OpenFOAM tutorials ship their initial conditions in a folder called
`0.orig` and expect you to copy it to `0` before running. Opening a case here
does that for you.

## Generate the mesh

The mesh is the set of cells the equations are solved on. `blockMesh` builds one
from the block description in `system/blockMeshDict`; `checkMesh` then reports
whether it is usable.

Take `checkMesh` seriously. A mesh with errors produces a run that either
diverges twenty minutes later or converges to something wrong, and the check
costs seconds.

## Set the physics

Work down the Conditions group:

- **Analysis type** — steady or transient, and which turbulence model. If you do
  not know, the Verification view will ask about your flow and recommend one.
- **Basic settings** — end time, time step, how often results are written.
- **Initial conditions** — what every cell starts from.
- **Boundary conditions** — every patch and every field. The matrix shows all of
  them at once, because a boundary condition that is wrong is usually wrong
  relative to another one.
- **Solution control** — discretisation schemes and linear solvers. The defaults
  in a working tutorial are a better starting point than anything chosen from
  first principles.

## Check the setup

Runs before the solver does and reports what would stop it: a field with no
initial condition, a patch a field never mentions, a boundary condition that is
illegal on its patch type.

A clean result means the case does not contradict itself. It does not mean the
case is right — that is a different question, and the Verification view is where
it is asked.

## Run

The stage strip shows every stage before any of them run. Residuals plot live.

Three ways to stop, and the difference matters:

- **Stop & Write** asks the solver to write the current time and exit cleanly.
  The result stays complete and reopens. Use this one.
- **Stop Now** signals the solver to quit. Whatever it was writing may be
  incomplete.
- **Force Kill** ends the process immediately.

## Look at the results

The Results view opens the case in ParaView, and runs the standard utilities —
velocity magnitude, vorticity, wall shear stress, y+ — without a terminal.

## Then check whether you believe it

A run that converges is not a run that is right. The Verification view holds the
turbulence model choice, the y+ audit that says whether the mesh matches the
model's assumptions, and the mesh study.

This is the step most often skipped, and the one that decides whether the answer
means anything.
