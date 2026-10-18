@echo off
cd /d "%~dp0"
if exist "%~dp0dist\HearthstoneBGA\HearthstoneBGA.exe" (
  start "" "%~dp0dist\HearthstoneBGA\HearthstoneBGA.exe"
) else (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0run.py"
)
