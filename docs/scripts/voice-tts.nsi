; Voice TTS installer: the one-folder desktop build, installed for every user
; into Program Files (UAC prompt), with an all-users Start Menu entry, optional
; desktop shortcut and an entry in Settings > Apps that uninstalls it.
;
; Built by `python docs/scripts/tool-build.py --installer`, which passes:
;   /DVERSION=0.5.0              cli.__version__
;   /DSRC=<root>\dist\VoiceTTS   the PyInstaller one-folder build
;   /DICON=<path>.ico            the app icon, drawn by icon.py
;   /DOUT=<root>\dist\VoiceTTS-0.5.0-setup.exe
;
; The app folder is "Voice TTS", not "VoiceTTS": tool-install.py puts a source
; install (its own venv) in %LOCALAPPDATA%\Programs\VoiceTTS, and the two must
; not overwrite each other's files.
;
; This file is UTF-8 without a BOM, so tool-build.py passes /INPUTCHARSET UTF8:
; makensis otherwise reads it in the ANSI code page and mangles the Vietnamese.
;
; 0.6.0 installed per user into %LOCALAPPDATA%\Programs\Voice TTS. This one
; removes that copy first, so Settings > Apps does not list the app twice.

Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!define NAME "Voice TTS"
!define EXE "VoiceTTS.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceTTS"

Name "${NAME}"
OutFile "${OUT}"
InstallDir "$PROGRAMFILES64\${NAME}"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel admin
BrandingText "${NAME} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${NAME}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${NAME} installer"
VIAddVersionKey "LegalCopyright" "dtbao"

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Mở ${NAME}"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Vietnamese"
!insertmacro MUI_LANGUAGE "English"

; The app keeps running in the tray after its window closes, and Windows will
; not replace a running exe. Closing the window only hides it, so stop it hard.
!macro StopApp
  nsExec::Exec 'taskkill /F /T /IM ${EXE}'
  Pop $0
  Sleep 500
!macroend

; Shortcuts for all users, and the 64-bit registry view: the uninstall key must
; land where Settings > Apps reads a 64-bit app from.
!macro MachineScope
  SetShellVarContext all
  SetRegView 64
!macroend

Function .onInit
  !insertmacro MachineScope
FunctionEnd

Function un.onInit
  !insertmacro MachineScope
FunctionEnd

; The 0.6.0 per-user install: run its own uninstaller in place (_?=) so this
; waits for it, then drop what an in-place uninstaller cannot delete - itself.
!macro RemovePerUserInstall
  ReadRegStr $1 HKCU "${UNINST_KEY}" "InstallLocation"
  ${If} $1 != ""
  ${AndIf} $1 != $INSTDIR
  ${AndIf} ${FileExists} "$1\uninstall.exe"
    ExecWait '"$1\uninstall.exe" /S _?=$1'
    Delete "$1\uninstall.exe"
    RMDir "$1"
  ${EndIf}
  DeleteRegKey HKCU "${UNINST_KEY}"
!macroend

Section "${NAME}" SecApp
  SectionIn RO
  !insertmacro StopApp
  !insertmacro RemovePerUserInstall
  ; An update must not keep files the new build dropped: they would shadow it.
  RMDir /r "$INSTDIR\_internal"
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  File "/oname=voice-tts.ico" "${ICON}"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  CreateShortcut "$SMPROGRAMS\${NAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\voice-tts.ico"

  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${NAME}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\voice-tts.ico"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "dtbao"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" $0
SectionEnd

Section "Lối tắt trên Desktop" SecDesktop
  CreateShortcut "$DESKTOP\${NAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\voice-tts.ico"
SectionEnd

Section "Uninstall"
  !insertmacro StopApp
  Delete "$SMPROGRAMS\${NAME}.lnk"
  Delete "$DESKTOP\${NAME}.lnk"
  ; Only what the installer put there. The model lives inside _internal; the
  ; HuggingFace cache and anything the user saved are elsewhere and stay.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\voice-tts.ico"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINST_KEY}"
SectionEnd
