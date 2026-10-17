<#
==============================================================================
Script Name:   run.ps1
Description:   Run AP Monitor straight from a source checkout on Windows.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         .\scripts\run.ps1 [-NoOpen]
Notes:         Sets up virtualenv, builds dashboard if needed, runs API.
==============================================================================
#>
param([switch]$NoOpen)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$HostName = if ($env:AP_MONITOR_HOST) { $env:AP_MONITOR_HOST } else { "127.0.0.1" }
$Port = if ($env:AP_MONITOR_PORT) { $env:AP_MONITOR_PORT } else { "8766" }

# Find a real Python 3.10+. The Microsoft Store "python.exe" stub exits non-zero
# without printing a version, so it fails this probe and is skipped.
function Find-Python {
  foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $extra = @(); if ($candidate.Count -gt 1) { $extra = $candidate[1..($candidate.Count - 1)] }
    & $candidate[0] @extra -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { return , @($candidate) }
  }
  return $null
}

$python = Find-Python
if (-not $python) {
  Write-Error "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')."
}
$pyExe = $python[0][0]
$pyArgs = @(); if ($python[0].Count -gt 1) { $pyArgs = $python[0][1..($python[0].Count - 1)] }

& $pyExe @pyArgs -c "import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Python 3.14+ may lack wheels for the pinned dependencies; if installing fails, use Python 3.12 or 3.13 (py -3.12)."
}

Set-Location (Join-Path $Root "backend")
$venv = ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

# A venv made on another OS (for example one carried over in a zip from a Mac)
# has no Scripts folder and cannot run here - rebuild it.
if ((Test-Path $venv) -and -not (Test-Path $venvPython)) {
  Write-Host "==> The existing .venv was made on another system - recreating it"
  Remove-Item -Recurse -Force $venv
}
if (-not (Test-Path $venvPython)) {
  Write-Host "==> Creating virtual environment"
  & $pyExe @pyArgs -m venv $venv
}

$stamp = Join-Path $venv ".deps-installed"
if (-not (Test-Path $stamp) -or ((Get-Item "requirements.txt").LastWriteTime -gt (Get-Item $stamp).LastWriteTime)) {
  Write-Host "==> Installing dependencies (needs internet the first time)"
  & $venvPython -m pip install -q --upgrade pip
  & $venvPython -m pip install -q -r requirements.txt
  if ($LASTEXITCODE -ne 0) { Write-Error "Installing dependencies failed." }
  New-Item -ItemType File -Force $stamp | Out-Null
}

if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
  if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "==> Building the dashboard"
    Push-Location (Join-Path $Root "frontend")
    npm install --no-audit --no-fund
    npm run build
    Pop-Location
  } else {
    Write-Warning "frontend\dist is missing and npm is not installed: the API will run but there is no dashboard UI. Install Node.js 18+ and re-run, or copy a built frontend\dist here."
  }
}

$url = "http://${HostName}:${Port}"
if (-not $NoOpen) {
  Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", "Start-Sleep 3; Start-Process '$url'"
}

Write-Host "==> AP Monitor running at $url  (Ctrl+C to stop)"
Write-Host "    If WiFi details are blank, open the dashboard: it explains what Windows needs (usually Location services)."
& $venvPython -m uvicorn app.main:app --host $HostName --port $Port
