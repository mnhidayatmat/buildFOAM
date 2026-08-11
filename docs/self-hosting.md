# Publishing the Windows installer yourself

The build produces one self-contained `.exe`. It carries the whole application
and downloads nothing at install time, so it works from a web server, a shared
drive, or a USB stick with no network at all.

## Build it

On the **Windows** machine:

```powershell
uv sync --group dev
uv run python tools\build_installer.py
```

That freezes the application, compiles the installer around it, and writes a
checksum. You get two files in `dist\`:

```
BuildFOAM-Setup-<version>.exe
BuildFOAM-Setup-<version>.exe.sha256
```

The freeze must happen on Windows. PyInstaller bundles the interpreter and
extension modules of the machine it runs on, so a macOS build produces a macOS
application whatever the spec says. NSIS does cross-compile, which is why the
installer *script* can be checked from a developer machine —
`tools\build_installer.py --check-script` compiles it against a stub payload —
while the payload cannot.

## Publish both files

Serve them from the same directory. The checksum is the point of the second
file: a GitHub release page carries its own integrity signals and a file on your
server carries none, so this is what lets someone verify they received what you
published.

```
https://your.server/downloads/BuildFOAM-Setup-1.0.0.exe
https://your.server/downloads/BuildFOAM-Setup-1.0.0.exe.sha256
```

A user verifies with:

```powershell
Get-FileHash BuildFOAM-Setup-1.0.0.exe -Algorithm SHA256
```

Serve over HTTPS. A checksum delivered over the same plain-HTTP connection as
the file it describes protects against a corrupted download and against nothing
else.

## Installing

Normal use is double-clicking it. It installs per-user into
`%LOCALAPPDATA%\Programs\`, so there is **no administrator prompt** — the
application does not need machine-wide privileges, and asking for them is how an
install becomes impossible for the student who has to run it.

For a managed image (FR-R7):

```powershell
BuildFOAM-Setup-1.0.0.exe /S /D=C:\Program Files\BuildFOAM
```

`/D` must come last and must not be quoted. That is NSIS's rule rather than
ours, and it is the usual reason a silent install lands somewhere unexpected.

Pair it with a lab configuration if the runtime is already in the image, so
first launch adopts it instead of trying an install a student account cannot
perform (FR-R8).

## What the uninstaller removes

The application, its shortcut and its registry entries. It does **not** touch
your cases, your settings, the WSL distribution or OpenFOAM — each is either
your work or a separate installation you may share with other tools.

Those are handled by the application's own uninstall flow, which can ask
questions an installer cannot, and which exports cases out of the WSL
distribution before it is unregistered (FR-R12). That matters more than it
sounds: cases live inside the distribution's virtual disk, and
`wsl --unregister` deletes them with it.

## Code signing

The installer is unsigned unless you sign it. Windows SmartScreen will warn on
an unsigned download from an unfamiliar site — "Windows protected your PC" —
until the file builds reputation, and a self-hosted download builds it slowly.

An Authenticode certificate from a commercial CA removes the warning. It is a
separate purchase from Apple's programme and is not required to build or to
install; it changes what a first-time user sees.
