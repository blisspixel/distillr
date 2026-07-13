#!/usr/bin/env bash
# Easy one-line installer for distillr (macOS / Linux)
# Usage (recommended):
#   curl -fsSL https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.sh | bash

set -euo pipefail

PACKAGE="distillr"
CLI="distill"
UV_VERSION="0.11.11"
UV_INSTALLER_SHA256="3a020f8d69019caca567c9038999d130b0ea85866483caf2042c386cb685aef4"

echo "==> Installing $PACKAGE ..."

python312_available() {
    command -v python3 >/dev/null 2>&1 \
        && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
            >/dev/null 2>&1
}

# Prefer uv (the 2026 default for Python CLI tools): it manages its own Python,
# so it works even when no suitable python3 is on PATH.
#
# If uv is missing AND there's no suitable Python, bootstrap uv via its official
# installer so the one-liner works on a clean machine -- no manual Python setup.
if ! command -v uv >/dev/null 2>&1 && ! python312_available; then
    echo "==> uv and Python 3.12+ are unavailable. Bootstrapping uv..."
    installer=$(mktemp "${TMPDIR:-/tmp}/uv-installer.XXXXXX")
    trap 'rm -f "$installer"' EXIT
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" -o "$installer"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$installer" "https://astral.sh/uv/${UV_VERSION}/install.sh"
    else
        echo "Error: need curl or wget to bootstrap uv."
        echo "Install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        actual_sha256=$(sha256sum "$installer" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        actual_sha256=$(shasum -a 256 "$installer" | awk '{print $1}')
    else
        echo "Error: need sha256sum or shasum to verify the uv installer."
        exit 1
    fi
    if [ "$actual_sha256" != "$UV_INSTALLER_SHA256" ]; then
        echo "Error: uv installer checksum mismatch; refusing to execute it."
        exit 1
    fi
    sh "$installer"
    rm -f "$installer"
    trap - EXIT
    # uv installs to ~/.local/bin (or $XDG_BIN_HOME); make it usable this session.
    PATH="$HOME/.local/bin:$PATH"
    if [ -n "${XDG_BIN_HOME:-}" ]; then
        PATH="$XDG_BIN_HOME:$PATH"
    fi
    export PATH
fi

if command -v uv >/dev/null 2>&1; then
    echo "==> Using uv to install $PACKAGE ..."
    uv tool install "$PACKAGE"
else
    # Fall back to pipx, which needs a Python 3.12+ interpreter present.
    if ! python312_available; then
        echo "Error: need either 'uv' or python3 (3.12+)."
        echo "Install uv:     https://docs.astral.sh/uv/getting-started/installation/"
        echo "Install Python: https://www.python.org/downloads/"
        exit 1
    fi

    PYTHON=python3
    if ! "$PYTHON" -m pipx --version >/dev/null 2>&1; then
        echo "==> pipx not found. Installing pipx (recommended for CLI tools)..."
        "$PYTHON" -m pip install --user pipx
        "$PYTHON" -m pipx ensurepath
    fi
    echo "==> Using pipx to install $PACKAGE ..."
    "$PYTHON" -m pipx install --python "$PYTHON" "$PACKAGE"
fi

echo ""
echo "==> Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Open a new terminal (so PATH updates take effect)"
echo "  2. Run: $CLI init"
echo "     This creates your environment, configures a provider, and installs browser support."
echo ""
echo "Quick test:"
echo "  $CLI --help"
echo "  $CLI doctor"
echo ""
echo "Optional: tab-completion for your shell"
echo "  $CLI --install-completion"
echo ""
echo "To update later:"
echo "  $CLI update            # upgrade in place"
echo "  $CLI update --check    # just check for a newer version"
echo ""
echo "For development / editable install from source:"
echo "  git clone https://github.com/blisspixel/distillr.git"
echo "  cd distillr"
echo "  uv tool install -e .    # or: pipx install -e ."
echo ""
