#!/usr/bin/env bash
# Fails when an installed Python package is not pinned, at its installed
# version, in constraints.txt: a dependency added without `make constraints`
# would otherwise install unpinned and quietly fall outside the lock that CI
# and the production image share. CI runs it right after its install step:
#
#   pip freeze --exclude-editable | scripts/check_constraints.sh constraints.txt
#
# Names compare the way pip does (case-insensitive, "-", "_" and "." equal).
set -euo pipefail
pins=${1:?usage: check_constraints.sh <constraints.txt>  (pip freeze on stdin)}
[ -f "$pins" ] || { echo "check_constraints: $pins not found" >&2; exit 1; }

norm() { tr 'A-Z_.' 'a-z--'; }
pinned=$(grep -E '^[A-Za-z0-9._-]+==' "$pins" | norm | sort -u)
installed=$(grep -E '^[A-Za-z0-9._-]+==' | norm | sort -u)

# Installed lines (name==version) absent from the pins: unpinned, or drifted.
bad=$(comm -23 <(printf '%s\n' "$installed") <(printf '%s\n' "$pinned"))
if [ -n "$bad" ]; then
  echo "Installed but not pinned at this version in $pins:" >&2
  printf '  %s\n' $bad >&2
  echo "Run \`make constraints\` from a green dev venv and commit $pins." >&2
  exit 1
fi
echo "check_constraints: $(printf '%s\n' "$installed" | grep -c .) installed packages, all pinned"
