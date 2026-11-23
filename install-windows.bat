@echo off
rem Double-click to install the UKCEH biomonitoring toolkit on Windows. Nothing else to install first.
echo.
echo UKCEH biomonitoring toolkit: install or update
echo.
echo Which pipelines? Type any of: birds bats images validation all
echo (or just press Enter for uploading and reports only)
set /p PIPES="> "
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %PIPES%
echo.
pause
