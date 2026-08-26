#Requires -Version 7.0
<#
.SYNOPSIS
    Bridge between the consultant GUI and Invoke-M365Assessment.
.DESCRIPTION
    Translates the GUI's simple flat parameters into a real Invoke-M365Assessment
    call, including building a -CustomBranding hashtable from a JSON file (kept
    as JSON rather than passed as a PowerShell literal on the command line to
    avoid a command-line escaping mess for logo base64 data and free-text
    fields like Disclaimer).

    -OutputFolder is created fresh and empty by the caller (the GUI backend)
    for this one run, so the result is always the single Assessment_* folder
    that appears inside it afterward - no timestamp-guessing needed to find
    the log file or report.

    Device-code / interactive sign-in prompts pass straight through to
    stdout/stderr exactly as Invoke-M365Assessment already produces them -
    this script does not intercept or reformat them. The GUI backend reads
    them the same way it reads everything else from this process.
#>
param(
    [Parameter(Mandatory)] [string]$OutputFolder,
    [Parameter(Mandatory)] [string]$AuthMethod,       # Interactive | DeviceCode | AppReg
    [Parameter()] [string]$TenantId = '',
    [Parameter()] [string]$ProfileName = '',
    [Parameter()] [string]$ClientId = '',
    [Parameter()] [string]$CertificateThumbprint = '',
    [Parameter()] [string]$UserPrincipalName = '',
    # Comma-joined string, not string[]: when this script is launched via
    # "-File" from an external process (as the GUI backend does), PowerShell's
    # -File argument binding does NOT slurp multiple space-separated tokens
    # into an array parameter the way normal in-session calls do - it binds
    # only the first token, then scatters every value after it across
    # whatever OTHER positional parameters happen to still be free, erroring
    # once those run out. Confirmed by direct repro, not assumed. Taking one
    # already-comma-joined string sidesteps that entirely; split below.
    [Parameter()] [string]$Section = '',
    [Parameter()] [switch]$WhiteLabel,
    [Parameter()] [string]$BrandingJsonPath = '',
    [Parameter()] [string]$ReportTheme = 'Neon'
)

$ErrorActionPreference = 'Stop'

Write-Host "GUI_BRIDGE: importing M365-Assess module"
# Load the Graph sub-modules M365-Assess.psd1 lists under RequiredModules
# by hand first. PowerShell is supposed to auto-load these on its own
# when importing the manifest, but that auto-load isn't reliable when the
# manifest is imported by full file path (as below) rather than by name
# from the module path - seen live as "The required module
# 'Microsoft.Graph.Authentication' is not loaded" even though the module
# is genuinely installed. Loading each one explicitly first sidesteps
# that rather than depending on the auto-load working.
foreach ($graphModule in @(
    'Microsoft.Graph.Authentication', 'Microsoft.Graph.Applications',
    'Microsoft.Graph.DeviceManagement', 'Microsoft.Graph.Identity.DirectoryManagement',
    'Microsoft.Graph.Identity.SignIns', 'Microsoft.Graph.Reports',
    'Microsoft.Graph.Security', 'Microsoft.Graph.Users'
)) {
    Import-Module -Name $graphModule -ErrorAction Stop
}

# Prefer the copy sitting next to this script (the downloaded/forked
# source, which has the branding fixes) over whatever else might be on
# the module path - falls back to a plain by-name Import-Module only if
# that local copy isn't there, e.g. someone only copied the gui/ folder
# and separately ran Install-Module M365-Assess.
$localManifest = Join-Path $PSScriptRoot '..\src\M365-Assess\M365-Assess.psd1'
if (Test-Path -Path $localManifest -PathType Leaf) {
    Import-Module $localManifest -Force -ErrorAction Stop
} else {
    Import-Module M365-Assess -Force -ErrorAction Stop
}

$assessParams = @{
    OutputFolder = $OutputFolder
    ReportTheme  = $ReportTheme
}
if ($TenantId)    { $assessParams['TenantId'] = $TenantId }
if ($Section) {
    # Invoke-M365Assessment's real -Section parameter is [string[]] - split
    # back into an array here, right before the one call that needs it.
    $sectionList = @($Section -split ',' | Where-Object { $_ })
    if ($sectionList.Count -gt 0) { $assessParams['Section'] = $sectionList }
}
if ($WhiteLabel)  { $assessParams['WhiteLabel'] = $true }

switch ($AuthMethod) {
    'DeviceCode' {
        $assessParams['UseDeviceCode'] = $true
    }
    'AppReg' {
        if (-not $ClientId) { throw "AppReg auth requires -ClientId" }
        $assessParams['ClientId'] = $ClientId
        if ($CertificateThumbprint) { $assessParams['CertificateThumbprint'] = $CertificateThumbprint }
    }
    'Interactive' {
        if ($UserPrincipalName) { $assessParams['UserPrincipalName'] = $UserPrincipalName }
    }
    default { throw "Unknown AuthMethod: $AuthMethod" }
}

# A saved connection profile can supply auth details Invoke-M365Assessment
# already knows how to load itself - just point it at the name instead of
# duplicating TenantId/ClientId/etc. here. (Real parameter name is
# -ConnectionProfile, not -ProfileName - verified against the actual
# param block rather than assumed.)
if ($ProfileName) {
    $assessParams['ConnectionProfile'] = $ProfileName
}

if ($BrandingJsonPath -and (Test-Path -Path $BrandingJsonPath -PathType Leaf)) {
    try {
        $brandingRaw = Get-Content -Path $BrandingJsonPath -Raw | ConvertFrom-Json -AsHashtable
        # New-M365BrandingConfig validates logo paths exist and hex colors are
        # well-formed, and drops any keys that aren't real parameters -
        # cheaper to let it reject a malformed GUI-saved file than to
        # duplicate its validation here.
        $brandingArgs = @{}
        foreach ($key in $brandingRaw.Keys) {
            if ($brandingRaw[$key]) { $brandingArgs[$key] = $brandingRaw[$key] }
        }
        $branding = New-M365BrandingConfig @brandingArgs
        if ($branding.Count -gt 0) {
            $assessParams['CustomBranding'] = $branding
            Write-Host "GUI_BRIDGE: branding applied ($($branding.Keys -join ', '))"
        }
    } catch {
        Write-Warning "GUI_BRIDGE: could not apply branding from '$BrandingJsonPath': $($_.Exception.Message)"
    }
}

Write-Host "GUI_BRIDGE: starting assessment"
Invoke-M365Assessment @assessParams

# Invoke-M365Assessment builds Assessment_<timestamp>[_suffix] inside
# -OutputFolder itself - report the resolved path explicitly rather than
# have the caller guess the timestamp.
$resultFolder = Get-ChildItem -Path $OutputFolder -Directory -Filter 'Assessment_*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($resultFolder) {
    Write-Host "GUI_BRIDGE: RESULT_FOLDER=$($resultFolder.FullName)"
} else {
    Write-Warning "GUI_BRIDGE: could not locate the Assessment_* result folder under $OutputFolder"
}
