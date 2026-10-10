@echo off
REM Prompts for your IBM Cloud API key and saves it with Qiskit (~\.qiskit), never inside this project.
cd /d "%~dp0\..\.."
".venv\Scripts\qplay.exe" ibm login --save
pause
