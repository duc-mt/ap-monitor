<#
==============================================================================
Script Name:   uninstall-windows.ps1
Description:   Uninstall AP Monitor Scheduled Task and installed files on Windows.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         .\scripts\uninstall-windows.ps1 [-RemoveData]
Notes:         -RemoveData also deletes database and logs.
==============================================================================
#>
param([switch]$RemoveData)
$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $env:LOCALAPPDATA "ap-monitor"
$TaskName = "AP Monitor"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Write-Host "==> Stopping and removing the scheduled task"
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Host "==> Removing installed files"
foreach ($sub in @("backend", "venv", "frontend")) {
  $path = Join-Path $InstallDir $sub
  if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}
if ($RemoveData) {
  Write-Host "==> Removing data and logs"
  if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
} else {
  Write-Host "    Data and logs kept in $InstallDir (re-run with -RemoveData to delete them)."
}
Write-Host "Done."
