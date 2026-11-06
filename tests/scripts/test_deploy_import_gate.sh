#!/usr/bin/env bash
# Proves deploy.sh's import gate and its short sha.
#
# Import gate: the roll script is an unquoted heredoc, so it is rendered the
# way deploy.sh renders it (local expansion, escaped \$ left for the box),
# its order is checked (the pull, then the import gate, then the migrate
# gate, then promotion and `compose up`), and then it is run in a temp dir with stub docker,
# curl, df and flock on PATH. A failed import must leave the old
# images.env, compose.prod.yml and Caddyfile byte-identical and never reach
# `compose up`; a passing one must promote and bring the stack up.
#
# Short sha: build/push tag with exactly the first 7 characters of HEAD's
# sha whatever git's core.abbrev says, and refuse any other tag naming HEAD
# by those 7 characters.
# Run by hand:
#   bash tests/scripts/test_deploy_import_gate.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/deploy-import-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

new_py=ghcr.io/x/hax-py:newsha
new_web=ghcr.io/x/hax-web:newsha

# The heredoc block, from "remote=$(cat <<REMOTE" to its closing ")".
awk '/^  remote=\$\(cat <<REMOTE/{f=1} f{print} f&&/^\)$/{exit}' \
  "$root/infra/deploy/deploy.sh" > "$work/block.sh"
{
  echo "raw=x PY_IMAGE=$new_py WEB_IMAGE=$new_web"
  cat "$work/block.sh"
  echo 'printf "%s\n" "$remote"'
} > "$work/render.sh"
bash "$work/render.sh" > "$work/roll.sh"
[ -s "$work/roll.sh" ] || { echo "FAIL: the roll script did not render"; exit 1; }

# Backslash continuations joined, so a command split over lines is one line.
awk '{ if (sub(/\\$/, "")) { buf = buf $0 } else { print buf $0; buf = "" } }' \
  "$work/roll.sh" > "$work/joined.sh"

# First line number of a command (comments skipped) matching an ERE, or empty.
line_of() { grep -nE "$1" "$work/joined.sh" | grep -vE '^[0-9]+:[[:space:]]*#' | head -1 | cut -d: -f1 || true; }
import_at=$(line_of 'compose run.*apps\.api\.main')
migrate_at=$(line_of 'compose run.*migrate')
pull_at=$(line_of 'compose pull')
promote_at=$(line_of '^[[:space:]]*mv |(>|tee) *(Caddyfile|images\.env|compose\.prod\.yml)([[:space:];&)]|$)')
up_at=$(line_of 'compose up')
import_line=$( [ -n "$import_at" ] && sed -n "${import_at}p" "$work/joined.sh" || true)

if [ -n "$import_at" ] && [ -n "$pull_at" ] && [ -n "$migrate_at" ] \
  && [ "$pull_at" -lt "$import_at" ] && [ "$import_at" -lt "$migrate_at" ]; then
  report PASS "the import gate runs after the pull and before the migrate gate"
else
  report FAIL "the import gate (line ${import_at:-none}) is not between the pull (line ${pull_at:-none}) and the migrate gate (line ${migrate_at:-none})"
fi
if [ -n "$import_at" ] && { [ -z "$promote_at" ] || [ "$import_at" -lt "$promote_at" ]; }; then
  report PASS "the import gate runs before any promotion of compose.prod.yml, images.env or Caddyfile"
else
  report FAIL "the import gate (line ${import_at:-none}) is not before the first promotion (line ${promote_at:-none})"
fi
if [ -n "$import_at" ] && [ -n "$up_at" ] && [ "$import_at" -lt "$up_at" ]; then
  report PASS "the import gate runs before compose up"
else
  report FAIL "the import gate (line ${import_at:-none}) is not before compose up (line ${up_at:-none})"
fi

has() { case "$import_line" in *$1*) return 0 ;; *) return 1 ;; esac; }
has_re() { printf '%s\n' "$import_line" | grep -qE -- "$1"; }
if [ -n "$import_line" ] && has 'IMAGES_ENV=images.env.next' && has 'COMPOSE_FILE=compose.prod.yml.new'; then
  report PASS "the import gate runs against the staged images.env.next and compose.prod.yml.new"
else
  report FAIL "the import gate does not use the staged images.env.next and compose.prod.yml.new"
fi
if [ -n "$import_line" ] && has_re '[[:space:]]--rm([[:space:]]|$)' && has_re '[[:space:]]-T([[:space:]]|$)' \
  && has_re '[[:space:]]--no-deps([[:space:]]|$)'; then
  report PASS "the import gate is a one-off run with --rm, -T and --no-deps"
