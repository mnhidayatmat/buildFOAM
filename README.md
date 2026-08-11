# BuildFOAM

**A desktop workbench for OpenFOAM®** — installs, configures and drives a complete OpenFOAM workflow (mesh, solve, visualise) without the user ever opening a terminal.

> BuildFOAM is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.

**Status: M4 in progress.** `uv run buildfoam` opens a case, edits its dictionaries through schema-driven forms or a raw-text tab, shows the boundary-condition matrix with live validation, builds a run plan, executes it with the solver log streaming, and plots residuals as they converge. Both numerical gates pass: §12.2's round-trip corpus and §12.3's golden-case regression. Still to come in M4: meshing utilities (FR-P5) and `fvSchemes`/`fvSolution` schemas. The specification is [`docs/PRD-v1.0.md`](docs/PRD-v1.0.md).

---

## Layout

```
src/foamwb/            Application. The import package is deliberately not named
  branding.py          for the product — see "The rename guard" below.
  codes.py             §9 error taxonomy: stable codes + guide anchors
  logs.py              Structured JSON-lines logging (NFR-M4)
  paths.py             Host-side application paths (§5.3)
  data/                The runtime manifest. The only place versions exist.
  services/            Pure Python. No Qt. Exercised headlessly.
    case.py              Open/classify a case, tree hash, metadata (§5.1, §5.2)
    fence.py             The GUI-owned controlDict fence (FR-S3, NFR-C3)
    functionals.py       Scalar reductions for the §12.3 gate
    paraview.py          Locate ParaView, .foam stub (FR-V1, FR-V2)
    monitor.py           solverInfo .dat → time series (DEC-13, FR-S4)
    foamdict/lexer.py    Tokeniser. Byte-conserving by construction.
    foamdict/document.py Tolerant parser + round-trip-faithful editing API
    run/plan.py          RunPlan / Stage — the §4.3 abstraction
    boundary.py          Patch names and types from polyMesh (FR-P4)
    boundary_matrix.py   Patch x field matrix and its findings (FR-P4, E-C03/04)
    schema.py            The §5.4 declarative form layer
    validation.py        Whole-case findings (FR-C3)
    run/controller.py    Executes a plan, streams output (FR-S1, FR-S5)
                         and build_plan() composes one from a case
    runtime/manifest.py  §3.4 version policy, read from data/
    runtime/manager.py   Detection + the canary (FR-R1, FR-R5)
    runtime/native.py    NativeSession — macOS, via the bundle launcher
    runtime/provision.py Plan/install/verify a runtime (FR-R3, FR-R11)
    runtime/session.py   RuntimeSession / Process — the §4.2 abstraction
    runtime/status.py    RuntimeStatus with a machine-readable reason (FR-R2)
  ui/                  PySide6. The only subtree permitted to import Qt.
    theme.py             Light/dark tokens; contrast verified against WCAG AA
    strings.py           The translatable string catalogue (NFR-A5)
    shell.py             Nav rail + view stack + status footer (§7.1)
    probe.py             Off-thread runtime detection (NFR-P1)
    run_worker.py        Runs a plan off the GUI thread, batching output
    views/run.py         The Run view (§7.5)
    views/preprocessor.py  The Preprocessor view (§7.4)
    widgets/             Stage strip, log pane, residual plot,
                         form editor, text editor, BC matrix
tools/                 The four CI guards + the corpus vendoring tool
tests/corpus/          368 dictionaries from 23 tutorial cases, pinned to v2512
tests/                 pytest suite, including tests of the guards themselves
```

## The parser gate (§12.2)

`FoamDict` is the M1 gate and the only mechanical guarantee behind D4 — that every file stays a valid, hand-editable OpenFOAM dictionary. The design point:

**Byte-identical round-trip does not depend on understanding the grammar.** Every character lands in exactly one token, so `render()` is a concatenation and fidelity is a property of the data structure rather than something the emitter has to get right. The lexer asserts this on every parse.

The corollary is what makes the parser usable on real cases: because fidelity is already guaranteed, the *structural* parser is free to be tolerant. It models what a form editor can edit and marks everything else opaque — `#ifeq`/`#else`/`#endif`, `#word`-generated keywords, `#eval{...}`, embedded C++ in `#codeStream`/`#{...#}`, macro inclusion as a dictionary body, bare top-level lists. Those are preserved untouched rather than rejected.

What it does *not* tolerate is structural impossibility — an unbalanced brace, an unterminated string, a missing `;`. Those are E-C02 with file, line and column. OpenFOAM's own `fatal-*.dict` fixtures are in the corpus as a **must-reject** set: a parser loose enough to accept those is loose enough to swallow a user's real mistake.

Coverage:

- **368 vendored dictionaries** from 23 cases (§12.1 axes: incompressible/compressible, steady/transient, blockMesh/snappyHexMesh, single/multiphase), run by every `preflight.py`.
- **9,781 dictionaries** in the full v2512 tutorial suite round-trip byte-for-byte locally. This sweep is opt-in — it needs an OpenFOAM install — and is what to run after any lexer change:

  ```sh
  FOAMWB_TUTORIALS=/path/to/tutorials uv run pytest tests/test_foamdict_sweep.py
  ```

One documented limitation and one upstream defect are recorded in `tests/corpus/corpus.json` with reasons, rather than silently excluded.

## The numerical gate (§12.3)

