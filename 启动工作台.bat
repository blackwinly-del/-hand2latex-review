@echo off
rem Hand2LaTeX one-click entry point.
rem All user-facing text lives in scripts/launch.ps1 so this file stays ASCII-only:
rem cmd.exe cannot reliably read non-ASCII batch bodies, but PowerShell can.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Menu
if errorlevel 1 pause
