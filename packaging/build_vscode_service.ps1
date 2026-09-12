#Requires -Version 5.1
<#
.SYNOPSIS
  Builds the Coach service into vscode-extension\bundled\win32-x64\, ready
  for `vsce package` to include in the .vsix.

.DESCRIPTION
  Same PyInstaller onedir approach as packaging\build.ps1 uses for the
  desktop app, applied to claude_code_coach/service/__main__.py instead -
  the same HTTP service, drain loop, and service.json/token contract, with
  zero PySide6/Qt import anywhere in the chain (that's the whole point of
  this being a separate build from the desktop app: the service alone is
  small, since it never pulls in Qt).

  This is what vscode-extension/src/serviceLauncher.ts spawns when no
  Coach service is already reachable, so an ordinary Marketplace install
  never needs Python - see that file's module docstring.

.NOTES
  Plain ASCII only - see packaging/build.ps1's own note on why (Windows
  PowerShell 5.1 misreads a UTF-8-without-BOM em dash and other multi-byte
  characters, which can corrupt string-literal parsing elsewhere in the
  file).
#>

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$BuildDir = Join-Path $Root "packaging\build"
$IconIco = Join-Path $Root "packaging\assets\icon.ico"
$ServiceDist = Join-Path $BuildDir "coachservice_dist"
$BundledRoot = Join-Path $Root "vscode-extension\bundled\win32-x64"
$BundledDst = Join-Path $BundledRoot "CoachService"

Write-Host "== 1/3  Build dependencies ==" -ForegroundColor Cyan
python -m pip install --quiet --upgrade pyinstaller

if (-not (Test-Path $IconIco)) {
  Write-Host "  $IconIco not found - run packaging\build.ps1 first (it generates the icon)." -ForegroundColor Yellow
  exit 1
}

Write-Host "== 2/3  Build CoachService.exe ==" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean `
  --name CoachService `
  --icon $IconIco `
  --distpath $ServiceDist `
  --workpath (Join-Path $BuildDir "coachservice_work") `
  --specpath $BuildDir `
  (Join-Path $Root "packaging\service_entry.py")

Write-Host "== 3/3  Copy into vscode-extension\bundled\win32-x64\ ==" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $BundledRoot | Out-Null
if (Test-Path $BundledDst) { Remove-Item -Recurse -Force $BundledDst }
Copy-Item -Recurse (Join-Path $ServiceDist "CoachService") $BundledDst

$sizeBytes = (Get-ChildItem -Recurse $BundledDst | Measure-Object -Property Length -Sum).Sum
$sizeMB = [math]::Round($sizeBytes / 1MB, 1)

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Bundled service: $BundledDst"
Write-Host "  Size: $sizeMB MB"
Write-Host ""
Write-Host "Next: cd vscode-extension; npm run compile; npx vsce package"
