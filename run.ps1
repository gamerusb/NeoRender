# NeoRender Pro: always Python 3.13 from project root (avoids old `python` in PATH).
# Examples:
#   .\run.ps1 -m pip install -r requirements.txt
#   .\run.ps1 -m playwright install chromium
#   .\run.ps1 -c "import sys; print(sys.version)"

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if ($args.Count -eq 0) {
    Write-Host "NeoRender Pro -> py -3.13" -ForegroundColor Cyan
    Write-Host "Project: $ProjectRoot"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\run.ps1 -m pip install -r requirements.txt"
    Write-Host "  .\run.ps1 -m pip install -r requirements-dev.txt"
    Write-Host "  .\run.ps1 -m pytest tests -v"
    Write-Host "  .\run.ps1 -m playwright install chromium"
    Write-Host "  .\run.ps1 -c `"import sys; print(sys.version)`""
    exit 0
}

& py -3.13 @args
exit $LASTEXITCODE
