@echo off
rem Hand2LaTeX drawing-board demo (Streamlit) one-click entry point.
rem ASCII-only on purpose: cmd.exe mangles non-ASCII batch bodies.
rem All Chinese text is printed by scripts/launch_demo.ps1 (UTF-8 with BOM).
rem The demo runs in the foreground: closing the window stops it.
rem Extra arguments are passed through, e.g. this file followed by -Port 8502
rem GPU mode: this file followed by -Gpu (needs .venv\gpu-venv, see README 6.4)
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_demo.ps1" %*
if errorlevel 1 pause
