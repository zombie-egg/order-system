@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\demo.ps1"
set "DEMO_EXIT=%ERRORLEVEL%"
if not "%DEMO_EXIT%"=="0" (
  echo.
  echo Demo startup failed. Review the message above.
  if /I not "%CODEX_NONINTERACTIVE%"=="1" pause
)
endlocal & exit /b %DEMO_EXIT%
