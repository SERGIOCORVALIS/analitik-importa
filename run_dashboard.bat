@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem ============================================================
rem  Analitik Importa — дашборд управления
rem  Двойной клик: откроется в браузере http://localhost:8501
rem  Закрыть: закройте это окно или нажмите Ctrl+C
rem ============================================================

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

where python >nul 2>&1
if errorlevel 1 (
  echo [ОШИБКА] Python не найден в PATH. Установите Python 3.11+.
  pause
  exit /b 1
)

if not exist "%VENV_PY%" (
  echo [1/3] Создаю виртуальное окружение .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ОШИБКА] Не удалось создать .venv
    pause
    exit /b 1
  )
) else (
  echo [1/3] .venv найден
)

echo [2/3] Проверяю зависимости ...
"%VENV_PY%" -m pip install -e ".[dev]" -q --disable-pip-version-check
if errorlevel 1 (
  echo [ОШИБКА] Не удалось установить зависимости
  pause
  exit /b 1
)

if not exist "%~dp0.env" if exist "%~dp0.env.example" copy /Y "%~dp0.env.example" "%~dp0.env" >nul

echo [3/3] Запускаю дашборд: http://localhost:8501
echo Чтобы остановить — закройте это окно.
echo.
"%VENV_PY%" -m streamlit run "%~dp0src\analitik_importa\dashboard.py" --server.port 8501 --browser.gatherUsageStats false

pause
endlocal
