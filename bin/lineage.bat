@echo off
rem lineage CLI wrapper for Windows.
rem Locates a Python 3.11+ interpreter and runs `python -m lineage %*`.

setlocal

set "SCRIPT_DIR=%~dp0"

rem Prefer the `py` launcher, then fall back to `python`.
set "PYEXE="
where py >nul 2>&1
if %ERRORLEVEL% == 0 (
    for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)"') do (
        set "PYEXE=%%P"
    )
)
if not defined PYEXE (
    where python >nul 2>&1
    if %ERRORLEVEL% == 0 (
        set "PYEXE=python"
    )
)
if not defined PYEXE (
    echo lineage: error: could not find Python on PATH 1>&2
    echo lineage: hint: install Python 3.11+ from python.org and re-run 1>&2
    exit /b 127
)

"%PYEXE%" -m lineage %*
exit /b %ERRORLEVEL%
