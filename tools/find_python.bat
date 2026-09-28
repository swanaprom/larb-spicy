@echo off
rem Finds a Python in the supported range (python-range.txt) and sets LARB_PY to its full path.
rem None found: offers to install the newest version in the range with winget (only after a
rem yes), or points to python.org. Exit code 0 = found, 1 = not found (the caller stops).
rem Called by setup_once.bat and run.bat. Everything after this is tools\env_setup.py (SPEC §16).
rem
rem For testing, the environment variable LARB_PYTHON_RANGE (e.g. 3.9-3.9) overrides the file.
rem Note: %~dp0 is kept out of ( ) blocks, so a folder name with brackets can't break them.

setlocal
set "RANGE=%LARB_PYTHON_RANGE%"
set "RANGE_FILE=%~dp0..\python-range.txt"
if not defined RANGE set /p RANGE=<"%RANGE_FILE%"
set "MAJOR=" & set "LOW=" & set "HIGH="
for /f "tokens=1-4 delims=.- " %%a in ("%RANGE%") do (
    set "MAJOR=%%a"
    set "LOW=%%b"
    set "HIGH=%%d"
)
if not defined HIGH (
    echo python-range.txt should contain a range like 3.11-3.13, not "%RANGE%".
    exit /b 1
)

rem 1. The py launcher (installed with Python from python.org or winget), newest first.
set "FOUND="
for /l %%m in (%HIGH%,-1,%LOW%) do if not defined FOUND (
    for /f "delims=" %%p in ('py -%MAJOR%.%%m -c "import sys; print(sys.executable)" 2^>nul') do set "FOUND=%%p"
)

rem 2. "python" on PATH, if it's in the range and not a venv (the venv may get rebuilt, which
rem    Windows refuses while its own Python is running). If "python" is only the Microsoft
rem    Store placeholder, it prints nothing here and is skipped.
set "CHECK=import sys; v = sys.version_info[:2]; ok = (%MAJOR%, %LOW%) <= v <= (%MAJOR%, %HIGH%) and sys.prefix == sys.base_prefix; print(sys.executable if ok else '')"
if not defined FOUND (
    for /f "delims=" %%p in ('python -c "%CHECK%" 2^>nul') do set "FOUND=%%p"
)

if defined FOUND (
    endlocal & set "LARB_PY=%FOUND%"
    exit /b 0
)

rem 3. None: offer the newest version in the range.
set "WANT=%MAJOR%.%HIGH%"
echo.
echo No Python %MAJOR%.%LOW% to %MAJOR%.%HIGH% was found on this computer.
echo This program needs Python %WANT%. It installs alongside any other Python you have,
echo so nothing needs to be uninstalled.
where winget >nul 2>nul
if errorlevel 1 goto :python_org
set "ANSWER="
set /p "ANSWER=Install Python %WANT% now with winget? [y/N] "
if /i "%ANSWER%"=="y" goto :winget
if /i "%ANSWER%"=="yes" goto :winget
goto :python_org

:winget
winget install --id Python.Python.%WANT% -e
rem Not "if errorlevel 1": winget's error codes are negative numbers (e.g. 0x8A150014).
if not "%errorlevel%"=="0" (
    echo winget couldn't install it.
    goto :python_org
)
echo.
echo Python %WANT% is installed. Close this window, open a new terminal, and run setup_once again.
exit /b 1

:python_org
echo.
echo Get Python %WANT% for Windows from https://www.python.org/downloads/
echo and run the installer (tick "Add python.exe to PATH"; the other defaults are fine).
echo Then open a new terminal and run setup_once again.
exit /b 1
