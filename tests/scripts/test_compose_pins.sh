#!/usr/bin/env bash
# Proves every third-party image in infra/compose/compose.prod.yml is pinned
# by both a version tag and a digest, so a deploy at an unchanged commit pulls
# the same bytes: `<name>:<tag>@sha256:<64 hex>`, the tag at least
# major.minor (a bare major such as `7-alpine` floats across minors). Our own
# images (values starting `${HAX_`) are tagged by commit sha at deploy time
# and are skipped. Reads `image:` lines one at a time. Run by hand:
#   bash tests/scripts/test_compose_pins.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
compose=$root/infra/compose/compose.prod.yml
work=$(mktemp -d "${TMPDIR:-/tmp}/compose-pins-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

[ -f "$compose" ] && report PASS "compose.prod.yml exists" || { report FAIL "no $compose"; finish; }

# image values, comments and surrounding quotes stripped.
grep -E '^[[:space:]]*image:' "$compose" \
  | sed -E 's/^[[:space:]]*image:[[:space:]]*//; s/[[:space:]]+#.*$//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//; s/[[:space:]]+$//' \
  | grep -vE '^\$\{HAX_' > "$work/images.txt" || true

count=$(wc -l < "$work/images.txt" | tr -d ' ')
[ "$count" -gt 0 ] && report PASS "third-party images found ($count)" || report FAIL "no third-party images found"

while IFS= read -r img; do
  name=${img%%[:@]*}
  if printf '%s' "$img" | grep -qE '^[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$'; then
    report PASS "$name: pinned by tag and digest"
  else
    report FAIL "$name: not pinned as <name>:<tag>@sha256:<digest> ('$img')"
  fi
  tag=${img#*:}
  tag=${tag%%@*}
  [ "$tag" = "$img" ] && tag=""
  if printf '%s' "$tag" | grep -qE '^v?[0-9]+\.[0-9]+'; then
    report PASS "$name: the tag names at least major.minor"
  else
    report FAIL "$name: the tag '${tag:-none}' is not at least major.minor"
  fi
done < "$work/images.txt"

finish
