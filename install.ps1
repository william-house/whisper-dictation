# install.ps1 - Install Whisper Dictation
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step($Message, $Color = 'Yellow') {
    Write-Host $Message -ForegroundColor $Color
}

function Test-PythonVersion($PythonCommand) {
    try {
        $version = & $PythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if (-not $version) { return $false }
        $parts = $version.Trim().Split('.')
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        return ($major -eq 3 -and $minor -ge 9)
    } catch {
        return $false
    }
}

function Resolve-Python {
    $candidates = @()

    if (Get-Command py -ErrorAction SilentlyContinue) {
        $pythons = & py -0p 2>$null
        foreach ($line in $pythons) {
            if ($line -match '3\.(\d+).+?([A-Z]:\\.+python(?:w)?\.exe)') {
                $minor = [int]$matches[1]
                $path = $matches[2]
                if ($minor -ge 9 -and (Test-Path $path)) {
                    $candidates += $path
                }
            }
        }
    }

    foreach ($cmd in @('python', 'python3')) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $candidates += $cmd
        }
    }

    $candidates += @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        'C:\Python312\python.exe',
        'C:\Python313\python.exe',
        'C:\Python314\python.exe'
    )

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (($candidate -in @('python', 'python3') -and (Test-PythonVersion $candidate)) -or
            ((Test-Path $candidate) -and (Test-PythonVersion $candidate))) {
            return $candidate
        }
    }

    return $null
}

function Install-PythonIfMissing {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3.9+ was not found, and winget is not available to install it automatically."
    }

    Write-Step '[1/5] Python 3.9+ not found. Installing Python 3.12 with winget...' 'Yellow'
    & winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw 'Automatic Python install failed.'
    }
}

Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Whisper Dictation - Installer' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''

# --- Locate or install Python ---
$pythonExe = Resolve-Python
if (-not $pythonExe) {
    Install-PythonIfMissing
    $pythonExe = Resolve-Python
}
if (-not $pythonExe) {
    throw 'Python 3.9+ could not be located after installation.'
}
Write-Step "[1/5] Python found: $pythonExe" 'Green'

# --- Create virtual environment ---
$venvDir = Join-Path $scriptDir 'venv'
if (-not (Test-Path $venvDir)) {
    Write-Step '[2/5] Creating virtual environment...'
    & $pythonExe -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to create virtual environment.'
    }
} else {
    Write-Step '[2/5] Virtual environment already exists.' 'Green'
}

# --- Install dependencies ---
$pipExe = Join-Path $venvDir 'Scripts\pip.exe'
Write-Step '[3/5] Installing dependencies...'
$reqFile = Join-Path $scriptDir 'requirements.txt'
& $pythonExe -m pip --version > $null 2>&1
$pythonVenv = Join-Path $venvDir 'Scripts\python.exe'
& $pythonVenv -m pip install --upgrade pip
& $pythonVenv -m pip install -r $reqFile
if ($LASTEXITCODE -ne 0) { throw 'Failed to install dependencies.' }
Write-Step '[3/5] Dependencies installed.' 'Green'

# --- Pre-download the Whisper model ---
Write-Step '[4/5] Pre-downloading Whisper model...'
$downloadScript = Join-Path $scriptDir '_download_model.py'
& $pythonVenv $downloadScript
if ($LASTEXITCODE -ne 0) {
    Write-Step 'WARNING: Model pre-download may have failed. It will download on first launch.'
} else {
    Write-Step '[4/5] Model downloaded.' 'Green'
}

# --- Create Startup shortcut ---
Write-Step '[5/5] Creating Startup shortcut...'
$startupFolder = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'WhisperDictation.lnk'
$vbsPath = Join-Path $scriptDir 'launch.vbs'

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'wscript.exe'
$shortcut.Arguments = "`"$vbsPath`""
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = 'Whisper Dictation (Alt+C / Alt+Z)'
$shortcut.Save()
Write-Step '[5/5] Startup shortcut created.' 'Green'

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Installation complete!' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'The app will auto-start at next login.' -ForegroundColor White
Write-Host 'Press Alt+C to start/stop dictation.' -ForegroundColor White
Write-Host ''
