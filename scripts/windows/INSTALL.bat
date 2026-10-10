@echo off
REM Quantum Playground Studio v9 - one-time setup (creates .venv in the project folder)
cd /d "%~dp0\..\.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv || (echo Python 3.10+ not found. Install it from python.org with "Add to PATH". & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e ".[all]" || (echo Installation failed. & pause & exit /b 1)
echo.
echo Installed. Start the studio with scripts\windows\RUN_STUDIO.bat
pause
