@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo First run 1_INSTALL.bat
 pause
 exit /b 1
)
".venv\Scripts\python.exe" bootstrap.py
if errorlevel 1 pause
