<#
.SYNOPSIS
    One-time setup for the M365-Assess Consultant Console. Run this once;
    use Start-Console.bat for every day after.
#>
Write-Host "M365-Assess Consultant Console - setup" -ForegroundColor Cyan
Write-Host ""

try {
    $pyVer = & python --version 2>&1
    Write-Host "[OK] $pyVer found" -ForegroundColor Green
} catch {
    Write-Host "[XX] Python not found. Install Python 3.11+ from https://python.org/downloads and re-run this script." -ForegroundColor Red
    exit 1
}

Write-Host "Installing GUI dependencies (Flask)..." -ForegroundColor Cyan
& python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt") --quiet

Write-Host ""
Write-Host "Checking M365-Assess module..." -ForegroundColor Cyan
try {
    Import-Module M365-Assess -ErrorAction Stop
    Write-Host "[OK] M365-Assess module found" -ForegroundColor Green
} catch {
    Write-Host "[!!] M365-Assess module not found or failed to load: $_" -ForegroundColor Yellow
    Write-Host "     Install it with: Install-Module M365-Assess -Scope CurrentUser" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. Use Start-Console.bat to launch the console (no PowerShell window)." -ForegroundColor Cyan
