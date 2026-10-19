@echo off
setlocal
cd /d "%~dp0"
if exist ".runtime\python.exe" (
 ".runtime\python.exe" runtime_manager.py --repair
) else (
 py -3.11 runtime_manager.py --repair
)
if errorlevel 1 (
 echo Installation failed. Read .updates\repair.log or use FootballShorts-Setup.exe.
 pause
 exit /b 1
)
echo Installation complete. Run 2_START.bat
pause
