<#
==============================================================================
Script Name:   install-windows.ps1
Description:   Install AP Monitor for current Windows user & Scheduled Task.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         .\scripts\install-windows.ps1 [-Start]
Notes:         Installs to %LOCALAPPDATA%\ap-monitor. No admin required.
==============================================================================
#>
param([switch]$Start)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$InstallDir = Join-Path $env:LOCALAPPDATA "ap-monitor"
$BackendDir = Join-Path $InstallDir "backend"
$VenvDir = Join-Path $InstallDir "venv"
$TaskName = "AP Monitor"

function Find-Python {
  foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $extra = @(); if ($candidate.Count -gt 1) { $extra = $candidate[1..($candidate.Count - 1)] }
    & $candidate[0] @extra -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { return , @($candidate) }
  }
  return $null
}

Write-Host "==> Checking for Python 3.10+"
$python = Find-Python
if (-not $python) { Write-Error "Python 3.10 or newer is required (https://www.python.org/downloads/)." }
$pyExe = $python[0][0]
$pyArgs = @(); if ($python[0].Count -gt 1) { $pyArgs = $python[0][1..($python[0].Count - 1)] }

Write-Host "==> Copying files to $InstallDir"
New-Item -ItemType Directory -Force $BackendDir | Out-Null
if (Test-Path (Join-Path $BackendDir "app")) { Remove-Item -Recurse -Force (Join-Path $BackendDir "app") }
Copy-Item -Recurse -Force (Join-Path $Root "backend\app") $BackendDir
Copy-Item -Force (Join-Path $Root "backend\requirements.txt") $BackendDir
Get-ChildItem -Recurse -Directory -Filter "__pycache__" $BackendDir | Remove-Item -Recurse -Force

$dist = Join-Path $Root "frontend\dist"
if (Test-Path $dist) {
  $target = Join-Path $InstallDir "frontend\dist"
  if (Test-Path $target) { Remove-Item -Recurse -Force $target }
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item -Recurse -Force $dist $target
} else {
  Write-Warning "frontend\dist not found - run 'npm run build' in frontend\ first if you want the dashboard UI."
}

Write-Host "==> Creating virtual environment and installing dependencies (needs internet)"
if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) { & $pyExe @pyArgs -m venv $VenvDir }
$venvPython = Join-Path $VenvDir "Scripts\python.exe"
& $venvPython -m pip install -q --upgrade pip
& $venvPython -m pip install -q -r (Join-Path $BackendDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Error "Installing dependencies failed." }
& $venvPython -m pip install -q (Join-Path $Root "cli")

Write-Host "==> Registering the '$TaskName' scheduled task (runs at logon, no console window)"
$pythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m app.serve" -WorkingDirectory $BackendDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

if ($Start) {
  Write-Host "==> Starting now"
  Start-ScheduledTask -TaskName $TaskName
}

Write-Host ""
Write-Host "Installed. AP Monitor starts at every logon and serves http://127.0.0.1:8766"
if (-not $Start) { Write-Host "  Start it now:  Start-ScheduledTask -TaskName '$TaskName'" }
Write-Host "  Log file:      $env:LOCALAPPDATA\ap-monitor\logs\ap-monitor.log"
Write-Host "  CLI:           $VenvDir\Scripts\ap-monitor.exe status"
Write-Host "  If WiFi details are blank, the dashboard explains what Windows needs (usually Location services)."
