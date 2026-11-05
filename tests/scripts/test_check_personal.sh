#!/usr/bin/env bash
# Proves scripts/check_personal.sh: a line ADDED by a change that contains a
# denylisted personal string (whole word, any case) fails the check, which
# names the file and line but never prints the string or the line (CI logs
# are public); lines already in the repo, removed lines and partial-word
# matches pass; with no denylist the check is skipped, never failed. The
# denylist comes from PERSONAL_DENYLIST (CI secret) or the gitignored
# local/personal-denylist.txt. Run by hand:
#   bash tests/scripts/test_check_personal.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
script=$root/scripts/check_personal.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/personal-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

r=$work/repo
git init -q -b main "$r"
g() { git -C "$r" -c user.email=t@t -c user.name=t "$@"; }
printf 'Jane Roe wrote this once.\n' > "$r/old.txt"
g add -A && g commit -q -m base
export PERSONAL_DENYLIST=$'Jane\nRoe\njane.roe@example.com'

run() { (cd "$r" && "$script" "$@" 2>&1); }

printf 'hello world\n' > "$r/a.txt"; g add a.txt
out=$(run --staged) && report PASS "a clean staged change passes" || report FAIL "clean change failed: $out"

printf 'thanks, jane\n' > "$r/b.txt"; g add b.txt
if out=$(run --staged); then report FAIL "a staged personal name passed"; else report PASS "a staged personal name fails"; fi
case "$out" in *b.txt:1*) report PASS "the failure names the file and line" ;; *) report FAIL "no file:line in: $out" ;; esac
case "$out" in *[Jj]ane*) report FAIL "the output leaks the string: $out" ;; *) report PASS "the output never prints the string" ;; esac
g reset -q b.txt; rm "$r/b.txt"

printf 'see github.com/janeroe/repo\n' > "$r/c.txt"; g add c.txt
out=$(run --staged) && report PASS "a partial-word match passes" || report FAIL "partial word failed: $out"
g reset -q c.txt; rm "$r/c.txt"

printf 'mail jane.roe@example.com\n' > "$r/d.txt"; g add d.txt
if run --staged >/dev/null; then report FAIL "an email passed"; else report PASS "a denylisted email fails"; fi
g reset -q d.txt; rm "$r/d.txt"

g rm -q old.txt
out=$(run --staged) && report PASS "a removed line with the name passes" || report FAIL "removal failed: $out"
g reset -q HEAD old.txt; g checkout -q -- old.txt

g add a.txt && g commit -q -m clean
printf 'Roe was here\n' > "$r/e.txt"; g add e.txt && g commit -q -m leak
if run --range HEAD~2..HEAD >/dev/null; then report FAIL "a committed range with the name passed"; else report PASS "a commit range with the name fails"; fi
out=$(run --range HEAD~2..HEAD~1) && report PASS "a clean range passes" || report FAIL "clean range failed: $out"

out=$(unset PERSONAL_DENYLIST; cd "$r" && "$script" --staged 2>&1) && report PASS "no denylist: skipped, not failed" || report FAIL "no denylist failed: $out"
case "$out" in *skipped*) report PASS "the skip is said" ;; *) report FAIL "silent skip: $out" ;; esac

# --- each case below runs in its own throwaway repo -----------------------
DENY=$'Jane\nRoe\njane.roe@example.com'
fresh() { # $1 = name; sets r; base commit holds clean.txt
  r=$work/$1
  git init -q -b main "$r"
  printf 'plain text\n' > "$r/clean.txt"
  g add -A && g commit -q -m base
}
# rc, out (stdout+stderr), err (stderr only)
check() {
  rc=0
  out=$(cd "$r" && PERSONAL_DENYLIST="$DENY" "$script" "$@" 2>"$work/err") || rc=$?
  err=$(cat "$work/err")
  out="$out$err"
}
leaks() { printf '%s\n' "$out" | grep -qiE 'jane|roe|example\.com'; }

# usage errors
fresh usage
check; [ "$rc" -eq 64 ] && report PASS "no arguments is bad usage (exit 64)" || report FAIL "no arguments: exit $rc, want 64: $out"
check --range; [ "$rc" -eq 64 ] && report PASS "--range with no range is bad usage (exit 64)" || report FAIL "--range alone: exit $rc, want 64: $out"

