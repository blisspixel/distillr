# Easy one-line installer for distillr (Windows PowerShell)
# Usage (recommended):
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.ps1 | iex"

$ErrorActionPreference = "Stop"

$Package = "distillr"
$Cli = "distill"

Write-Host "==> Installing $Package ..." -ForegroundColor Cyan
Write-Host ""

# Prefer uv (the 2026 default for Python CLI tools): it manages its own Python,
# so it works even when no suitable interpreter is on PATH.
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "==> Using uv to install $Package ..." -ForegroundColor Green
    uv tool install $Package
}
else {
    # Fall back to pipx, which needs a Python 3.12+ interpreter present.
    $python = "python"
    if (-not (Get-Command $python -ErrorAction SilentlyContinue)) {
        $python = "py"
    }
    if (-not (Get-Command $python -ErrorAction SilentlyContinue)) {
        Write-Host "Error: need either 'uv' or Python 3.12+." -ForegroundColor Red
        Write-Host "Install uv:     https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Yellow
        Write-Host "Install Python: https://www.python.org/downloads/" -ForegroundColor Yellow
        exit 1
    }

    $ver = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if (-not $ver -or ([version]$ver -lt [version]"3.12")) {
        Write-Host "Error: Python 3.12+ is required (found $ver). Or install uv, which manages its own Python." -ForegroundColor Red
        exit 1
    }

    # pipx: isolated, automatic PATH shims, no activation
    if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
        Write-Host "==> pipx not found. Installing pipx (recommended for CLI tools)..." -ForegroundColor Yellow
        & $python -m pip install --user pipx --quiet
        & $python -m pipx ensurepath
        # Refresh PATH for this session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    }

    Write-Host "==> Using pipx to install $Package ..." -ForegroundColor Green
    pipx install $Package
}

Write-Host ""
Write-Host "==> Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Open a NEW terminal (so PATH updates take effect)"
Write-Host "  2. Run: $Cli doctor"
Write-Host "  3. Set your API keys (XAI_API_KEY recommended, GEMINI for some features)"
Write-Host "  4. Optional but recommended for full features:"
Write-Host "       playwright install chromium"
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