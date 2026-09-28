@echo off
rem setup_once: prepares everything this program needs, inside the .venv folder (SPEC §16).
rem This file only finds a suitable Python; tools\env_setup.py does the rest.
rem Safe to run again: nothing is rebuilt unless something is missing or out of range.
setlocal
call "%~dp0tools\find_python.bat"
if errorlevel 1 goto :end
"%LARB_PY%" "%~dp0tools\env_setup.py" setup
:end
set "CODE=%errorlevel%"
rem Keep the window open when double-clicked, so the result can be read.
pause
exit /b %CODE%