# Git cannot read the change
fresh badrev
check --range deadbeef..HEAD
[ "$rc" -eq 2 ] && report PASS "an unknown revision in --range exits 2" || report FAIL "unknown revision: exit $rc, want 2: $out"
[ -n "$err" ] && report PASS "an unknown revision says so on stderr" || report FAIL "unknown revision: nothing on stderr"
[ "$rc" -ne 0 ] && report PASS "an unknown revision never passes" || report FAIL "unknown revision exited 0"
nogit=$work/not-a-repo; mkdir -p "$nogit"
rc=0; out=$(cd "$nogit" && PERSONAL_DENYLIST="$DENY" "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 2 ] && report PASS "--staged outside a git repository exits 2" || report FAIL "--staged outside a repo: exit $rc, want 2: $(printf '%s\n' "$out" | head -2)"

# A denylisted word in an added path
fresh path-add
mkdir -p "$r/docs"; printf 'nothing personal\n' > "$r/docs/jane-notes.txt"; g add -A
check --staged
[ "$rc" -eq 1 ] && report PASS "an added file whose path holds a denylisted word fails" || report FAIL "path hit: exit $rc, want 1: $out"
case "$out" in *docs/jane-notes.txt*) report PASS "the path hit names the path" ;; *) report FAIL "path hit: path not named: $out" ;; esac
g commit -q -m 'add notes'
check --range HEAD~1..HEAD
[ "$rc" -eq 1 ] && report PASS "--range: an added path with a denylisted word fails" || report FAIL "--range path hit: exit $rc, want 1: $out"

# A rename onto a denylisted path
fresh path-rename
g mv clean.txt Roe.txt
check --staged
[ "$rc" -eq 1 ] && report PASS "renaming a clean file onto a denylisted path fails" || report FAIL "rename hit: exit $rc, want 1: $out"
g commit -q -m rename
check --range HEAD~1..HEAD
[ "$rc" -eq 1 ] && report PASS "--range: a rename onto a denylisted path fails" || report FAIL "--range rename hit: exit $rc, want 1: $out"

# A denylisted word in a commit message
fresh message
printf 'more plain text\n' >> "$r/clean.txt"; g add -A; g commit -q -m 'thanks to Jane for this'
sha=$(g rev-parse HEAD)
check --range HEAD~1..HEAD
[ "$rc" -eq 1 ] && report PASS "--range: a commit message with a denylisted word fails" || report FAIL "message hit: exit $rc, want 1: $out"
case "$out" in *"${sha:0:7}"*) report PASS "the message hit names the commit's short sha" ;; *) report FAIL "message hit: no short sha ${sha:0:7}: $out" ;; esac
case "$out" in *thanks*) report FAIL "the message hit prints the message: $out" ;; *) report PASS "the message hit never prints the message" ;; esac

# An added line that itself starts with "++ "
fresh plusplus
printf '++ Jane was here\n' >> "$r/clean.txt"; g add -A
check --staged
[ "$rc" -eq 1 ] && report PASS "an added line starting with '++ ' holding a denylisted word fails" || report FAIL "'++ ' line: exit $rc, want 1: $out"
g commit -q -m pp
check --range HEAD~1..HEAD
[ "$rc" -eq 1 ] && report PASS "--range: an added line starting with '++ ' fails" || report FAIL "--range '++ ' line: exit $rc, want 1: $out"

