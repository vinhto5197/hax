#!/usr/bin/env bash
# Proves the build toolchain itself is pinned, not only the app's packages:
# the production image never upgrades pip to whatever is latest, and the
# project's build backend (setuptools) is an exact version, so neither can
# change under an unchanged commit. The pip check reads one line at a time:
# an upgrade split across a continuation line is not seen. Runs with the other
# script tests in `make ci` (CI's lint job); by hand:
#   bash tests/scripts/test_build_pins.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
docker=$root/infra/docker/python.Dockerfile
pyproject=$root/pyproject.toml
fails=0

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

[ -f "$docker" ] && report PASS "the Python Dockerfile exists" || report FAIL "no $docker"

# Any `pip install` naming pip itself (quoted or not, with or without -U) must
# give it an exact version.
upgrades=$(grep -E "pip install.*[[:space:]][\"']?pip([[:space:]=<>~!\"']|$)" "$docker" || true)
unpinned=$(printf '%s\n' "$upgrades" | grep -vE "[[:space:]][\"']?pip==[0-9]+\.[0-9]+(\.[0-9]+)?[\"']?([[:space:]]|$)" | grep . || true)
[ -z "$unpinned" ] \
  && report PASS "the image upgrades pip only to an exact version" \
  || report FAIL "unpinned pip upgrade: $unpinned"

requires=$(awk '/^\[build-system\]/{f=1;next} /^\[/{f=0} f && /^requires[[:space:]]*=/' "$pyproject")
[ -n "$requires" ] && report PASS "pyproject.toml declares build-system requires" || report FAIL "no [build-system] requires"
printf '%s\n' "$requires" | grep -qE '"setuptools==[0-9]+\.[0-9]+\.[0-9]+"' \
  && report PASS "setuptools is pinned at an exact version" \
  || report FAIL "setuptools is not an exact pin: $requires"
printf '%s\n' "$requires" | grep -qE 'setuptools[[:space:]]*(>|<|~|!|,)' \
  && report FAIL "setuptools carries a range: $requires" \
  || report PASS "setuptools carries no range"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
