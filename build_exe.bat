@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Bank Account Manager - EXE erstellen
echo ============================================================
echo.

:: Python pruefen
python --version
if errorlevel 1 (
    echo.
    echo FEHLER: Python nicht gefunden. Bitte zuerst install_and_run.bat ausfuehren.
    pause
    exit /b 1
)

:: Abhaengigkeiten + PyInstaller installieren
echo.
echo Installiere Abhaengigkeiten und PyInstaller...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
if errorlevel 1 (
    echo.
    echo FEHLER: Installation fehlgeschlagen.
    pause
    exit /b 1
)

:: EXE bauen
echo.
echo Erstelle EXE (kann einige Minuten dauern)...
echo.
python -m PyInstaller bank_manager.spec --clean
if errorlevel 1 (
    echo.
    echo FEHLER: EXE konnte nicht erstellt werden.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Fertig! Die EXE liegt unter:
echo  %~dp0dist\BankAccountManager.exe
echo ============================================================
echo.
pause
endlocal
