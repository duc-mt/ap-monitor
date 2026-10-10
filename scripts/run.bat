@echo off
rem Double-click launcher for Windows: runs scripts\run.ps1 without needing to change PowerShell's execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
echo.
pause
