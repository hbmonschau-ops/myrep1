@echo off
setlocal

echo ============================================================
echo  Bank Account Manager - Setup und Start
echo ============================================================
echo.

:: Python pruefen
python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python wurde nicht gefunden.
    echo Bitte installieren Sie Python 3.10 oder neuer von https://www.python.org
    echo Aktivieren Sie dabei "Add Python to PATH".
    pause
    exit /b 1
)

:: Abhaengigkeiten installieren
echo Installiere Abhaengigkeiten...
python -m pip install --upgrade pip --quiet
python -m pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo FEHLER: Abhaengigkeiten konnten nicht installiert werden.
    pause
    exit /b 1
)

echo.
echo Starte Bank Account Manager...
python "%~dp0bank_manager.py"

endlocal
