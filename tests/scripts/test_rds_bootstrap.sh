#!/usr/bin/env bash
# Proves infra/terraform/rds-bootstrap.sql takes write access to
# alembic_version back from hax_app after its blanket table grant: the app
# role may read the schema version but never move it. The bootstrap also runs
# on a fresh database before any migration, so the revoke is conditional on
# the table existing (a to_regclass guard driven by \gexec, or a DO block).
# A static check of the SQL text: no database runs here. Comment lines are
# skipped; the statement is read with its whitespace collapsed, so it may span
# lines. Run by hand:
#   bash tests/scripts/test_rds_bootstrap.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
sql=$root/infra/terraform/rds-bootstrap.sql
work=$(mktemp -d "${TMPDIR:-/tmp}/rds-bootstrap-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

[ -f "$sql" ] && report PASS "the bootstrap script exists" || { report FAIL "no $sql"; finish; }

# Numbered non-comment lines.
grep -nvE '^[[:space:]]*--' "$sql" > "$work/code.txt" || true

last_grant=$(grep -iE '^[0-9]+:.*GRANT[[:space:]].*TO[[:space:]]+hax_app' "$work/code.txt" | tail -1 | cut -d: -f1)
[ -n "$last_grant" ] && report PASS "the script grants table privileges to hax_app" \
  || report FAIL "no GRANT ... TO hax_app line"
last_grant=${last_grant:-0}

revoke_re='REVOKE[[:space:]]+[A-Za-z, ]+[[:space:]]+ON[[:space:]]+(TABLE[[:space:]]+)?(public\.)?"?alembic_version"?[[:space:]]+FROM[[:space:]]+hax_app'
revoke_line=$(grep -iE "^[0-9]+:.*REVOKE" "$work/code.txt" | grep -i alembic_version | tail -1 | cut -d: -f1 || true)
# The whole script after the last grant, comments dropped, on one line.
awk -F: -v n="$last_grant" '$1 > n { sub(/^[0-9]+:/, ""); print }' "$work/code.txt" | tr '\n' ' ' | tr -s '[:space:]' ' ' > "$work/after.txt"
revoke=$(grep -ioE "$revoke_re" "$work/after.txt" | head -1 || true)

if [ -n "$revoke" ]; then
  report PASS "alembic_version is revoked from hax_app"
else
  report FAIL "no REVOKE ... ON alembic_version FROM hax_app"
fi

privs=$(printf '%s' "$revoke" | sed -E 's/^REVOKE[[:space:]]+//I; s/[[:space:]]+ON[[:space:]].*$//I' | tr '[:lower:]' '[:upper:]')
for p in INSERT UPDATE DELETE; do
  case ",${privs// /}," in
    *",$p,"*) report PASS "the revoke covers $p" ;;
    *) report FAIL "the revoke does not cover $p (privileges: '${privs:-none}')" ;;
  esac
done
case ",${privs// /}," in
  *",SELECT,"* | *",ALL,"* | *",ALLPRIVILEGES,"*) report FAIL "the revoke takes SELECT away too (privileges: '$privs')" ;;
  *) report PASS "the revoke leaves SELECT in place" ;;
esac

if [ -n "$revoke_line" ] && [ "$revoke_line" -gt "$last_grant" ]; then
  report PASS "the revoke comes after the last grant to hax_app"
else
  report FAIL "the revoke (line ${revoke_line:-none}) is not after the last grant to hax_app (line $last_grant)"
fi

# Guarded: either the revoke is text a SELECT produces under a to_regclass
# guard, executed by \gexec, or it sits in a DO block behind IF to_regclass.
guard='to_regclass\([[:space:]]*'"'"'(public\.)?alembic_version'"'"'[[:space:]]*(::regclass)?\)[[:space:]]+IS[[:space:]]+NOT[[:space:]]+NULL'
# The \gexec segment holding the revoke: text between the previous \gexec
# and the next one, which must exist.
gexec_ok=no
awk '{ gsub(/\\gexec/, "\n"); print }' "$work/after.txt" | awk '{ print NR "\t" $0 }' > "$work/segments.txt"
segments=$(wc -l < "$work/segments.txt" | tr -d ' ')
while IFS=$'\t' read -r i seg; do
  [ "$i" -lt "$segments" ] || continue
  if printf '%s' "$seg" | grep -qiE "SELECT[^;]*['\"(]REVOKE[^;]*alembic_version" \
    && printf '%s' "$seg" | grep -qiE "$guard"; then
    gexec_ok=yes
  fi
done < "$work/segments.txt"
do_ok=no
grep -qiE "DO[[:space:]].*IF[[:space:]]+$guard[[:space:]]+THEN[^;]*REVOKE[^;]*alembic_version" "$work/after.txt" && do_ok=yes

if [ "$gexec_ok" = yes ] || [ "$do_ok" = yes ]; then
  report PASS "the revoke runs only when alembic_version exists"
else
  report FAIL "the revoke is not guarded by to_regclass('public.alembic_version') IS NOT NULL"
fi

# No bare, unconditional revoke on alembic_version: it would fail on a fresh
# database, before the first migration creates the table.
bare=$(grep -iE '^[0-9]+:[[:space:]]*REVOKE[^;]*alembic_version' "$work/code.txt" || true)
if [ -n "$bare" ] && [ "$do_ok" = no ]; then
  report FAIL "an unconditional REVOKE on alembic_version: $bare"
else
  report PASS "no unconditional REVOKE on alembic_version"
fi

finish
