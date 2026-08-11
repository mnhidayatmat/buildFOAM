# Results

Looking at what a run produced.

## ParaView not found

**E-V01.** No ParaView installation was found on this machine.

ParaView is separate software and is not installed with this application. Setup
can download it, or you can point at a copy you already have. Everything else —
residuals, monitors, the y+ audit — works without it.

## ParaView open failed

**E-V02.** ParaView started but could not open the case.

The usual causes are a case with no written time directories yet, and a run whose
final write was interrupted. If a run was stopped with *Stop Now* or *Force
Kill*, the last time directory may be incomplete; delete it and open the previous
one. *Stop & Write* exists to avoid exactly this.
