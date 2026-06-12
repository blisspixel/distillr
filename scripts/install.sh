#!/usr/bin/env bash
# Easy one-line installer for distillr (macOS / Linux)
# Usage (recommended):
#   curl -fsSL https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.sh | bash

set -euo pipefail

PACKAGE="distillr"
CLI="distill"

echo "==> Installing $PACKAGE ..."

# Ensure Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required (Python 3.12+)."
    echo "Install via your package manager or https://www.python.org/downloads/"
    exit 1
fi

PYTHON=python3
PYVER=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
if [ "$(printf '%s\n' "3.12" "$PYVER" | sort -V | head -1)" != "3.12" ]; then
    echo "Error: Python 3.12+ is required (found $PYVER)."
    exit 1
fi

# Prefer pipx
if ! command -v pipx >/dev/null 2>&1; then
    echo "==> pipx not found. Installing pipx (recommended for CLI tools)..."
    $PYTHON -m pip install --user pipx
    $PYTHON -m pipx ensurepath
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Using pipx to install $PACKAGE ..."
pipx install "$PACKAGE"

echo ""
echo "==> Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Open a new terminal (so PATH updates take effect)"
echo "  2. Run: $CLI doctor"
echo "  3. Set your API keys (XAI_API_KEY recommended, GEMINI for some features)"
echo "  4. Optional but recommended for full features:"
echo "       playwright install chromium"
echo ""
echo "Quick test:"
echo "  $CLI --help"
echo "  $CLI doctor"
echo ""
echo "For development / editable install from source:"
echo "  git clone https://github.com/blisspixel/distillr.git"
echo "  cd distillr"
echo "  pipx install -e ."
echo ""