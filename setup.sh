#!/usr/bin/env bash
# Run: source setup.sh   (sets up project + activates venv)
#  or: bash setup.sh      (sets up project, prints activation hint)

# ── Detect sourced vs executed ──
SOURCED=0
if [[ -n "${BASH_SOURCE[0]}" && "${BASH_SOURCE[0]}" != "${0}" ]]; then
  SOURCED=1
elif [[ -n "${ZSH_VERSION}" && "${ZSH_EVAL_CONTEXT}" == *"file"* ]]; then
  SOURCED=1
fi

# Resolve repo root from script location
if [[ -n "${BASH_SOURCE[0]}" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "${ZSH_VERSION}" ]]; then
  ROOT="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else
  ROOT="$(cd "$(dirname "$0")" && pwd)"
fi
cd "$ROOT"

die() {
  echo "ERROR: $1" >&2
  if [[ "$SOURCED" -eq 1 ]]; then return 1; else exit 1; fi
}

# ── Check prerequisites ──
echo "Checking prerequisites..."

# Python 3.11+
PYTHON=""
for cmd in python3.12 python3.11 python3; do
  if command -v "$cmd" &>/dev/null; then
    if "$cmd" -c 'import sys; exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
      PYTHON="$cmd"
      break
    fi
  fi
done
[[ -z "$PYTHON" ]] && die "Python 3.11+ not found. Install via pyenv or Homebrew."
echo "  Python: $("$PYTHON" --version)"

# Node.js + npm (for apps/web)
command -v node &>/dev/null || die "Node.js not found. Install via nvm or Homebrew."
echo "  Node:   $(node --version)"
command -v npm &>/dev/null || die "npm not found."
echo "  npm:    $(npm --version)"

# Docker (warn only — not blocking setup)
if command -v docker &>/dev/null; then
  echo "  Docker: $(docker --version | cut -d' ' -f3 | tr -d ',')"
else
  echo "  Docker: not found (needed for 'make infra-up')"
fi

# ── Python venv + dependencies ──
if [[ ! -d .venv ]]; then
  echo "Creating Python venv..."
  "$PYTHON" -m venv .venv
else
  echo "Python venv exists, skipping creation."
fi

if ! .venv/bin/pip show fastapi &>/dev/null; then
  echo "Installing Python dependencies..."
  .venv/bin/pip install --quiet -r requirements.txt
  .venv/bin/pip install --quiet -e ".[dev]"
else
  echo "Python dependencies already installed."
fi

# ── Node.js dependencies (apps/web) ──
if [[ ! -d apps/web/node_modules ]]; then
  echo "Installing Node.js dependencies (apps/web)..."
  npm install --prefix apps/web
else
  echo "Node.js dependencies already installed (apps/web)."
fi

# ── Pre-commit hooks (black + ruff on commit) ──
if [[ ! -f .git/hooks/pre-commit ]]; then
  echo "Installing pre-commit hooks..."
  .venv/bin/pre-commit install
else
  echo "Pre-commit hooks already installed."
fi

# ── Activate venv ──
echo ""
if [[ "$SOURCED" -eq 1 ]]; then
  source .venv/bin/activate
  echo "Setup complete. Venv activated."
else
  echo "Setup complete. Run 'source .venv/bin/activate' to activate venv."
fi
