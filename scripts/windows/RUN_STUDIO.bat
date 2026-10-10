@echo off
cd /d "%~dp0\..\.."
if not exist ".venv\Scripts\qplay.exe" (echo Run scripts\windows\INSTALL.bat first. & pause & exit /b 1)
".venv\Scripts\qplay.exe" serve --open
if errorlevel 1 pause
