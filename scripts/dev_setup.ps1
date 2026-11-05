[CmdletBinding()]
param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')"
    }
}

Push-Location $Root
try {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Invoke-Checked $Python @("-m", "venv", ".venv")
    }
    Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", "requirements-dev.txt")
    Invoke-Checked $VenvPython @("-m", "playwright", "install", "chromium")
    Invoke-Checked $VenvPython @("-m", "pip", "check")
    Invoke-Checked $VenvPython @("-c", "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); browser = p.chromium.launch(); browser.close(); p.stop()")
    Invoke-Checked $VenvPython @("-m", "pytest", "-q", "tests\test_readiness.py")
    Write-Host "Ready. Use .\.venv\Scripts\python.exe for the documented Flask commands."
} finally {
    Pop-Location
}
