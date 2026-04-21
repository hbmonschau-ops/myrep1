@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo  Bank Account Manager - Setup und Start
echo ============================================================
echo.

:: --- Python suchen ---
set PYTHON=

:: 1) py-Launcher (zuverlaessigste Methode auf Windows)
where py >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py
    goto :found_python
)

:: 2) python im PATH
where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON=python
        goto :found_python
    )
)

:: 3) Bekannte Installationspfade (User + System)
for %%V in (313 312 311 310 39 38) do (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        "%ProgramFiles%\Python%%V\python.exe"
        "%ProgramFiles(x86)%\Python%%V\python.exe"
        "C:\Python%%V\python.exe"
    ) do (
        if exist %%P (
            set PYTHON=%%P
            goto :found_python
        )
    )
)

:: Nicht gefunden
echo FEHLER: Python wurde nicht gefunden!
echo.
echo Bitte Python 3.10 oder neuer installieren:
echo   https://www.python.org/downloads/
echo.
echo Beim Installieren diese Optionen aktivieren:
echo   [x] Add Python to PATH
echo   [x] Install for all users  (bei Admin-Ausfuehrung wichtig)
echo.
pause
exit /b 1

:found_python
echo Python gefunden: !PYTHON!
!PYTHON! --version
echo.

:: --- Abhaengigkeiten installieren ---
echo Installiere Abhaengigkeiten...
echo.
!PYTHON! -m pip install --upgrade pip
!PYTHON! -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo FEHLER: Pakete konnten nicht installiert werden.
    echo Bitte Internetverbindung pruefen.
    echo.
    pause
    exit /b 1
)

:: --- App starten ---
echo.
echo ============================================================
echo  Starte Bank Account Manager...
echo ============================================================
echo.
!PYTHON! "%~dp0bank_manager.py"
set APP_EXIT=%errorlevel%

echo.
if !APP_EXIT! neq 0 (
    echo FEHLER: Anwendung beendet mit Code !APP_EXIT!
) else (
    echo Anwendung normal beendet.
)
echo.
pause
endlocal
