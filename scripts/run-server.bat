@echo off
rem ==============================================================================
rem Script Name:   run.bat
rem Description:   Windows double-click launcher for AP Monitor PowerShell runner.
rem Author:        Mai Tan Duc <ducmai.network@gmail.com>
rem Created:       2026-10-10
rem Version:       1.0.0
rem License:       MIT
rem ==============================================================================
rem Usage:         scripts\run.bat
rem Notes:         Bypasses ExecutionPolicy to execute scripts\run.ps1
rem ==============================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-server.ps1" %*
echo.
pause
