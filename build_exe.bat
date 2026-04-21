@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo  Bank Account Manager - EXE erstellen
echo ============================================================
echo.

:: --- Python suchen (gleiche Logik wie install_and_run.bat) ---
set PYTHON=

where py >nul 2>&1
if not errorlevel 1 ( set PYTHON=py & goto :found_python )

where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 ( set PYTHON=python & goto :found_python )
)

for %%V in (313 312 311 310 39 38) do (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        "%ProgramFiles%\Python%%V\python.exe"
        "%ProgramFiles(x86)%\Python%%V\python.exe"
        "C:\Python%%V\python.exe"
    ) do (
        if exist %%P ( set PYTHON=%%P & goto :found_python )
    )
)

echo FEHLER: Python nicht gefunden. Bitte zuerst install_and_run.bat ausfuehren.
pause
exit /b 1

:found_python
echo Python gefunden: !PYTHON!
!PYTHON! --version
echo.

:: --- Abhaengigkeiten + PyInstaller ---
echo Installiere Abhaengigkeiten und PyInstaller...
echo.
!PYTHON! -m pip install --upgrade pip
!PYTHON! -m pip install -r "%~dp0requirements.txt"
!PYTHON! -m pip install pyinstaller
if errorlevel 1 (
    echo.
    echo FEHLER: Installation fehlgeschlagen.
    pause
    exit /b 1
)

:: --- EXE bauen ---
echo.
echo Erstelle EXE (kann einige Minuten dauern)...
echo.
!PYTHON! -m PyInstaller "%~dp0bank_manager.spec" --clean
if errorlevel 1 (
    echo.
    echo FEHLER: EXE konnte nicht erstellt werden.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Fertig!
echo  Die EXE liegt unter: %~dp0dist\BankAccountManager.exe
echo ============================================================
echo.
pause
endlocal
