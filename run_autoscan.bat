@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem ============================================================
rem  Analitik Importa — автопоиск лучших товаров на сегодня
rem  Без API-ключей: Яндекс Маркет + Amazon (публичный поиск).
rem  Двойной клик: соберёт данные (~3 мин) и откроет цветной отчёт.
rem ============================================================

cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"

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

echo [3/3] Сканирую ниши ...
"%VENV_PY%" -m analitik_importa.cli scan --open
if errorlevel 1 (
  echo [ОШИБКА] Скан завершился с ошибкой
  pause
  exit /b 1
)

echo.
echo Готово. Отчёт открыт в браузере, файлы — в папке reports\scans
timeout /t 15
endlocal
