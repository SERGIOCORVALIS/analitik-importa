@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================
rem  Analitik Importa — полный автозапуск анализа ниши
rem  Двойной клик или: run_analyze.bat [ниша] [wb-path] [ozon-path] [cost-cny] [sell-rub] [mp]
rem ============================================================

cd /d "%~dp0"

rem --- Параметры по умолчанию (можно менять здесь) ---
set "KEYWORDS=powerbank"
set "WB_PATH=Электроника/Powerbanks"
set "OZON_PATH=Электроника/Powerbanks"
set "COST_CNY=25"
set "SELL_RUB=2990"
set "MP=wb"

if not "%~1"=="" set "KEYWORDS=%~1"
if not "%~2"=="" set "WB_PATH=%~2"
if not "%~3"=="" set "OZON_PATH=%~3"
if not "%~4"=="" set "COST_CNY=%~4"
if not "%~5"=="" set "SELL_RUB=%~5"
if not "%~6"=="" set "MP=%~6"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "VENV_PIP=%~dp0.venv\Scripts\pip.exe"
set "ANALITIK=%~dp0.venv\Scripts\analitik.exe"
set "REPORTS=%~dp0reports"

echo.
echo ========================================
echo  ANALITIK IMPORTA — автозапуск
echo ========================================
echo  Ниша:        %KEYWORDS%
echo  WB path:     %WB_PATH%
echo  Ozon path:   %OZON_PATH%
echo  Закупка CNY: %COST_CNY%
echo  Цена RUB:    %SELL_RUB%
echo  Площадка:    %MP%
echo ========================================
echo.

rem --- Python ---
where python >nul 2>&1
if errorlevel 1 (
  echo [ОШИБКА] Python не найден в PATH. Установите Python 3.11+.
  pause
  exit /b 1
)

rem --- venv ---
if not exist "%VENV_PY%" (
  echo [1/5] Создаю виртуальное окружение .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ОШИБКА] Не удалось создать .venv
    pause
    exit /b 1
  )
) else (
  echo [1/5] .venv найден
)

rem --- зависимости ---
echo [2/5] Проверяю / устанавливаю пакет ...
"%VENV_PIP%" install -e ".[dev]" -q
if errorlevel 1 (
  echo [ОШИБКА] pip install не удался
  pause
  exit /b 1
)

rem --- .env ---
if not exist "%~dp0.env" (
  if exist "%~dp0.env.example" (
    echo [3/5] Копирую .env.example -^> .env
    copy /Y "%~dp0.env.example" "%~dp0.env" >nul
  ) else (
    echo [ОШИБКА] Нет .env и .env.example
    pause
    exit /b 1
  )
) else (
  echo [3/5] .env найден
)

if not exist "%REPORTS%" mkdir "%REPORTS%"

rem --- анализ ---
echo [4/5] Запускаю analyze ...
echo.

"%ANALITIK%" analyze "%KEYWORDS%" --wb-path "%WB_PATH%" --ozon-path "%OZON_PATH%" --cost-cny %COST_CNY% --sell-rub %SELL_RUB% --mp %MP%
if errorlevel 1 (
  echo.
  echo [ОШИБКА] analyze завершился с ошибкой
  pause
  exit /b 1
)

rem --- открыть самый свежий HTML-отчёт ---
echo.
echo [5/5] Открываю цветной отчёт ...

set "LATEST="
for /f "delims=" %%F in ('dir /b /a-d /o-d "%REPORTS%\*.html" 2^>nul') do (
  set "LATEST=%%F"
  goto :found
)

:found
if not defined LATEST (
  echo [ПРЕДУПРЕЖДЕНИЕ] HTML-отчёт не найден в reports\
  pause
  exit /b 0
)

set "REPORT_PATH=%REPORTS%\!LATEST!"
echo Отчёт: !REPORT_PATH!
start "" "!REPORT_PATH!"

echo.
echo Готово.
echo XML:   reports\!LATEST:.html=.xml!
echo Данные: reports\!LATEST:.html=.data.xml!
echo.
pause
endlocal
exit /b 0
