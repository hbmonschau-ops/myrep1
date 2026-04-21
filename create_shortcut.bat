@echo off
:: Erstellt eine Desktop-Verknuepfung fuer den Bank Account Manager

set SCRIPT_DIR=%~dp0
set SHORTCUT=%USERPROFILE%\Desktop\Bank Account Manager.lnk
set TARGET=%SCRIPT_DIR%install_and_run.bat

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut('%SHORTCUT%'); " ^
  "$s.TargetPath = '%TARGET%'; " ^
  "$s.WorkingDirectory = '%SCRIPT_DIR%'; " ^
  "$s.Description = 'Bank Account Manager'; " ^
  "$s.Save()"

echo Desktop-Verknuepfung wurde erstellt: %SHORTCUT%
pause
