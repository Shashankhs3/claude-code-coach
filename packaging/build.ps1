#Requires -Version 5.1
<#
.SYNOPSIS
  Builds a distributable Windows package for Claude Code Coach.

.DESCRIPTION
  Produces dist\ClaudeCodeCoach\ (onedir - a real folder of files, not a
  single-file exe) plus a zip ready to attach to a GitHub Release.

  Two separate PyInstaller builds happen here, not one:

    1. hook_receiver.exe - a small standalone build of
       claude_code_coach/runtime/hook_receiver.py, the script Claude Code's
       hooks actually invoke.
    2. ClaudeCodeCoach.exe - the main PySide6 GUI app.

  Why two: claude_code_coach/runtime/hook_installer.py writes a hook command
  into the user's real Claude Code settings.json. Running from source, that
  command is `sys.executable` + this repo's hook_receiver.py - which breaks
  under a single frozen exe two different ways: sys.executable there would
  be this app's own GUI exe (not a Python interpreter you can hand a script
  to), and the script's own path resolves inside a temp extraction dir
  PyInstaller deletes the moment the process exits - fatal for a hook
  invoked long after the app has closed. Shipping the receiver as its own
  small, persistent executable next to the main app (see
  hook_installer.py's `hook_command()`) avoids both problems. See that
  module's docstring for the full reasoning.

.NOTES
  Run from anywhere; paths are resolved relative to the repo root. Requires
  Python on PATH with this project's requirements installed (PySide6) -
  pyinstaller and Pillow are installed automatically if missing.

  Plain ASCII only in this file, deliberately: Windows PowerShell 5.1
  (powershell.exe, as opposed to pwsh) does not reliably auto-detect a
  UTF-8-without-BOM script file, and misreads multi-byte characters (an
  em dash, a curly quote) as separate Windows-1252 bytes - which can, and
  did during development, corrupt string-literal parsing elsewhere in the
  file with an error that points nowhere near the real cause. Since this
  script is meant to just work when someone runs it, ASCII is the safer
  choice here even though the rest of this project's prose uses em dashes
  freely.
#>

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Version = "0.3.0"
$DistName = "ClaudeCodeCoach"
$BuildDir = Join-Path $Root "packaging\build"
$AssetsDir = Join-Path $Root "packaging\assets"
$IconIco = Join-Path $AssetsDir "icon.ico"
$IconPng = Join-Path $Root "vscode-extension\icon.png"
$VersionFile = Join-Path $Root "packaging\version_info.txt"
$DistPath = Join-Path $Root "dist"
$AppDir = Join-Path $DistPath $DistName

Write-Host "== 1/6  Build dependencies ==" -ForegroundColor Cyan
python -m pip install --quiet --upgrade pyinstaller pillow

Write-Host "== 2/6  Icon (same artwork as the VS Code extension) ==" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $AssetsDir | Out-Null
if (-not (Test-Path $IconIco)) {
  $iconScript = "from PIL import Image`n" +
    "src = Image.open(r'$IconPng').convert('RGBA')`n" +
    "sizes = [16, 24, 32, 48, 64, 128, 256]`n" +
    "src.save(r'$IconIco', sizes=[(s, s) for s in sizes])`n"
  python -c $iconScript
  Write-Host "  wrote $IconIco"
} else {
  Write-Host "  $IconIco already exists - skipping conversion"
}

Write-Host "== 3/6  Build hook_receiver.exe (companion) ==" -ForegroundColor Cyan
$ReceiverDist = Join-Path $BuildDir "receiver_dist"
python -m PyInstaller --noconfirm --clean `
  --name hook_receiver `
  --distpath $ReceiverDist `
  --workpath (Join-Path $BuildDir "receiver_work") `
  --specpath $BuildDir `
  (Join-Path $Root "packaging\hook_receiver_entry.py")

Write-Host "== 4/6  Build ClaudeCodeCoach.exe (main app) ==" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean `
  --name $DistName `
  --windowed `
  --icon $IconIco `
  --version-file $VersionFile `
  --distpath $DistPath `
  --workpath (Join-Path $BuildDir "app_work") `
  --specpath $BuildDir `
  (Join-Path $Root "main.py")

Write-Host "== 5/6  Merge the receiver into the app folder ==" -ForegroundColor Cyan
$ReceiverDst = Join-Path $AppDir "hook_receiver"
if (Test-Path $ReceiverDst) { Remove-Item -Recurse -Force $ReceiverDst }
Copy-Item -Recurse (Join-Path $ReceiverDist "hook_receiver") $ReceiverDst
Copy-Item (Join-Path $Root "README.md") $AppDir
$LicensePath = Join-Path $Root "LICENSE"
if (Test-Path $LicensePath) { Copy-Item $LicensePath $AppDir }

Write-Host "== 6/6  Zip for distribution ==" -ForegroundColor Cyan
$ZipPath = Join-Path $DistPath "$DistName-v$Version-win64.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
Compress-Archive -Path $AppDir -DestinationPath $ZipPath

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  App:  $AppDir\$DistName.exe"
Write-Host "  Zip:  $ZipPath"
