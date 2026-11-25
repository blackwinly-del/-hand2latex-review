@echo off
rem Hand2LaTeX drawing-board demo (Streamlit) one-click entry point.
rem ASCII-only on purpose: cmd.exe mangles non-ASCII batch bodies.
rem All Chinese text is printed by scripts/launch_demo.ps1 (UTF-8 with BOM).
rem The demo runs in the foreground: closing the window stops it.
rem Extra arguments are passed through, e.g. this file followed by -Port 8502
rem Defaults to GPU when .venv\gpu-venv exists; add -Cpu to force CPU.
rem -Gpu is still accepted and errors if the GPU environment is missing.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_demo.ps1" %*
if errorlevel 1 pause
