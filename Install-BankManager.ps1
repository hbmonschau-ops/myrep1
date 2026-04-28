#Requires -Version 5.1
<#
.SYNOPSIS
    Installer for Bank Account Manager
.DESCRIPTION
    Downloads and installs the Bank Account Manager Python application,
    including Python 3.12 if not already present, all required packages,
    the application file, and a Desktop shortcut.
#>

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Header banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Bank Account Manager - Installer" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Install directory
# ---------------------------------------------------------------------------
$DefaultInstallDir = "$env:USERPROFILE\Desktop\BankManager"
Write-Host "Standard-Installationsverzeichnis:" -ForegroundColor Yellow
Write-Host "  $DefaultInstallDir" -ForegroundColor White
Write-Host ""
$UserInput = Read-Host "Enter druecken um zu bestaetigen, oder neuen Pfad eingeben"
if ([string]::IsNullOrWhiteSpace($UserInput)) {
    $InstallDir = $DefaultInstallDir
} else {
    $InstallDir = $UserInput.Trim()
}
Write-Host ""
Write-Host "Installationsverzeichnis: $InstallDir" -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# 2. Create install directory
# ---------------------------------------------------------------------------
if (-not (Test-Path $InstallDir)) {
    try {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        Write-Host "Verzeichnis erstellt: $InstallDir" -ForegroundColor Green
    } catch {
        Write-Host "FEHLER: Verzeichnis konnte nicht erstellt werden: $InstallDir" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        Read-Host "Druecke eine Taste zum Beenden..."
        exit 1
    }
} else {
    Write-Host "Verzeichnis existiert bereits: $InstallDir" -ForegroundColor Green
}
Write-Host ""

# ---------------------------------------------------------------------------
# 3. Detect Python 3
# ---------------------------------------------------------------------------
Write-Host "Suche nach Python 3..." -ForegroundColor Yellow

$PythonCmd   = $null   # the launcher/executable name used to run scripts
$PipCmd      = $null   # prefix for pip invocations
$PythonwExe  = $null   # path to pythonw.exe / pyw.exe for the shortcut

function Find-PythonExecutable {
    foreach ($cmd in @("py", "python", "python3")) {
        try {
            $output = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and ($output -match "Python 3")) {
                return $cmd
            }
        } catch {}
    }
    return $null
}

$PythonCmd = Find-PythonExecutable

if ($PythonCmd) {
    $PythonVersion = & $PythonCmd --version 2>&1
    Write-Host "Python gefunden ($PythonCmd): $PythonVersion" -ForegroundColor Green
    Write-Host ""
} else {
    # ---------------------------------------------------------------------------
    # 4. Python not found – offer automatic installation
    # ---------------------------------------------------------------------------
    Write-Host "Python 3 wurde nicht gefunden." -ForegroundColor Red
    Write-Host ""
    $Answer = Read-Host "Soll Python 3.12 automatisch heruntergeladen und installiert werden? (J/N)"
    if ($Answer -notmatch '^[JjYy]') {
        Write-Host ""
        Write-Host "Installation abgebrochen. Bitte Python 3 manuell installieren:" -ForegroundColor Yellow
        Write-Host "  https://www.python.org/downloads/" -ForegroundColor White
        Read-Host "Druecke eine Taste zum Beenden..."
        exit 1
    }

    $PythonInstallerUrl  = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    $PythonInstallerPath = "$env:TEMP\python-3.12.10-amd64.exe"

    Write-Host ""
    Write-Host "Lade Python 3.12.10 herunter..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $PythonInstallerUrl -OutFile $PythonInstallerPath -UseBasicParsing
        Write-Host "Download abgeschlossen." -ForegroundColor Green
    } catch {
        Write-Host "FEHLER beim Herunterladen des Python-Installers:" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        Read-Host "Druecke eine Taste zum Beenden..."
        exit 1
    }

    Write-Host "Installiere Python 3.12.10 (bitte warten)..." -ForegroundColor Yellow
    try {
        $InstallArgs = "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1"
        $proc = Start-Process -FilePath $PythonInstallerPath -ArgumentList $InstallArgs -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            throw "Installer beendet mit Exit-Code $($proc.ExitCode)"
        }
        Write-Host "Python 3.12 erfolgreich installiert." -ForegroundColor Green
    } catch {
        Write-Host "FEHLER bei der Python-Installation:" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        Read-Host "Druecke eine Taste zum Beenden..."
        exit 1
    }

    # Refresh PATH so the new Python is available in this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")

    # Re-detect after installation
    $PythonCmd = Find-PythonExecutable
    if (-not $PythonCmd) {
        Write-Host "FEHLER: Python wurde installiert, konnte aber nicht gefunden werden." -ForegroundColor Red
        Write-Host "Bitte ein neues PowerShell-Fenster oeffnen und das Skript erneut starten." -ForegroundColor Yellow
        Read-Host "Druecke eine Taste zum Beenden..."
        exit 1
    }
    $PythonVersion = & $PythonCmd --version 2>&1
    Write-Host "Python erkannt ($PythonCmd): $PythonVersion" -ForegroundColor Green
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Determine pip invocation and pythonw path
# ---------------------------------------------------------------------------
if ($PythonCmd -eq "py") {
    $PipCmd = "py -m pip"
} else {
    $PipCmd = "$PythonCmd -m pip"
}