else
  report FAIL "the import gate lacks one of --rm, -T, --no-deps"
fi
if [ -n "$import_line" ] && has_re '[[:space:]]api[[:space:]]+python[0-9.]*[[:space:]]+-c'; then
  report PASS "the import gate runs python -c in the api service"
else
  report FAIL "the import gate does not run python -c in the api service"
fi
if [ -n "$import_line" ] && has_re '<[[:space:]]*/dev/null'; then
  report PASS "the import gate reads stdin from /dev/null"
else
  report FAIL "the import gate does not read stdin from /dev/null"
fi
if [ -n "$import_line" ] && has 'apps.api.main' && has 'apps.worker.celery_app'; then
  report PASS "the import gate imports both apps.api.main and apps.worker.celery_app"
else
  report FAIL "the import gate does not import both apps.api.main and apps.worker.celery_app"
fi

# --- Running the rendered roll script against stubs. ---
mkdir -p "$work/bin"
# docker: logs argv; a compose run of the api service fails when
# IMPORT_FAIL=1; caddy is running and serves the host's Caddyfile (the cwd
# is the box dir); everything else succeeds.
cat > "$work/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
case " $* " in
  *" exec "*" caddy cat "*) cat Caddyfile; exit 0 ;;
  *" ps "*caddy*) echo caddy; exit 0 ;;
esac
if [ "${1:-}" = compose ] && [ "${IMPORT_FAIL:-0}" = 1 ]; then
  run=0 api=0
  for a in "$@"; do
    [ "$a" = run ] && run=1
    [ "$a" = api ] && api=1
  done
  if [ "$run" = 1 ] && [ "$api" = 1 ]; then
    echo "ImportError: stub import failure" >&2
    exit 1
  fi
fi
exit 0
STUB
# curl: the staged files' new contents, by the URL's last path part; -o writes them to
# the named file, otherwise to stdout. Health checks just succeed.
cat > "$work/bin/curl" <<'STUB'
#!/usr/bin/env bash
out="" url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--output) out=$2; shift ;;
    -*) ;;
    *) url=$1 ;;
  esac
  shift
done
case "$url" in
  *compose.prod.yml*) body="NEW compose.prod.yml" ;;
  *Caddyfile*) body="NEW Caddyfile" ;;
  *) body="" ;;
esac
if [ -n "$out" ]; then printf '%s\n' "$body" > "$out"; else [ -z "$body" ] || printf '%s\n' "$body"; fi
exit 0
STUB
printf '#!/bin/sh\necho Avail\necho %s\n' "$((100 * 1024 * 1024))" > "$work/bin/df"
printf '#!/bin/sh\nexit 0\n' > "$work/bin/flock"
printf '#!/bin/sh\nexit 0\n' > "$work/bin/sleep"
chmod +x "$work/bin/"*

# The roll script starts with `cd /opt/hax` and reads /opt/hax/.env; the
# rendered copy has every /opt/hax rewritten to the temp box dir (which is
# seeded with a fake .env), and nothing else is changed.
roll() {
  local box="$work/box-$1"
  rm -rf "$box"; mkdir -p "$box"
  printf 'FAKE=1\n' > "$box/.env"
  printf 'OLD images.env\n' > "$box/images.env"
  printf 'OLD compose.prod.yml\n' > "$box/compose.prod.yml"
  printf 'OLD Caddyfile\n' > "$box/Caddyfile"
  cp "$box/images.env" "$box/images.env.orig"
  cp "$box/compose.prod.yml" "$box/compose.prod.yml.orig"
  cp "$box/Caddyfile" "$box/Caddyfile.orig"
  sed "s#/opt/hax#$box#g" "$work/roll.sh" > "$work/roll-$1.sh"
  : > "$work/docker-$1.log"
  DOCKER_LOG="$work/docker-$1.log" IMPORT_FAIL=$2 PATH="$work/bin:$PATH" \
    bash "$work/roll-$1.sh" > "$work/out-$1.txt" 2>&1
}
same() { cmp -s "$work/box-fail/$1" "$work/box-fail/$1.orig"; }

if roll fail 1; then
  report FAIL "a failed import: the roll exits zero"
else
  report PASS "a failed import: the roll exits non-zero"
fi
# Guards the checks below against passing because the roll stopped earlier.
if grep -E '(^| )run( |$)' "$work/docker-fail.log" | grep -qE '(^| )api( |$)'; then
  report PASS "a failed import: the roll got as far as the api import run"
