@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo First run 1_INSTALL.bat
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]" "deno>=2.3,<3"
if errorlevel 1 (
 echo Update failed. Check the error above.
) else (
 echo YouTube downloader updated. Restart the app.
)
pause
