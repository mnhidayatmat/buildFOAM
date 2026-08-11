# Setting up OpenFOAM

Getting a working OpenFOAM, and what to do when the setup cannot finish.

## First run

**E-R10.** No OpenFOAM has been provisioned yet.

This is the expected state on a new machine and not an error. Setup will install
one. A case can be opened and edited before then; only running needs a runtime.

## Virtualization disabled

**E-R01.** WSL2 needs hardware virtualization, and it is switched off in your
computer's firmware.

This is a BIOS or UEFI setting, not a Windows one. The name varies by
manufacturer: *Intel VT-x*, *AMD-V*, *SVM Mode*, or simply *Virtualization*.
Restart, enter the firmware setup — usually F2, F10 or Delete during startup —
enable it, and save.

Nothing in Windows can enable this for you, which is why setup stops here rather
than failing later with something less clear.

## Administrator rights

**E-R02.** Enabling the Windows features that WSL needs requires an
administrator.

Only that one step does. Importing the distribution and installing OpenFOAM run
as you. On a managed or university machine you may need whoever administers it to
run the first step; afterwards, setup continues without further elevation.

## Reboot required

**E-R03.** Windows will not let a newly enabled feature be used until the machine
restarts.

Setup remembers where it got to and continues afterwards. You will not be asked
for an administrator password a second time, and you can restart whenever suits —
the record is kept for a week.

## Download blocked

**E-R04.** A download could not be reached.

Usually a proxy or a firewall. On a university network, HTTPS to package
repositories is sometimes blocked by default. Check whether a proxy needs
configuring, and whether the network requires you to sign in first.

## Insufficient disk

**E-R05.** There is not enough free space for what setup would install.

A distribution, OpenFOAM and its dependencies need roughly 25 GB, and cases need
more on top. The plan screen states the figure before anything is downloaded.

## Package manager failed

**E-R06.** `apt` or Homebrew reported an error.

The log holds what it said. Common causes are a repository that is temporarily
unavailable, a package index that needs refreshing, and — on macOS — a Homebrew
installation that needs its own update first.

## Broken install

**E-R07.** OpenFOAM was found, but a simple command run inside it failed.

The installation is present and not working. Most often the environment script
cannot be sourced, or the installation was moved after it was installed. Setting
it up again is usually quicker than diagnosing it.

## Intel Mac

**E-R08.** The Homebrew tap this application uses does not support Intel Macs.

The tap builds for Apple silicon only. Docker is the supported path on Intel
hardware; it is slower for small-file work, but it runs the same OpenFOAM.

## Gatekeeper

**E-R09.** macOS blocked a downloaded component.

Gatekeeper quarantines downloads from the internet. Open *System Settings →
Privacy & Security*, find the blocked item, and allow it. Do this only for
components you expect — a Gatekeeper prompt for something you did not download is
worth taking seriously.
