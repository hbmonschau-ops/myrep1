@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Bank Account Manager - Setup und Start
echo ============================================================
echo.

:: Python pruefen
python --version
if errorlevel 1 (
    echo.
    echo FEHLER: Python wurde nicht gefunden!
    echo Bitte installieren Sie Python 3.10 oder neuer:
    echo   https://www.python.org/downloads/
    echo.
    echo Wichtig: Beim Installieren "Add Python to PATH" aktivieren!
    echo.
    pause
    exit /b 1
)

echo.
echo Installiere / aktualisiere Abhaengigkeiten...
echo.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo FEHLER: Pakete konnten nicht installiert werden.
    echo Bitte pruefen Sie Ihre Internetverbindung.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Starte Bank Account Manager...
echo ============================================================
echo.
python bank_manager.py

if errorlevel 1 (
    echo.
    echo Die Anwendung wurde mit einem Fehler beendet.
    pause
)
endlocal
