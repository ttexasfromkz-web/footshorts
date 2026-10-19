@echo off
cd /d "%~dp0"
if exist ".runtime\python.exe" (
 ".runtime\python.exe" bootstrap.py
) else if exist ".venv\Scripts\python.exe" (
 ".venv\Scripts\python.exe" bootstrap.py
) else (
 py -3.11 bootstrap.py
)
if errorlevel 1 pause
