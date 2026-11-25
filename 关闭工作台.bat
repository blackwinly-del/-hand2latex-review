@echo off
rem Stops the Hand2LaTeX workbench started by the launcher entry point.
rem Keep this file ASCII-only: cmd.exe cannot reliably read non-ASCII batch bodies.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Stop
if errorlevel 1 pause
