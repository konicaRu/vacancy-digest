@echo off
rem Запуск дайджеста. Параметры передаются дальше: run_digest.bat --dry-run --force
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist logs mkdir logs
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py" %* >> "%~dp0logs\scheduler.log" 2>&1
exit /b %ERRORLEVEL%
