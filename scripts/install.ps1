# Easy one-line installer for distillr (Windows PowerShell)
# Usage (recommended):
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.ps1 | iex"

$ErrorActionPreference = "Stop"

$Package = "distillr"
$Cli = "distill"
$UvVersion = "0.11.11"
$UvInstallerSha256 = "8034382058eae34a765c6b439d2e1a4987bab519cb444afd117c4bf139d89839"

Write-Host "==> Installing $Package ..." -ForegroundColor Cyan
Write-Host ""

function Get-SuitablePythonCommand {
    foreach ($candidate in @("python", "py")) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) {
            continue
        }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    return $null
}

function Assert-NativeSuccess {
    param(
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][int]$ExitCode
    )
    if ($ExitCode -ne 0) {
        throw "$Operation exited with status $ExitCode."
    }
}

# Prefer uv (the 2026 default for Python CLI tools): it manages its own Python,
# so it works even when no suitable interpreter is on PATH.
#
# If uv is missing AND there's no suitable Python, bootstrap uv via its official
# installer so the one-liner works on a clean machine -- no manual Python setup.
$haveUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)
$python = Get-SuitablePythonCommand
if (-not $haveUv -and -not $python) {
    Write-Host "==> uv and Python 3.12+ are unavailable. Bootstrapping uv..." -ForegroundColor Yellow
    $installer = Join-Path ([System.IO.Path]::GetTempPath()) (([System.IO.Path]::GetRandomFileName()) + ".ps1")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/$UvVersion/install.ps1" -OutFile $installer
        $actualSha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha256 -ne $UvInstallerSha256) {
            throw "uv installer checksum mismatch; refusing to execute it."
        }
        & powershell -NoProfile -ExecutionPolicy ByPass -File $installer
        Assert-NativeSuccess -Operation "uv installer" -ExitCode $LASTEXITCODE
    }
    finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
    # uv installs to %USERPROFILE%\.local\bin; make it usable this session.
    $env:Path = "$env:USERPROFILE\.local\bin;" + $env:Path
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "==> Using uv to install $Package ..." -ForegroundColor Green
    uv tool install $Package
    Assert-NativeSuccess -Operation "uv tool install" -ExitCode $LASTEXITCODE
}
else {
    # Fall back to pipx, which needs a Python 3.12+ interpreter present.
    $python = Get-SuitablePythonCommand
    if (-not $python) {
        Write-Host "Error: need either 'uv' or Python 3.12+." -ForegroundColor Red
        Write-Host "Install uv:     https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Yellow
        Write-Host "Install Python: https://www.python.org/downloads/" -ForegroundColor Yellow
        exit 1
    }

    # Invoke pipx through the verified interpreter. A bare pipx executable can
    # belong to an older Python and silently select an incompatible runtime.
    & $python -m pipx --version 2>$null
    $haveSuitablePipx = $LASTEXITCODE -eq 0
    if (-not $haveSuitablePipx) {
        Write-Host "==> pipx not found. Installing pipx (recommended for CLI tools)..." -ForegroundColor Yellow
        & $python -m pip install --user pipx --quiet
        Assert-NativeSuccess -Operation "pip install pipx" -ExitCode $LASTEXITCODE
        & $python -m pipx ensurepath
        Assert-NativeSuccess -Operation "pipx ensurepath" -ExitCode $LASTEXITCODE
        # Refresh PATH for this session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    }

    Write-Host "==> Using pipx to install $Package ..." -ForegroundColor Green
    & $python -m pipx install --python $python $Package
    Assert-NativeSuccess -Operation "pipx install" -ExitCode $LASTEXITCODE
}

Write-Host ""
Write-Host "==> Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Open a NEW terminal (so PATH updates take effect)"
Write-Host "  2. Run: $Cli init"
Write-Host "     This creates your environment, configures a provider, and installs browser support."
Write-Host ""
Write-Host "Quick test:"
Write-Host "  $Cli --help"
Write-Host "  $Cli doctor"
Write-Host ""
Write-Host "Optional: tab-completion for your shell"
Write-Host "  $Cli --install-completion"
Write-Host ""
Write-Host "To update later:"
Write-Host "  $Cli update            # upgrade in place"
Write-Host "  $Cli update --check    # just check for a newer version"
Write-Host ""
Write-Host "For development / editable install from source:"
Write-Host "  git clone https://github.com/blisspixel/distillr.git"
Write-Host "  cd distillr"
Write-Host "  uv tool install -e .   # or: pipx install -e . / venv instructions in README"
Write-Host ""
