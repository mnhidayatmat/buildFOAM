# BuildFOAM

**A desktop workbench for OpenFOAM®** — installs, configures and drives a complete OpenFOAM workflow (mesh, solve, visualise) without the user ever opening a terminal.

> BuildFOAM is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.

**Status: M0 — foundations.** The application does not run yet. What exists is the repository, CI, the licence, the two interfaces everything else is built on (`RuntimeSession` and `RunPlan`), structured logging, and the three architectural guards described below. The specification is [`docs/PRD-v1.0.md`](docs/PRD-v1.0.md).

---

## Layout

```
src/foamwb/            Application. The import package is deliberately not named
  branding.py          for the product — see "The rename guard" below.
  codes.py             §9 error taxonomy: stable codes + guide anchors
  logs.py              Structured JSON-lines logging (NFR-M4)
  paths.py             Host-side application paths (§5.3)
  services/            Pure Python. No Qt. Exercised headlessly.
    run/plan.py        RunPlan / Stage — the §4.3 abstraction
    runtime/session.py RuntimeSession / Process — the §4.2 abstraction
    runtime/status.py  RuntimeStatus with a machine-readable reason (FR-R2)
  ui/                  PySide6. The only subtree permitted to import Qt. Empty until M1.
tools/                 The three CI guards
tests/                 pytest suite, including tests of the guards themselves
```

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                      # create the environment
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format

uv run python tools/check_no_qt.py
uv run python tools/check_branding.py
uv run python tools/check_version_literals.py
```

CI runs all of the above on macOS and Windows. Linux is not a desktop target (NG4), but it becomes a CI target at M2 for the golden-case regression (§12.3), which needs a real OpenFOAM install.

## Three guards worth understanding before you commit

Each of these enforces a promise the PRD makes that no type system can hold.

**`check_no_qt.py` — the service layer imports no Qt** (NFR-M1, §4.1). Services must be testable headlessly and reusable by a future CLI. AST-based, so documenting the rule in a docstring is not a breach, but a deferred import inside a function still is. Only `src/foamwb/ui/` is exempt.

**`check_branding.py` — the product name appears exactly twice** (NFR-M5). Both occurrences are in `src/foamwb/branding.py`, one per constant; every path, bundle identifier, distro name, metadata directory and content namespace is derived from them. DEC-03 knowingly accepts a trade-mark risk in the name and leaves the decision open until M8 — this guard is what keeps reversing it a two-line change instead of an excavation. Need the name somewhere? Derive it, or add a derived constant to `branding.py`.

The declared migration-shim surface, outside the guard's scope: `pyproject.toml` (distribution name), this README, `CITATION.cff`, `docs/`, and the CI workflow.

**`check_version_literals.py` — no OpenFOAM version or lineage names in code** (NFR-M3, §3.4). Release identifiers live in the runtime manifest and dictionary filenames come from its `dictionaries` block, so a new ESI release ships without an application release and the Foundation lineage stays additive (DEC-15). `src/foamwb/data/` is exempt — the manifest is *supposed* to name versions.

## Two decisions already load-bearing in the code

**DEC-06 — parallel-aware from M0.** v1.0 exposes sequential runs only, with `n_procs` fixed at 1, but `RunPlan` implements the full stage machinery. Hard-coding a serial pipeline is forbidden. `tests/test_run_plan.py` renders plans at `n_procs > 1` and asserts the `mpirun -np N … -parallel` form, so a serial short-cut fails CI now rather than surfacing at M10 as a rewrite.

**FR-R2 — a runtime is never un-diagnosably broken.** `RuntimeStatus` refuses to construct in any non-ready state without a §9 code. The status footer is always visible and always truthful (§7.9), which is only achievable if "not working" is a value with structure.

## Licence

GPL-3.0-or-later (DEC-09). See [`LICENSE`](LICENSE).

OpenFOAM is invoked as a separate process, not linked. Trade-mark rules per §13.3 apply: the name must never take the `OpenFOAM <Something>` form, the mark carries ® on first prominent use, and the non-endorsement notice appears in the setup wizard, the About dialog, this README and the release page.
