@echo off
REM Launches the Consultant Console with no visible console window - safe
REM to double-click in front of a client. Run Setup.ps1 once first.
cd /d "%~dp0"
start /B pythonw backend.py
