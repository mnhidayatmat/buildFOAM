; NSIS installer (M8, FR-R7, FR-A6).
;
; Produces one self-contained .exe that can be published anywhere — a web
; server, a shared drive, a USB stick. It carries the whole application; it
; downloads nothing at install time and needs no network.
;
; The payload is a PyInstaller onedir build, not onefile. Two reasons, and both
; are requirements rather than preferences:
;
;   * NFR-P8's Qt libraries stay individually replaceable, which is what keeps
;     the LGPL relinking question answerable if Qt's licence ever changes.
;   * A onefile build unpacks itself to a temporary directory on every launch,
;     which on a managed machine with an aggressive antivirus is both slow and
;     the thing most likely to be quarantined.
;
; Silent install (FR-R7) is NSIS's own /S, plus /D to place it. An imaging
; script runs:
;
;     BuildFOAM-Setup.exe /S /D=C:\Program Files\BuildFOAM
;
; /D must be last and unquoted — that is NSIS's rule, not ours, and it is the
; single most common reason a silent install lands somewhere unexpected.

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"

; Supplied by the build script from branding.py, so the product name still
; lives in exactly one place (NFR-M5).
!ifndef APP_NAME
  !define APP_NAME "BuildFOAM"
!endif
!ifndef APP_VERSION
  !define APP_VERSION "0.0.0"
!endif
!ifndef APP_PUBLISHER
  !define APP_PUBLISHER "mnhidayatmat"
!endif
!ifndef PAYLOAD_DIR
  !define PAYLOAD_DIR "..\dist\${APP_NAME}"
!endif

Name "${APP_NAME} ${APP_VERSION}"
OutFile "..\dist\${APP_NAME}-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"

; Per-user by default, so no administrator prompt. The application does not
; need machine-wide privileges, and asking for them on a lab machine is how an
; install becomes impossible for the student who has to run it.
RequestExecutionLevel user
SetCompressor /SOLID lzma

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "FileDescription" "${APP_NAME} — a desktop workbench for OpenFOAM"
VIAddVersionKey "LegalCopyright" "GPL-3.0-or-later"

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_NAME}.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APP_NAME}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Application" SecApp
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD_DIR}\*.*"

  ; Attribution travels with the binary, not only with the repository (§13.5).
  File "..\LICENSE"
  File "..\THIRD-PARTY-NOTICES"

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\${APP_NAME}" "Version" "${APP_VERSION}"

  ; Add/Remove Programs, with an accurate size rather than a guess: a figure
  ; that disagrees with the disk is one the user notices and stops trusting.
  !define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_NAME}.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" "$\"$INSTDIR\Uninstall.exe$\" /S"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_NAME}.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  ; FR-A6: what this removes is the application. It does not touch the user's
  ; cases, their settings, the WSL distribution or OpenFOAM — each of those is
  ; either their work or a separate installation they may share with other
  ; tools. The application's own uninstall flow handles those, with the case
  ; export FR-R12 requires, and it can afford to ask questions an MSI cannot.
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR"

  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
