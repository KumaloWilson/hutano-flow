@echo off
rem Start the whole Hutano Flow demo stack on Windows (double-click or run from a terminal).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo_up.ps1"
if errorlevel 1 pause
