@echo off
rem run: starts the program (SPEC §16). This file only finds a suitable Python;
rem tools\env_setup.py checks the venv, updates yt-dlp, and starts the program.
rem
rem   run.bat                                   opens the window
rem   run.bat "<sheet URL or CSV file>" [--countdown FILE_OR_URL] [--rows 2-10] [--verbose]
rem                                             the terminal version
rem
rem Without arguments (e.g. double-clicked) it starts itself again in a minimized console:
rem the window is what the operator sees, and the console stays reachable from the taskbar
rem if something fails before the window opens. It then stays open, so it can be read.
rem Note: %~dp0 / %~f0 are kept out of ( ) blocks, so a folder name with brackets can't break them.
setlocal
if not "%~1"=="" goto :start
if defined LARB_MINIMIZED goto :start
set "LARB_MINIMIZED=1"
start "LARB - Spicy (console)" /min cmd /c call "%~f0"
exit /b 0
:start
call "%~dp0tools\find_python.bat"
if errorlevel 1 goto :end
"%LARB_PY%" "%~dp0tools\env_setup.py" run %*
:end
set "CODE=%errorlevel%"
rem The minimized console closes by itself after a normal run; after a problem it waits.
if "%~1"=="" if not "%CODE%"=="0" pause
exit /b %CODE%