# Resolve pythonw.exe / pyw.exe for the shortcut (no console window)
try {
    if ($PythonCmd -eq "py") {
        # py launcher lives alongside pyw.exe in the same folder
        $PyExePath = (Get-Command py -ErrorAction Stop).Source
        $LauncherDir = Split-Path $PyExePath
        $PywCandidate = Join-Path $LauncherDir "pyw.exe"
        if (Test-Path $PywCandidate) {
            $PythonwExe = $PywCandidate
        } else {
            $PythonwExe = $PyExePath   # fallback: use py.exe
        }
    } else {
        $PyExePath = (Get-Command $PythonCmd -ErrorAction Stop).Source
        $PyDir = Split-Path $PyExePath
        $PythonwCandidate = Join-Path $PyDir "pythonw.exe"
        if (Test-Path $PythonwCandidate) {
            $PythonwExe = $PythonwCandidate
        } else {
            $PythonwExe = $PyExePath   # fallback: use python.exe
        }
    }
} catch {
    # Last-resort fallback
    $PythonwExe = "pythonw.exe"
}

# ---------------------------------------------------------------------------
# 5. Install / upgrade pip packages
# ---------------------------------------------------------------------------
Write-Host "Installiere / aktualisiere Python-Pakete..." -ForegroundColor Yellow
Write-Host "  (cryptography, reportlab, pdfplumber, python-docx, openpyxl)" -ForegroundColor White
Write-Host ""
try {
    if ($PythonCmd -eq "py") {
        & py -m pip install --upgrade cryptography reportlab pdfplumber python-docx openpyxl
    } else {
        & $PythonCmd -m pip install --upgrade cryptography reportlab pdfplumber python-docx openpyxl
    }
    if ($LASTEXITCODE -ne 0) { throw "pip beendet mit Exit-Code $LASTEXITCODE" }
    Write-Host ""
    Write-Host "Pakete erfolgreich installiert." -ForegroundColor Green
} catch {
    Write-Host "FEHLER bei der Paketinstallation:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Druecke eine Taste zum Beenden..."
    exit 1
}
Write-Host ""

# ---------------------------------------------------------------------------
# 6. Download bank_manager.pyw
# ---------------------------------------------------------------------------
$AppSourceUrl = "https://raw.githubusercontent.com/hbmonschau-ops/myrep1/claude/bank-account-manager-app-1Me0D/bank_manager.py"
$AppDestPath  = "$InstallDir\bank_manager.pyw"

Write-Host "Lade Bank Account Manager herunter..." -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri $AppSourceUrl -OutFile $AppDestPath -UseBasicParsing
    Write-Host "Anwendung gespeichert: $AppDestPath" -ForegroundColor Green
} catch {
    Write-Host "FEHLER beim Herunterladen der Anwendung:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Druecke eine Taste zum Beenden..."
    exit 1
}
Write-Host ""

# ---------------------------------------------------------------------------
# 7. Create Desktop shortcut "Bank Manager.lnk"
# ---------------------------------------------------------------------------
Write-Host "Erstelle Desktop-Verknuepfung..." -ForegroundColor Yellow
$ShortcutPath = "$env:USERPROFILE\Desktop\Bank Manager.lnk"

try {
    $WScriptShell    = New-Object -ComObject WScript.Shell
    $Shortcut        = $WScriptShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath       = $PythonwExe
    $Shortcut.Arguments        = "`"$AppDestPath`""
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.Description      = "Bank Account Manager"
    $Shortcut.Save()
    Write-Host "Verknuepfung erstellt: $ShortcutPath" -ForegroundColor Green
} catch {
    Write-Host "WARNUNG: Verknuepfung konnte nicht erstellt werden:" -ForegroundColor Yellow
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host "Sie koennen die Anwendung manuell starten:" -ForegroundColor Yellow
    Write-Host "  $PythonwExe `"$AppDestPath`"" -ForegroundColor White
}
Write-Host ""

# ---------------------------------------------------------------------------
# 8. Success message
# ---------------------------------------------------------------------------
Write-Host "============================================================" -ForegroundColor Green
Write-Host "   Installation erfolgreich abgeschlossen!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Installationsverzeichnis : $InstallDir" -ForegroundColor White
Write-Host "Anwendungsdatei          : $AppDestPath" -ForegroundColor White
Write-Host "Desktop-Verknuepfung     : $ShortcutPath" -ForegroundColor White
Write-Host ""
Write-Host "So starten Sie den Bank Account Manager:" -ForegroundColor Cyan
Write-Host "  * Doppelklick auf 'Bank Manager' auf dem Desktop" -ForegroundColor White
Write-Host "  * Oder in PowerShell:" -ForegroundColor White
Write-Host "    & `"$PythonwExe`" `"$AppDestPath`"" -ForegroundColor White
Write-Host ""

# ---------------------------------------------------------------------------
# Pause so the window stays open when double-clicked
# ---------------------------------------------------------------------------
Write-Host "Druecke eine Taste zum Beenden..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
