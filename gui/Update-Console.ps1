<#
.SYNOPSIS
    Gets the latest version of every console file, all at once.
.DESCRIPTION
    Run this any time you're told there's a fix to get. It always
    re-downloads every file together, so you never end up with a mix of
    some old files and some new ones (which is what caused the last two
    mismatched-file problems).
#>
$ErrorActionPreference = 'Stop'
$branch = 'consultant-gui'
$base = "https://raw.githubusercontent.com/AbuAyrin/M365-Assess/$branch/gui"
$files = @('Setup.ps1', 'Run-Assessment.ps1', 'backend.py', 'index.html', 'Start-Console.bat', 'requirements.txt', 'Update-Console.ps1')

Write-Host "Updating the console (getting the latest copy of every file)..." -ForegroundColor Cyan
foreach ($f in $files) {
    Write-Host "  getting $f" -ForegroundColor Gray
    Invoke-WebRequest -Uri "$base/$f" -OutFile (Join-Path $PSScriptRoot $f)
}

Write-Host ""
Write-Host "Done. Every file is now the latest version." -ForegroundColor Green
Write-Host "Close this window, close the console browser tab if it's open, then start the console again with Start-Console.bat." -ForegroundColor Green