CFD output is **not bit-reproducible** across compiler, MPI, BLAS or CPU generation, so a hash-equality gate would fail spuriously the moment a CI image changed. The gate is therefore scalar functionals with explicit tolerances, and it splits in two:

- **Editor invariance** runs on any toolchain. It parses and rewrites every dictionary in a case — the operation a form save performs when the user changes nothing — reruns the case, and asserts every functional is *identical*. §12.3 calls this "the one that actually protects users: it proves the editor changed nothing numerical, independently of whether the solver is reproducible."
- **Absolute references** compare against values captured on a pinned toolchain, recorded in `tests/golden/references.json` alongside the fingerprint they are only valid against. On a different toolchain they skip, naming the mismatch — a cross-toolchain comparison is invalid, not merely lenient.

References are regenerated only by `tools/capture_golden.py` in an explicit, reviewed commit that states why. A drift is a defect until proven to be an intended upstream change.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                      # create the environment
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format

uv run buildfoam             # launch the shell

uv run python tools/preflight.py          # everything below, in order
uv run python tools/preflight.py --fast   # skip the tests that need OpenFOAM
```

**There is no CI.** `preflight.py` is the whole safety net, so run it before you push — it runs lint, format, the four architectural guards, the test suite and the §12.3 numerical gate, stopping at the first failure.

What it cannot check, and no local run can: **Windows**. The product targets both platforms (§3.1) and this is one of them. The Windows paths in `foamwb.paths` are exercised through monkeypatched tests, which prove the logic and nothing about the platform. §12.4's platform acceptance suite is manual and gated on release for that reason.

Qt widget tests render offscreen, so the suite needs no display and works over ssh. Tests marked `requires_runtime` exercise a real OpenFOAM installation and skip when none is present:

```sh
uv run pytest -m requires_runtime      # needs OpenFOAM installed
```

## Four guards worth understanding before you commit

Each of these enforces a promise the PRD makes that no type system can hold.

**`check_no_qt.py` — the service layer imports no Qt** (NFR-M1, §4.1). Services must be testable headlessly and reusable by a future CLI. AST-based, so documenting the rule in a docstring is not a breach, but a deferred import inside a function still is. Only `src/foamwb/ui/` is exempt.

**`check_branding.py` — the product name appears exactly twice** (NFR-M5). Both occurrences are in `src/foamwb/branding.py`, one per constant; every path, bundle identifier, distro name, metadata directory and content namespace is derived from them. DEC-03 knowingly accepts a trade-mark risk in the name and leaves the decision open until M8 — this guard is what keeps reversing it a two-line change instead of an excavation. Need the name somewhere? Derive it, or add a derived constant to `branding.py`.

The declared migration-shim surface, outside the guard's scope: `pyproject.toml` (distribution name), this README, `CITATION.cff`, `docs/`, and the CI workflow.

**`check_version_literals.py` — no OpenFOAM version or lineage names in code** (NFR-M3, §3.4). Release identifiers live in the runtime manifest and dictionary filenames come from its `dictionaries` block, so a new ESI release ships without an application release and the Foundation lineage stays additive (DEC-15). `src/foamwb/data/` is exempt — the manifest is *supposed* to name versions.

**`check_translatable.py` — user-visible strings are externalised** (NFR-A5). "The extraction discipline starts immediately." The expensive part of retrofitting i18n is not translating, it is *finding* the strings — they accumulate one convenient literal at a time. Text setters must take their argument from `foamwb.ui.strings` or `tr()`. f-strings are rejected outright: they cannot be extracted, and a translator cannot reorder their parts for a right-to-left locale.

## Two decisions already load-bearing in the code

**DEC-06 — parallel-aware from M0.** v1.0 exposes sequential runs only, with `n_procs` fixed at 1, but `RunPlan` implements the full stage machinery. Hard-coding a serial pipeline is forbidden. `tests/test_run_plan.py` renders plans at `n_procs > 1` and asserts the `mpirun -np N … -parallel` form, so a serial short-cut fails CI now rather than surfacing at M10 as a rewrite.

**FR-R2 — a runtime is never un-diagnosably broken.** `RuntimeStatus` refuses to construct in any non-ready state without a §9 code. The status footer is always visible and always truthful (§7.9), which is only achievable if "not working" is a value with structure. One setter drives both the footer and the Hub banner, so they cannot disagree.

**NFR-M3 — versions live in data, not code.** `src/foamwb/data/runtime-manifest.json` is the only place an OpenFOAM version or a lineage-specific dictionary name appears. Services ask for a *role* (`transport`, `turbulence`) and the manifest answers with a filename, which is what keeps Foundation-lineage support additive (DEC-15) rather than a fork of every call site.

**NFR-A2 — contrast is checked, not eyeballed.** Both palettes are asserted against the WCAG 2.1 formula in `tests/test_theme.py`, so a well-meant colour tweak cannot push the footer below legibility. Colour is never the sole carrier of meaning: each runtime state has a distinct glyph *shape* and a text label, so the footer reads correctly in greyscale, in a support screenshot, and to a colourblind user.

## Licence

GPL-3.0-or-later (DEC-09). See [`LICENSE`](LICENSE).

OpenFOAM is invoked as a separate process, not linked. Trade-mark rules per §13.3 apply: the name must never take the `OpenFOAM <Something>` form, the mark carries ® on first prominent use, and the non-endorsement notice appears in the setup wizard, the About dialog, this README and the release page.
