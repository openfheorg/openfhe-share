@echo off
setlocal ENABLEDELAYEDEXPANSION

REM Change to the directory of this script
cd /d "%~dp0"

REM Allow override via environment variable
if not "%PYTHON_BIN%"=="" goto run_py

REM Try "py" first
where py >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    set "PYTHON_BIN=py"
    goto run_py
)

REM Fallback to "python"
where python >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    set "PYTHON_BIN=python"
    goto run_py
)

echo.
echo [ERROR] Could not find Python. Ensure it is installed and on PATH,
echo         or set PYTHON_BIN before running this script.
echo.
pause
exit /b 1

:run_py
"%PYTHON_BIN%" main.py ui %*
set "EXITCODE=%ERRORLEVEL%"

echo.
pause
endlocal & exit /b %EXITCODE%
