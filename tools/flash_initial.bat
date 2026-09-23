@echo off
REM One-time wired flash of bootloader + app (Windows).
REM Requires: Python 3.10+ and STM32CubeProgrammer (STM32_Programmer_CLI).
REM Usage: double-click, or run from cmd:  tools\flash_initial.bat [COM5]

setlocal
set HERE=%~dp0
python "%HERE%flash_initial.py" %*
if errorlevel 1 (
    echo.
    echo *** Flashing failed. See the messages above. ***
    pause
    exit /b 1
)
echo.
echo *** Flashing finished. ***
pause
