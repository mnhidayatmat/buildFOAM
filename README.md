# BuildFOAM

**A desktop workbench for OpenFOAM®** — installs, configures and drives a complete OpenFOAM workflow (mesh, solve, visualise) without the user ever opening a terminal.

> BuildFOAM is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.

**Status: M1 complete.** The shell launches (`uv run buildfoam`) with the Hub, nav rail, status footer and view stack, and **`FoamDict` passes the §12.2 round-trip corpus test** — the gate §11 says must not be passed without. No runtime is detected and no case can be opened yet; those are M2 and M4. The specification is [`docs/PRD-v1.0.md`](docs/PRD-v1.0.md).

---

## Layout

```
src/foamwb/            Application. The import package is deliberately not named
  branding.py          for the product — see "The rename guard" below.
  codes.py             §9 error taxonomy: stable codes + guide anchors
  logs.py              Structured JSON-lines logging (NFR-M4)
  paths.py             Host-side application paths (§5.3)
  services/            Pure Python. No Qt. Exercised headlessly.
    foamdict/lexer.py    Tokeniser. Byte-conserving by construction.
    foamdict/document.py Tolerant parser + round-trip-faithful editing API
    run/plan.py          RunPlan / Stage — the §4.3 abstraction
    runtime/session.py   RuntimeSession / Process — the §4.2 abstraction
    runtime/status.py    RuntimeStatus with a machine-readable reason (FR-R2)
  ui/                  PySide6. The only subtree permitted to import Qt.
    theme.py             Light/dark tokens; contrast verified against WCAG AA
    strings.py           The translatable string catalogue (NFR-A5)
    shell.py             Nav rail + view stack + status footer (§7.1)
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

- **368 vendored dictionaries** from 23 cases (§12.1 axes: incompressible/compressible, steady/transient, blockMesh/snappyHexMesh, single/multiphase), run in CI on every commit.
- **9,781 dictionaries** in the full v2512 tutorial suite round-trip byte-for-byte locally. This sweep is opt-in — it needs an OpenFOAM install — and is what to run after any lexer change:

  ```sh
  FOAMWB_TUTORIALS=/path/to/tutorials uv run pytest tests/test_foamdict_sweep.py
  ```

One documented limitation and one upstream defect are recorded in `tests/corpus/corpus.json` with reasons, rather than silently excluded.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                      # create the environment
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format

uv run buildfoam             # launch the shell

uv run python tools/check_no_qt.py
uv run python tools/check_branding.py
uv run python tools/check_version_literals.py
uv run python tools/check_translatable.py
```

Qt widget tests render offscreen, so the suite needs no display and works over ssh.

CI runs all of the above on macOS and Windows. Linux is not a desktop target (NG4), but it becomes a CI target at M2 for the golden-case regression (§12.3), which needs a real OpenFOAM install.

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

**NFR-A2 — contrast is checked, not eyeballed.** Both palettes are asserted against the WCAG 2.1 formula in `tests/test_theme.py`, so a well-meant colour tweak cannot push the footer below legibility. Colour is never the sole carrier of meaning: each runtime state has a distinct glyph *shape* and a text label, so the footer reads correctly in greyscale, in a support screenshot, and to a colourblind user.

## Licence

GPL-3.0-or-later (DEC-09). See [`LICENSE`](LICENSE).

OpenFOAM is invoked as a separate process, not linked. Trade-mark rules per §13.3 apply: the name must never take the `OpenFOAM <Something>` form, the mark carries ® on first prominent use, and the non-endorsement notice appears in the setup wizard, the About dialog, this README and the release page.
