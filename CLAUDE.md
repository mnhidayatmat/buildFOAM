# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A PySide6 desktop application that installs, configures and drives a complete OpenFOAM workflow without the user opening a terminal. The full specification is [`docs/PRD-v1.0.md`](docs/PRD-v1.0.md) — it is the source of truth, and code comments cite it by section (`§7.5`) and requirement id (`FR-S3`, `NFR-M1`, `DEC-14`). **When changing behaviour, check the PRD first**; most non-obvious decisions here are answers to a specific requirement, and the reason is usually written in the module docstring.

Milestones M0–M2 are complete: the app detects/provisions a runtime, opens a case, runs it with the log streaming, and plots residuals. M4 (preprocessor) is next.

## Commands

```sh
uv sync --group dev                       # set up
uv run buildfoam                          # launch the app

uv run python tools/preflight.py          # everything below, stops at first failure
uv run python tools/preflight.py --fast   # skip tests needing a real OpenFOAM

uv run pytest tests/test_case.py -q                       # one file
uv run pytest tests/test_case.py::TestTreeHash -q          # one class
uv run pytest -k "fence and byte" -q                       # by name
uv run pytest -m requires_runtime -q                       # only the real-solver tests
uv run pytest -p no:qt --ignore=tests/test_shell.py        # headless, no Qt libs

uv run ruff check --fix . && uv run ruff format .
```

**There is no CI.** `preflight.py` is the entire safety net — run it before pushing. It cannot check Windows; §12.4's platform acceptance suite is manual.

Qt tests render offscreen (set in `tests/conftest.py`), so no display is needed.

## Four guards that will fail your build

These enforce PRD promises no type system can hold. Each has been caught doing its job during development — treat a failure as the guard working, not as an obstacle.

| Guard | Rule |
|---|---|
| `check_no_qt.py` | `foamwb.services` imports no Qt. Only `foamwb/ui/` may. AST-based, so a docstring mentioning PySide6 is fine but a deferred import inside a function is not. |
| `check_branding.py` | The product name appears **exactly twice**, both in `src/foamwb/branding.py`. Everything else derives from `APP_ID`/`APP_DISPLAY_NAME` — including in docstrings, where a literal `.buildfoam/case.json` becomes wrong after a rename (DEC-03 leaves the name open until M8). |
| `check_version_literals.py` | No OpenFOAM version (`v2512`) or lineage-specific dictionary name (`transportProperties`) in code. Read them from `src/foamwb/data/runtime-manifest.json`, which is exempt. |
| `check_translatable.py` | Text setters take their argument from `foamwb.ui.strings` or `tr()`. **f-strings are rejected outright** — they cannot be extracted and a translator cannot reorder their parts. Compose with catalogue format strings (`"{0}  {1}"`). |

## Architecture

### The layering is the load-bearing decision

```
foamwb/ui/         PySide6. The only subtree allowed to import Qt.
foamwb/services/   Pure Python. No Qt. Exercised headlessly; could back a CLI.
```

Services communicate upward through plain callbacks and return values, never signals. This is why the golden-case gate can run the *same* `RunController` a user's run goes through, in a container with no Qt installed.

### Everything runs through `RuntimeSession`

`services/runtime/session.py` abstracts "run a command in an OpenFOAM environment". `NativeSession` is the only implementation and has **two modes**: a launcher script (macOS app bundle) or sourcing `etc/bashrc` (Debian/Linux). The bashrc mode is §3.2's command bridge verbatim, which is what `WslSession` will need at M3. `WslSession` and `DockerSession` (FR-R10, Intel Macs) do not exist yet.

Callers never build shell strings. `argv` is a token list and the bashrc mode expands it with `"$@"`, so a case path with a space or `$` stays one argument.

Processes own a **process group**, not a process — an MPI job is a tree and signalling only its root orphans the ranks (FR-S10).

### `FoamDict`: byte-fidelity is a property of the data structure

`services/foamdict/` is the M1 gate and the guarantee everything else rests on. **Every character lands in exactly one token**, so `render()` is a concatenation and byte-identical round-trip cannot be got wrong by an emitter. The lexer asserts this on every parse.

The corollary is what makes it usable: because fidelity does not depend on understanding the grammar, the *structural* parser is deliberately tolerant. It models what a form editor can edit and marks everything else opaque — `#ifeq`/`#else`, `#codeStream`, `#eval{}`, macro inclusion, bare top-level lists. It still rejects structural impossibility (E-C02), and OpenFOAM's own `fatal-*.dict` fixtures are in the corpus as a **must-reject** set.

If you touch the lexer, run the wide sweep over a real installation, which is how the tolerated constructs were found in the first place:

```sh
FOAMWB_TUTORIALS=/Volumes/OpenFOAM-v2512/tutorials uv run pytest tests/test_foamdict_sweep.py
```

### Two numerical gates, valid under different conditions

CFD output is **not bit-reproducible** across compiler, MPI or CPU generation, so §12.3 splits the gate:

- **Editor invariance** — rewrites every dictionary in a case (what a no-op form save does), reruns it, asserts every functional is *identical*. Needs no reference values; valid anywhere.
- **Absolute references** — `tests/golden/references.json`, captured on a pinned toolchain and stored with the fingerprint they belong to. On a different toolchain they **skip and name the mismatch**, because a cross-toolchain comparison is invalid rather than lenient.

Regenerate references only via `tools/capture_golden.py`, in a commit that states why. A drift is a defect until proven an intended upstream change.

`tests/corpus/` (368 vendored dictionaries) and the golden references are **data with recorded hashes**. Never hand-edit them; use `tools/vendor_corpus.py`. `.gitattributes` sets `* -text` because Git for Windows would otherwise rewrite line endings and break every corpus hash.

### Versions live in data

`src/foamwb/data/runtime-manifest.json` is the only place OpenFOAM versions and dictionary filenames exist. Services ask for a *role* (`transport`, `turbulence`) and the manifest answers with a filename — that indirection is what keeps Foundation-lineage support additive (DEC-15) instead of a fork of every call site.

### The status footer must never lie

§7.9 rule 4. `RuntimeStatus` refuses to construct in any non-ready state without a §9 error code (FR-R2), and one shell setter drives both the footer and the Hub banner so they cannot disagree. Colour is never the sole carrier of meaning: every state also has a distinct glyph *shape* and a text label (NFR-A2), and both palettes are asserted against the WCAG formula in `tests/test_theme.py`.

### Things that must stay off the GUI thread

Anything that blocks: runtime detection (`ui/probe.py`) and run execution (`ui/run_worker.py`). The worker **batches log lines** rather than signalling per line — at NFR-P3's 5,000 lines/s, one signal per line floods the event loop.

Modal dialogs are injectable (`Shell.set_dialogs`). A hard-coded `QFileDialog` blocks until a human answers, which once hung the whole suite and meant the path users take most was the one path no test could exercise.

## Conventions worth matching

- Module docstrings explain **why**, citing the PRD. Comments state the consequence of the alternative, not what the line does.
- User-facing failures carry a §9 code from `foamwb/codes.py`, so support starts from a code rather than a screenshot. Add codes; never renumber them.
- Absence is usually a state, not an error — `ParaViewService.locate()` returns `None`, a missing runtime is `RuntimeState.MISSING` with `E-R10`.
- Anything the application writes into a user's case is fenced, disclosed and byte-reversibly removable (`services/fence.py`, NFR-C3). Removing it restores the file exactly.
- `tests/fakes.py` holds a hand-written `FakeSession`; prefer it to mocks. Tests that need real OpenFOAM are marked `requires_runtime`.
