#!/usr/bin/env bash
# Run with: source setup.sh (activates venv in current shell when done)
set -e

# Resolve repo root from script location
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Error handler: return when sourced, exit when executed
die() {
  echo "$1"
  if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    exit 1
  else
    return 1
  fi
}

# Pick Python 3.11+ (python3.11, python3.12, or python3)
PYTHON=""
for candidate in python3.11 python3.12 python3; do
  if command -v "$candidate" &>/dev/null; then
    if "$candidate" -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  die "Error: Python 3.11+ required. Install via pyenv or Homebrew."
fi
echo "Using $($PYTHON --version)"

# Create .venv if missing (skips if it already exists)
if [ -d ".venv" ]; then
  echo ".venv exists. Remove it first to recreate (rm -rf .venv)"
else
  "$PYTHON" -m venv .venv
fi

# Install requirements.txt and dev deps (black, ruff, pre-commit)
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e ".[dev]"

# Install pre-commit git hook (runs black + ruff on commit)
.venv/bin/pre-commit install

# Activate venv in current shell (only persists when script is sourced)
source .venv/bin/activate
echo "Done. Venv activated."