else
  report FAIL "a failed import: the roll never ran the api import ($(tail -2 "$work/out-fail.txt" | tr '\n' ' '))"
fi
if grep -qE '(^| )up( |$)' "$work/docker-fail.log"; then
  report FAIL "a failed import: compose up still ran"
else
  report PASS "a failed import: compose up never runs"
fi
if grep -E '(^| )run( |$)' "$work/docker-fail.log" | grep -qE '(^| )migrate( |$)'; then
  report FAIL "a failed import: the migrate still ran"
else
  report PASS "a failed import: the migrate never runs"
fi
if same images.env && same compose.prod.yml && same Caddyfile; then
  report PASS "a failed import: images.env, compose.prod.yml and Caddyfile keep their old contents"
else
  report FAIL "a failed import: a running-stack file was changed"
fi

if roll pass 0; then
  report PASS "a passing import: the roll exits zero"
else
  report FAIL "a passing import: the roll exits non-zero ($(tail -3 "$work/out-pass.txt" | tr '\n' ' '))"
fi
if grep -qE '(^| )up( .*)? -d( |$)|(^| )up -d' "$work/docker-pass.log"; then
  report PASS "a passing import: compose up -d runs"
else
  report FAIL "a passing import: compose up -d never ran"
fi
if grep -q "$new_py" "$work/box-pass/images.env" 2>/dev/null \
  && grep -q 'NEW compose.prod.yml' "$work/box-pass/compose.prod.yml" 2>/dev/null \
  && grep -q 'NEW Caddyfile' "$work/box-pass/Caddyfile" 2>/dev/null; then
  report PASS "a passing import: images.env, compose.prod.yml and Caddyfile hold the new contents"
else
  report FAIL "a passing import: the new contents were not promoted"
fi

# --- Short sha under a longer core.abbrev. ---
full=$(git -C "$root" rev-parse HEAD)
sha7=${full:0:7}
other=0000000; [ "$other" != "$sha7" ] || other=1111111
# docker: logs argv; `manifest inspect` exits 1 (the tag is not on the
# registry yet), everything else succeeds.
cat > "$work/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
[ "${1:-}" = manifest ] && exit 1
exit 0
STUB
chmod +x "$work/bin/docker"
deploy() {
  : > "$work/docker-deploy.log"
  env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.abbrev GIT_CONFIG_VALUE_0=12 \
    DEPLOY_ALLOW_DIRTY=1 GHCR_OWNER=x DOCKER_LOG="$work/docker-deploy.log" PATH="$work/bin:$PATH" \
    bash "$root/infra/deploy/deploy.sh" "$@" 2>&1
}
build() { deploy build "$1"; }

out=$(build "$sha7") && status=0 || status=$?
case "$out" in
  *"pass a sha to roll only"*) report FAIL "core.abbrev=12: build of HEAD's 7-char sha is refused ($out)" ;;
  *) report PASS "core.abbrev=12: build of HEAD's 7-char sha is not refused" ;;
esac

# push with no sha: the tag defaults to HEAD's, so no refusal confounds it.
# Every ghcr.io reference in its `docker tag` and `docker push` argv must end
# in exactly :<sha7>.
out=$(deploy push) && status=0 || status=$?
grep -E '^(tag|push) ' "$work/docker-deploy.log" > "$work/tagpush.log" || true
refs=$(grep -oE 'ghcr\.io/[^[:space:]]+' "$work/tagpush.log" || true)
bad=$(printf '%s\n' "$refs" | grep -vE ":$sha7\$" | grep . || true)
if [ "$status" -eq 0 ] && grep -q '^tag ' "$work/tagpush.log" && grep -q '^push ' "$work/tagpush.log" \
  && [ -n "$refs" ] && [ -z "$bad" ]; then
  report PASS "core.abbrev=12: push tags images with exactly HEAD's first 7 characters"
else
  report FAIL "core.abbrev=12: push does not tag and push images with exactly :$sha7 (exit $status; refs: $(echo $refs); out: $(echo "$out" | tail -2 | tr '\n' ' '))"
fi

out=$(build "$other") && status=0 || status=$?
if [ "$status" -ne 0 ] && [[ "$out" == *"builds HEAD ($sha7); pass a sha to roll only"* ]]; then
  report PASS "core.abbrev=12: build of another sha is refused, naming HEAD by its first 7 characters"
else
  report FAIL "core.abbrev=12: build of another sha is not refused naming HEAD as $sha7 (exit $status: $out)"
fi

finish
