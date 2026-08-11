# Library

Installing bundled cases, and why an install can be refused.

## Signature invalid

**E-L01.** The catalogue could not be verified, and nothing was installed.

The catalogue carries a cryptographic signature made with a key held by whoever
built this application, and the matching public key is compiled in. A signature
that does not check out means the catalogue is not the one that was published —
it has been altered, truncated, or replaced.

There is no override. A signature you can skip is not a signature, and the whole
point of the check is that it holds on the day it matters.

Reinstalling the application restores a good catalogue.

## Checksum mismatch

**E-L02.** A package did not match the checksum the catalogue gives for it.

The expected checksum comes from *inside* the signed catalogue, so this check is
what that signature protects. A mismatch means the package is not the one the
catalogue describes — most often a truncated download, occasionally something
worse.

Nothing was installed. Try again; if it fails a second time, the copy on disk is
bad rather than the transfer.

## Not data

**E-L04.** A package contains something that is not data, and was refused.

Content is data only in this version: cases, meshes and geometry. A package
containing an executable file, a build recipe, a symbolic link, or a path that
would write outside the destination is refused entirely.

This is not unusual in practice. OpenFOAM tutorials ship executable `Allrun`
scripts, and a few contain `Make` directories for compiled extensions — such a
case cannot be installed as content and must be copied by hand.

## Sideloading

**E-L03.** A package came from somewhere other than the bundled catalogue.

Sideloaded packages are still checked for the rules above, but nothing vouches
for where they came from. Install one only if you trust whoever gave it to you.

## Destination

**E-L05.** A folder of that name already exists where the case would be
installed.

Nothing was overwritten. Rename or move the existing folder — it is your work,
and an installer is not the right thing to be deleting it.
