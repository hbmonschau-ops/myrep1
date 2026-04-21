# Bank Account Manager - Setup und Start
# Aufruf: Rechtsklick -> "Mit PowerShell ausfuehren"
# Oder in PowerShell: Set-ExecutionPolicy -Scope Process Bypass; .\install_and_run.ps1

Set-Location $PSScriptRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Bank Account Manager - Setup und Start" -ForegroundColor Cyan
Write-Host "============================================================"
Write-Host ""

# Python suchen
$python = $null

foreach ($cmd in @("py", "python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) { $python = $cmd; break }
    } catch {}
}

if (-not $python) {
    $searchPaths = @()
    foreach ($v in @("313","312","311","310","39","38")) {
        $searchPaths += "$env:LOCALAPPDATA\Programs\Python\Python$v\python.exe"
        $searchPaths += "$env:ProgramFiles\Python$v\python.exe"
        $searchPaths += "C:\Python$v\python.exe"
    }
    foreach ($p in $searchPaths) {
        if (Test-Path $p) { $python = $p; break }
    }
}

if (-not $python) {
    Write-Host "FEHLER: Python nicht gefunden!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Bitte Python 3.10+ installieren: https://www.python.org/downloads/"
    Write-Host "Option 'Add Python to PATH' aktivieren."
    Read-Host "Druecken Sie Enter zum Beenden"
    exit 1
}

Write-Host "Python gefunden: $python" -ForegroundColor Green
& $python --version
Write-Host ""

Write-Host "Installiere Abhaengigkeiten..." -ForegroundColor Yellow
& $python -m pip install --upgrade pip
& $python -m pip install -r "$PSScriptRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host "FEHLER: Pakete konnten nicht installiert werden." -ForegroundColor Red
    Read-Host "Enter zum Beenden"
    exit 1
}

Write-Host ""
Write-Host "Starte Bank Account Manager..." -ForegroundColor Green
Write-Host ""
& $python "$PSScriptRoot\bank_manager.py"
