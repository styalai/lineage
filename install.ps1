<#
lineage installer (Windows / PowerShell)

Usage:
    irm https://raw.githubusercontent.com/styalai/lineage/main/install.ps1 | iex
    $env:LINEAGE_VERSION = "v0.1.0"; irm https://raw.githubusercontent.com/styalai/lineage/main/install.ps1 | iex
    .\install.ps1 -LocalTarball .\lineage-0.1.0.tar.gz

Environment overrides:
    LINEAGE_REPO      GitHub "<owner>/<repo>"
    LINEAGE_VERSION   "latest" (default) or "vX.Y.Z"
    LINEAGE_HOME      install root (default: $HOME\.lineage)
    LINEAGE_BIN_DIR   launcher dir (default: $HOME\.local\bin)
#>
[CmdletBinding()]
param(
    [string]$LocalTarball = ""
)

$ErrorActionPreference = "Stop"

# -----------------------------------------------------------------------------
# Defaults from env
# -----------------------------------------------------------------------------
$repo    = if ($env:LINEAGE_REPO)    { $env:LINEAGE_REPO }    else { "styalai/lineage" }
$version = if ($env:LINEAGE_VERSION) { $env:LINEAGE_VERSION } else { "latest" }
$homeDir = if ($env:LINEAGE_HOME)    { $env:LINEAGE_HOME }    else { Join-Path $HOME ".lineage" }
$binDir  = if ($env:LINEAGE_BIN_DIR) { $env:LINEAGE_BIN_DIR } else { Join-Path $HOME ".local\bin" }

function Write-Info    { param($m) Write-Host "lineage: $m" }
function Write-Success { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "[!] $m" -ForegroundColor Yellow }
function Write-Fail    { param($m) Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# -----------------------------------------------------------------------------
# Find Python 3.11+
# -----------------------------------------------------------------------------
function Find-Python {
    $candidates = @("py", "python", "python3", "python3.11", "python3.12", "python3.13")
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $ver = & $cmd.Source "-c" "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver -and $ver -match '^3\.(1[1-9]|[2-9][0-9]?)(\..*)?$') {
                return $cmd.Source
            }
        } catch {}
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Fail "Python 3.11+ not found. Install from https://www.python.org/downloads/ and retry."
}
$pyVer = & $python "-c" "import sys; print('%d.%d.%d' % sys.version_info[:3])"
Write-Info "found Python $pyVer at $python"

# -----------------------------------------------------------------------------
# Resolve version
# -----------------------------------------------------------------------------
function Resolve-Version {
    param([string]$v, [string]$local)
    if ($v -ne "latest") { return $v }
    if ($local)         { return "local" }
    try {
        $api = "https://api.github.com/repos/$repo/releases/latest"
        $resp = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "lineage-installer" } -TimeoutSec 15
        if ($resp.tag_name) { return $resp.tag_name }
    } catch {}
    try {
        $api = "https://api.github.com/repos/$repo/tags?per_page=1"
        $resp = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "lineage-installer" } -TimeoutSec 15
        if ($resp -and $resp.Count -gt 0 -and $resp[0].name) { return $resp[0].name }
    } catch {}
    Write-Fail "Could not resolve 'latest' version. Set LINEAGE_VERSION=vX.Y.Z or pass -LocalTarball."
}

$versionTag = Resolve-Version -v $version -local $LocalTarball
Write-Info "installing lineage $versionTag"

# -----------------------------------------------------------------------------
# Fetch & extract
# -----------------------------------------------------------------------------
$workDir = Join-Path $homeDir $versionTag
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
New-Item -ItemType Directory -Force -Path $binDir  | Out-Null

if ($LocalTarball) {
    Write-Info "extracting local tarball: $LocalTarball"
    if (-not (Test-Path $LocalTarball)) { Write-Fail "tarball not found: $LocalTarball" }
    tar -xz -f $LocalTarball -C $workDir --strip-components=1
} else {
    $tarUrl = "https://github.com/$repo/archive/refs/tags/$versionTag.tar.gz"
    Write-Info "downloading $tarUrl"
    $tmpTar = Join-Path ([System.IO.Path]::GetTempPath()) ("lineage-" + [Guid]::NewGuid().ToString("N").Substring(0,8) + ".tar.gz")
    try {
        Invoke-WebRequest -Uri $tarUrl -OutFile $tmpTar -UseBasicParsing
        tar -xz -f $tmpTar -C $workDir --strip-components=1
    } finally {
        if (Test-Path $tmpTar) { Remove-Item $tmpTar -Force -ErrorAction SilentlyContinue }
    }
}

if (-not (Test-Path (Join-Path $workDir "lineage"))) {
    Write-Fail "extracted tree is missing the 'lineage/' package. Is $versionTag a valid release?"
}

# -----------------------------------------------------------------------------
# Write the launcher
# -----------------------------------------------------------------------------
$launcher = Join-Path $binDir "lineage.bat"
$launcherContent = @"
@echo off
rem Auto-generated by the lineage installer. Do not edit.
rem To update or remove, re-run the installer or delete: $launcher
setlocal

set "WORKDIR=$workDir"
set "PYEXE=$python"

if not exist "%WORKDIR%\lineage" (
    echo lineage: install at %WORKDIR% is missing or corrupted. 1>&2
    echo lineage: re-run the installer to repair. 1>&2
    exit /b 1
)

set "PYTHONPATH=%WORKDIR%;%PYTHONPATH%"
"%PYEXE%" -m lineage %*
exit /b %ERRORLEVEL%
"@
Set-Content -Path $launcher -Value $launcherContent -Encoding ASCII

Set-Content -Path (Join-Path $homeDir ".current") -Value $versionTag

# -----------------------------------------------------------------------------
# PATH advice
# -----------------------------------------------------------------------------
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$binDir*") {
    Write-Warn "$binDir is not on your PATH."
    try {
        [Environment]::SetEnvironmentVariable("Path", "$binDir;$currentPath", "User")
        Write-Success "added $binDir to user PATH (open a new shell to take effect)"
    } catch {
        Write-Warn "could not update user PATH automatically. Add $binDir to your PATH manually."
    }
}

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
Write-Success "lineage $versionTag installed"
Write-Host "  binary:    $launcher"
Write-Host "  installed: $workDir"
Write-Host "  python:    $python ($pyVer)"
Write-Host ""
Write-Host "Next: open a new PowerShell window and run:  lineage --help"
