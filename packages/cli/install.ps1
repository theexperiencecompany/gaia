# GAIA CLI Installer for Windows
# Usage: irm https://heygaia.io/install.ps1 | iex

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[info] $msg" -ForegroundColor Blue }
function Write-Ok($msg) { Write-Host "[ok] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[warn] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[error] $msg" -ForegroundColor Red; exit 1 }

Write-Host "`nGAIA CLI Installer`n" -ForegroundColor Blue -NoNewline
Write-Host "" # newline

# Detect package manager
$PkgMgr = $null

if (Get-Command npm -ErrorAction SilentlyContinue) {
    $ver = npm --version
    Write-Ok "npm is already installed ($ver)"
    $PkgMgr = "npm"
} elseif (Get-Command pnpm -ErrorAction SilentlyContinue) {
    $ver = pnpm --version
    Write-Ok "pnpm is already installed ($ver)"
    $PkgMgr = "pnpm"
} elseif (Get-Command bun -ErrorAction SilentlyContinue) {
    $ver = bun --version
    Write-Ok "Bun is already installed ($ver)"
    $PkgMgr = "bun"
} else {
    Write-Err "No supported package manager found (npm, pnpm, or bun). Please install Node.js from https://nodejs.org"
}

# Install GAIA CLI globally
Write-Info "Installing @heygaia/cli via $PkgMgr..."
switch ($PkgMgr) {
    "npm"  { npm install -g @heygaia/cli }
    "pnpm" { pnpm add -g @heygaia/cli }
    "bun"  { bun install -g @heygaia/cli }
}

# Verify installation and fix PATH if needed
if (Get-Command gaia -ErrorAction SilentlyContinue) {
    Write-Ok "GAIA CLI installed successfully!"
    Write-Host ""
    Write-Host "Get started:" -ForegroundColor White
    Write-Host "  gaia init    - Set up GAIA from scratch" -ForegroundColor Green
    Write-Host "  gaia setup   - Configure an existing repo" -ForegroundColor Green
    Write-Host "  gaia status  - Check service health" -ForegroundColor Green
    Write-Host "  gaia --help  - Show all commands" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Warn "Installation completed but 'gaia' command not found in PATH"

    # Try to find and add the bin directory
    $binDir = $null
    switch ($PkgMgr) {
        "npm"  { $binDir = (npm config get prefix) }
        "pnpm" { $binDir = (pnpm bin -g 2>$null) }
        "bun"  { $binDir = Join-Path $env:USERPROFILE ".bun\bin" }
    }

    if ($binDir -and (Test-Path $binDir)) {
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if (-not $userPath.Contains($binDir)) {
            [Environment]::SetEnvironmentVariable("Path", "$binDir;$userPath", "User")
            $env:Path = "$binDir;$env:Path"
            Write-Ok "Added $binDir to your PATH. Restart your terminal for changes to take effect."
        }
    } else {
        Write-Host "  Add the global bin directory for $PkgMgr to your PATH manually." -ForegroundColor Yellow
    }
    Write-Host ""
}
