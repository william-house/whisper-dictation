# install.ps1 - Install Whisper Dictation
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Whisper Dictation - Installer' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''

# --- Locate Python ---
$pythonExe = 'C:\Users\XTi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $pythonExe)) {
    Write-Host 'ERROR: Python not found' -ForegroundColor Red
    exit 1
}
Write-Host '[1/5] Python found.' -ForegroundColor Green

# --- Create virtual environment ---
$venvDir = Join-Path $scriptDir 'venv'
if (-not (Test-Path $venvDir)) {
    Write-Host '[2/5] Creating virtual environment...' -ForegroundColor Yellow
    & $pythonExe -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'ERROR: Failed to create virtual environment' -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host '[2/5] Virtual environment already exists.' -ForegroundColor Green
}

# --- Install dependencies ---
$pipExe = Join-Path $venvDir 'Scripts\pip.exe'
Write-Host '[3/5] Installing dependencies...' -ForegroundColor Yellow
& $pipExe install --upgrade pip
$reqFile = Join-Path $scriptDir 'requirements.txt'
& $pipExe install -r $reqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host 'ERROR: Failed to install dependencies' -ForegroundColor Red
    exit 1
}
Write-Host '[3/5] Dependencies installed.' -ForegroundColor Green

# --- Pre-download the Whisper model ---
$pythonVenv = Join-Path $venvDir 'Scripts\python.exe'
Write-Host '[4/5] Pre-downloading Whisper model...' -ForegroundColor Yellow
$downloadScript = Join-Path $scriptDir '_download_model.py'
& $pythonVenv $downloadScript
if ($LASTEXITCODE -ne 0) {
    Write-Host 'WARNING: Model pre-download may have failed. It will download on first launch.' -ForegroundColor Yellow
} else {
    Write-Host '[4/5] Model downloaded.' -ForegroundColor Green
}

# --- Create Startup shortcut ---
Write-Host '[5/5] Creating Startup shortcut...' -ForegroundColor Yellow
$startupFolder = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'WhisperDictation.lnk'
$vbsPath = Join-Path $scriptDir 'launch.vbs'

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'wscript.exe'
$shortcut.Arguments = "`"$vbsPath`""
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = 'Whisper Dictation - Alt+C'
$shortcut.Save()
Write-Host '[5/5] Startup shortcut created.' -ForegroundColor Green

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Installation complete!' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'The app will auto-start at next login.' -ForegroundColor White
Write-Host 'Press Alt+C to start/stop dictation.' -ForegroundColor White
Write-Host ''
