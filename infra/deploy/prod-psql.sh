#!/usr/bin/env bash
# Interactive read-only psql against production RDS, from a laptop.
#
# RDS is reachable only from the box, so this opens an SSM session that runs
# one script there, as ubuntu:
#   1. connect as hax_readonly with the URL in /opt/hax/ops.env;
#   2. if that fails (first run, or the role is gone after a restore): create
#      or repair the role as the master user (MIGRATIONS_DATABASE_URL in
#      /opt/hax/.env) with a password generated on the box, and rewrite
#      ops.env;
#   3. open psql in a throwaway postgres:16 container as hax_readonly.
# Idempotent: every later run skips step 2. No credential leaves the box or
# is typed; quitting psql (\q) removes the container and ends the session.
#
# hax_readonly: SELECT only (grants, not a session setting a user could turn
# off), BYPASSRLS because every user table is FORCE ROW LEVEL SECURITY.
# ops.env, not .env: every container loads .env (compose env_file), the web
# included, and this credential reads every user's rows.
#
# Needs the AWS CLI + Session Manager plugin and credentials for this
# account. HAX_INSTANCE_ID (default: terraform output), AWS_REGION (default
# us-east-1).
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}
INSTANCE=${HAX_INSTANCE_ID:-$(terraform -chdir=infra/terraform output -raw instance_id)}

read -r -d '' remote <<'BOX' || true
set -euo pipefail
ops=/opt/hax/ops.env
# Extracted, not sourced: env-file values are not shell-quoted.
get() { grep -E "^$1=" "$2" 2>/dev/null | cut -d= -f2- || true; }
pg() { docker run --rm -i postgres:16 psql -X -q -v ON_ERROR_STOP=1 "$@"; }

ro=$(get OPS_DATABASE_URL "$ops")
if [ -z "$ro" ] || ! pg "$ro" -tAc 'SELECT 1' </dev/null >/dev/null 2>&1; then
  echo "prod-psql: setting up hax_readonly" >&2
  owner=$(get MIGRATIONS_DATABASE_URL /opt/hax/.env)
  [ -n "$owner" ] || { echo "MIGRATIONS_DATABASE_URL is not set in /opt/hax/.env" >&2; exit 1; }
  # Hex: no character needs escaping in a URL.
  pw=$(openssl rand -hex 24)
  pg "$owner" -v ro_password="$pw" <<'SQL'
SELECT format(
  'CREATE ROLE hax_readonly LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS',
  :'ro_password'
) WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hax_readonly') \gexec
SELECT format('ALTER ROLE hax_readonly WITH PASSWORD %L BYPASSRLS', :'ro_password') \gexec
ALTER ROLE hax_readonly SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE hax TO hax_readonly;
GRANT USAGE ON SCHEMA public TO hax_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO hax_readonly;
-- Run as the master user, who also runs the migrations, so tables from
-- future migrations are readable too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO hax_readonly;
SQL
  # Same host, port, database and options as the owner URL; only the user
  # and password differ.
  ro="postgresql://hax_readonly:${pw}@${owner#*@}"
  install -m 600 /dev/null "$ops"
  printf 'OPS_DATABASE_URL=%s\n' "$ro" > "$ops"
  pg "$ro" -tAc 'SELECT 1' </dev/null >/dev/null || { echo "hax_readonly still cannot connect" >&2; exit 1; }
fi
exec docker run --rm -it postgres:16 psql "$ro"
BOX

# Base64 keeps the script intact through SSM parameter quoting; bash -c (not
# a pipe into bash) leaves the session terminal on stdin for psql. sudo -u,
# not -iu: -i hands the command to ubuntu's login shell, which re-parses it,
# expanding every $var and joining the lines.
encoded=$(printf '%s' "$remote" | base64 | tr -d '\n')
params="{\"command\":[\"sudo -u ubuntu bash -c \\\"\$(echo $encoded | base64 -d)\\\"\"]}"

exec aws ssm start-session --region "$REGION" --target "$INSTANCE" \
  --document-name AWS-StartInteractiveCommand --parameters "$params"
