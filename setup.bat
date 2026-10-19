@echo off
rem Первичная установка: виртуальное окружение + зависимости + шаблон secrets.env
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1 && (py -3 -m venv .venv) || (python -m venv .venv)
if not exist .venv\Scripts\python.exe (
  echo Не удалось создать .venv — установи Python 3.10+ с python.org и запусти снова.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if not exist secrets.env copy secrets.env.example secrets.env >nul
echo.
echo Готово. Дальше: впиши почту и пароль приложения в secrets.env,
echo проверь config.yaml и запусти: run_digest.bat --dry-run --force
pause
