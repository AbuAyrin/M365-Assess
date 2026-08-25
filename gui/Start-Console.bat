@echo off
REM Launches the Consultant Console with no visible console window - safe
REM to double-click in front of a client. Run Setup.ps1 once first.
cd /d "%~dp0"

REM Close a leftover console from last time, if one is still running.
REM (start /B does not stop when you close the browser tab or this window -
REM without this, "the same old copy" can keep answering on the same port
REM even after you have updated the files, which looks exactly like the
REM update did nothing.)
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5050 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

start /B pythonw backend.py
