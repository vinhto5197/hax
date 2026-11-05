# Sourced by the shell tests beside it, never run on its own: one PASS/FAIL
# line per check, and `finish` turns the count into the exit status.
fails=0

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

finish() {
  [ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
}
