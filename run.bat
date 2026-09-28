@echo off
rem run: starts the program (SPEC §16). This file only finds a suitable Python;
rem tools\env_setup.py checks the venv, updates yt-dlp, and starts the program.
rem
rem   run.bat "<sheet URL or CSV file>" [--countdown FILE_OR_URL] [--rows 2-10] [--verbose]
rem
rem Without arguments (e.g. double-clicked) it asks for the sheet URL and keeps the window open.
setlocal
call "%~dp0tools\find_python.bat"
if errorlevel 1 goto :end
"%LARB_PY%" "%~dp0tools\env_setup.py" run %*
:end
set "CODE=%errorlevel%"
if "%~1"=="" pause
exit /b %CODE%
