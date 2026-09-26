@echo off
rem Double-click to process "This PC" jobs on the CPU. Close the window to stop.
title Lang-Bridge local worker
cd /d "%~dp0"
python scripts\local_worker.py
pause
