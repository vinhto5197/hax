#!/usr/bin/env bash
# Fails when an installed Python package is not pinned, at its installed
# version, in constraints.txt, and on any freeze line that is not a
# `name==version` release (a blank, a comment or an editable `-e` excepted): a dependency added without `make constraints`
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
freeze=$(cat)
installed=$(printf '%s\n' "$freeze" | grep -E '^[A-Za-z0-9._-]+==' | norm | sort -u || true)

# Anything else that is not a blank, a comment or an editable (`-e`, the
# project itself) is no pinned release: a direct-URL install (`name @ git+…`,
# `name @ file://…`) carries no version the pins could hold, so it would
# otherwise pass unseen.
unpinnable=$(printf '%s\n' "$freeze" | grep -Ev '^[[:space:]]*(#|$)|^-e[[:space:]]' | grep -Ev '^[A-Za-z0-9._-]+==' || true)
if [ -n "$unpinnable" ]; then
  echo "Not a name==version release (installed from a URL or path?):" >&2
  printf '%s\n' "$unpinnable" | sed 's/^/  /' >&2
  echo "Install it from the index at an exact version, pinned in $pins." >&2
  exit 1
fi

# Installed lines (name==version) absent from the pins: unpinned, or drifted.
bad=$(comm -23 <(printf '%s\n' "$installed") <(printf '%s\n' "$pinned"))
if [ -n "$bad" ]; then
  echo "Installed but not pinned at this version in $pins:" >&2
  printf '  %s\n' $bad >&2
  echo "Run \`make constraints\` from a green dev venv and commit $pins." >&2
  exit 1
fi
echo "check_constraints: $(printf '%s\n' "$installed" | grep -c .) installed packages, all pinned"
