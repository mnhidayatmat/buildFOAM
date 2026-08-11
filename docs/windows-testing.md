# Testing on Windows

Everything about the WSL bridge has been written against documentation and
tested as pure logic. Nothing has executed. This is how to change that.

Nothing here needs administrator rights until you choose to provision WSL, and
the verification script never provisions anything by itself.

## 1. Get the code running

Install Python 3.13 and [uv](https://docs.astral.sh/uv/), then:

```powershell
git clone https://github.com/mnhidayatmat/buildFOAM
cd buildFOAM
uv sync --group dev
```

## 2. Run the verification harness

```powershell
uv run python tools\verify_windows.py
```

It changes nothing. It reports:

- whether `wsl.exe` responds and which distributions exist;
- whether **our** path translation agrees with WSL's own `wslpath`, in both
  directions — this is the claim most likely to be wrong, because it has only
  ever been checked against the documentation;
- whether a path containing spaces and non-ASCII characters survives a round
  trip (NFR-C4);
- whether the command bridge keeps its arguments intact, including one that
  looks like a shell substitution;
- whether the existing test suite passes on Windows.

Paste the output back. The failures are the point — a clean run would mean the
harness is not looking hard enough.

## 3. Then, if you want to go further

```powershell
uv run buildfoam                          # the application itself
uv run python tools\verify_windows.py --run   # runs a real solver command
```

## What to expect

The test suite should pass unchanged: it is written to be platform-independent,
and running it here is what proves that rather than assuming it. Line endings
are pinned by `.gitattributes` (`* -text`) because Git for Windows would
otherwise rewrite them and break all 369 corpus hashes.

Path translation is where a real disagreement is most likely. WSL's `wslpath`
is the authority; ours matching it is the thing being tested.

## The parts that still need a person

From §12.4, and no script substitutes for them:

| Scenario | Why it is manual |
|---|---|
| Clean install → wizard → verification run | Needs a machine without WSL |
| Provisioning across a required reboot | The reboot is the test |
| Non-admin user | Needs a managed image or a standard account |
| Adopt a pre-provisioned lab runtime | Needs IT to have provisioned one |
| Keyboard-only pass | Needs someone not touching the mouse |
| Force-quit mid-run leaves no orphans | Needs Task Manager and judgement |
