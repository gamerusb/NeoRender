Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Test-PythonVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Version
    )

    & py "-$Version" -c "import sys; print(sys.version)" *> $null
    return $LASTEXITCODE -eq 0
}

function Get-PythonVersion {
    $preferred = @("3.10", "3.11", "3.12")
    foreach ($version in $preferred) {
        if (Test-PythonVersion -Version $version) {
            return $version
        }
    }
    return $null
}

$selected = Get-PythonVersion
if (-not $selected) {
    Write-Host ""
    Write-Host "Python 3.10/3.11/3.12 not found." -ForegroundColor Red
    Write-Host "Install Python and retry:" -ForegroundColor Yellow
    Write-Host "  winget install Python.Python.3.10"
    Write-Host ""
    exit 1
}

Write-Host "Using Python $selected via py launcher" -ForegroundColor Cyan

$venvPath = Join-Path $ProjectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Cyan
    & py "-$selected" -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$requirementsPath = Join-Path $ProjectRoot "requirements.txt"
& $venvPython -m pip install -r $requirementsPath
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Full dependency install failed." -ForegroundColor Yellow
    Write-Host "Retrying without faster-whisper (Windows fallback)..." -ForegroundColor Yellow

    $fallbackPath = Join-Path $ProjectRoot "requirements.windows.fallback.txt"
    Get-Content -LiteralPath $requirementsPath |
        Where-Object { $_ -notmatch '^\s*faster-whisper\s*==' } |
        Set-Content -LiteralPath $fallbackPath

    & $venvPython -m pip install -r $fallbackPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Dependency installation failed." -ForegroundColor Red
        Write-Host "Tip: install Microsoft C++ Build Tools or use a machine where wheels are available." -ForegroundColor Yellow
        exit $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "Fallback install succeeded." -ForegroundColor Green
    Write-Host "Speech-to-text via faster-whisper is disabled on this machine." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Starting server..." -ForegroundColor Green
& $venvPython (Join-Path $ProjectRoot "run_server.py")
exit $LASTEXITCODE