# Entries with a trailing space or CR
fresh trailing
printf 'met Quill today\nand Marrow too\n' > "$r/t.txt"; g add -A
rc=0; out=$(cd "$r" && PERSONAL_DENYLIST=$'Quill ' "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "a denylist entry with a trailing space still matches" || report FAIL "trailing space: exit $rc, want 1: $out"
rc=0; out=$(cd "$r" && PERSONAL_DENYLIST=$'Marrow\r' "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "a denylist entry with a trailing CR still matches" || report FAIL "trailing CR: exit $rc, want 1: $out"
rc=0; out=$(cd "$r" && PERSONAL_DENYLIST=$'Nobody\r\nMarrow\r\n' "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "a CRLF denylist matches its entries" || report FAIL "CRLF list: exit $rc, want 1: $out"

# A hit in a path with a space
fresh spaced
mkdir -p "$r/my docs"; printf 'by Roe\n' > "$r/my docs/a b.txt"; g add -A
check --staged
[ "$rc" -eq 1 ] && report PASS "a hit in a path with a space fails" || report FAIL "spaced path: exit $rc, want 1: $out"
printf '%s\n' "$out" | grep -qF 'my docs/a b.txt:1' \
  && report PASS "a path with a space is reported whole, with its line, on one line" \
  || report FAIL "spaced path not reported whole: $out"

# An external diff driver does not hide added lines
fresh extdiff
printf 'signed, Jane\n' >> "$r/clean.txt"; g add -A
rc=0; out=$(cd "$r" && GIT_EXTERNAL_DIFF=true PERSONAL_DENYLIST="$DENY" "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "with GIT_EXTERNAL_DIFF set, a staged hit still fails" || report FAIL "external diff staged: exit $rc, want 1: $out"
g commit -q -m ext
rc=0; out=$(cd "$r" && GIT_EXTERNAL_DIFF=true PERSONAL_DENYLIST="$DENY" "$script" --range HEAD~1..HEAD 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "with GIT_EXTERNAL_DIFF set, a range hit still fails" || report FAIL "external diff range: exit $rc, want 1: $out"
fresh extdiff-cfg
g config diff.external true
printf 'signed, Jane\n' >> "$r/clean.txt"; g add -A
check --staged
[ "$rc" -eq 1 ] && report PASS "with diff.external configured, a staged hit still fails" || report FAIL "diff.external: exit $rc, want 1: $out"

# Line numbers, any case, clean, skipped, no leak
fresh lines
printf 'one\ntwo\nthree\n' > "$r/README.md"; g add -A; g commit -q -m readme
printf 'one\ntwo\nwritten by JANE here\nthree\n' > "$r/README.md"; g add -A
check --staged
[ "$rc" -eq 1 ] && report PASS "an upper-case name on an added line fails with exit 1" || report FAIL "upper case: exit $rc, want 1: $out"
printf '%s\n' "$out" | grep -qE '(^|[^[:alnum:]_./-])README\.md:3([^0-9]|$)' \
  && report PASS "the hit names README.md:3" || report FAIL "no README.md:3: $out"
leaks && report FAIL "the upper-case hit leaks the string: $out" || report PASS "the upper-case hit never prints the string"
g reset -q --hard
printf 'mail Jane.Roe@Example.COM\n' >> "$r/README.md"; g add -A; g commit -q -m mail
check --range HEAD~1..HEAD
[ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -qE 'README\.md:4([^0-9]|$)' && ! leaks \
  && report PASS "--range: a mixed-case email fails with README.md:4 and no string" \
  || report FAIL "--range mixed-case email: exit $rc: $out"

fresh clean-pin
printf 'ordinary words, janet and roebuck\n' >> "$r/clean.txt"; g add -A
check --staged
[ "$rc" -eq 0 ] && report PASS "a clean change exits 0" || report FAIL "clean change: exit $rc, want 0: $out"
leaks && report FAIL "a clean change prints a denylisted string: $out" || report PASS "a clean change prints no denylisted string"

fresh skipped-pin
printf 'by Jane Roe\n' >> "$r/clean.txt"; g add -A
rc=0; out=$(cd "$r" && env -u PERSONAL_DENYLIST "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 0 ] && report PASS "no denylist in a repo without local/: exit 0" || report FAIL "no denylist: exit $rc, want 0: $out"
case "$out" in *skipped*) report PASS "no denylist prints the skipped line" ;; *) report FAIL "no skipped line: $out" ;; esac
rc=0; out=$(cd "$r" && PERSONAL_DENYLIST="" "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 0 ] && case "$out" in *skipped*) true ;; *) false ;; esac \
  && report PASS "an empty PERSONAL_DENYLIST counts as no denylist (0, skipped)" \
  || report FAIL "empty PERSONAL_DENYLIST: exit $rc: $out"

# A non-UTF-8 byte beside the word, under each locale
fresh latin1
printf 'Zorblat caf\xe9\n' > "$r/menu.txt"; g add -A
for loc in default C C.UTF-8 en_US.UTF-8; do
  rc=0
  if [ "$loc" = default ]; then
    out=$(cd "$r" && PERSONAL_DENYLIST=Zorblat "$script" --staged 2>&1) || rc=$?
  else
    out=$(cd "$r" && export LC_ALL=$loc && PERSONAL_DENYLIST=Zorblat "$script" --staged 2>&1) || rc=$?
  fi
  [ "$rc" -eq 1 ] && report PASS "a hit beside a non-UTF-8 byte fails with exit 1 ($loc locale)" \
    || report FAIL "non-UTF-8 hit ($loc): exit $rc, want 1: $out"
  printf '%s\n' "$out" | grep -qE 'menu\.txt:1([^0-9]|$)' \
    && report PASS "a hit beside a non-UTF-8 byte names menu.txt:1 ($loc locale)" \
    || report FAIL "non-UTF-8 hit ($loc): no menu.txt:1: $out"
  printf '%s\n' "$out" | grep -qi zorblat \
    && report FAIL "non-UTF-8 hit ($loc) leaks the string: $out" \
    || report PASS "a hit beside a non-UTF-8 byte never prints the string ($loc locale)"
done
g commit -q -m latin1
rc=0; out=$(cd "$r" && export LC_ALL=en_US.UTF-8 && PERSONAL_DENYLIST=Zorblat "$script" --range HEAD~1..HEAD 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "--range: a hit beside a non-UTF-8 byte fails with exit 1 (UTF-8 locale)" \
  || report FAIL "--range non-UTF-8 hit: exit $rc, want 1: $out"

# A .gitattributes `-diff` does not hide added lines
fresh nodiff
printf '*.txt -diff\n' > "$r/.gitattributes"; printf 'from Zorblat\n' > "$r/secret.txt"; g add -A
rc=0; out=$(cd "$r" && PERSONAL_DENYLIST=Zorblat "$script" --staged 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "a .txt hit under a new '*.txt -diff' .gitattributes fails" \
  || report FAIL "-diff attribute staged: exit $rc, want 1: $out"
g commit -q -m nodiff
rc=0; out=$(cd "$r" && PERSONAL_DENYLIST=Zorblat "$script" --range HEAD~1..HEAD 2>&1) || rc=$?
[ "$rc" -eq 1 ] && report PASS "--range: a .txt hit under a new '*.txt -diff' .gitattributes fails" \
  || report FAIL "-diff attribute range: exit $rc, want 1: $out"

finish
