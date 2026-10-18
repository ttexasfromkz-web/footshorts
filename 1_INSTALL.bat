@echo off
setlocal
cd /d "%~dp0"
py -3.11 -V >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.11 64-bit from https://www.python.org/downloads/release/python-3119/
  echo Then run this file again.
  pause
  exit /b 1
)
py -3.11 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Installation complete. Run 2_START.bat
pause
exit /b 0
:fail
echo Installation failed. Check the error above and your internet connection.
pause
exit /b 1
