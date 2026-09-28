-- One-time RDS setup, run as the master user (db_master_username, the schema
-- owner) before the first `alembic upgrade head`: the RLS migration grants to
-- hax_app and fails if the role does not exist. Mirrors
-- infra/compose/postgres/init.sql; the app password arrives as the psql
-- variable app_password (`-v app_password='...'`), never in this file.
-- Re-running is harmless: every statement is idempotent, and the password
-- given on the command line always wins (a re-run rotates it).

CREATE EXTENSION IF NOT EXISTS vector;

-- The runtime role. The master user must not be the app's connection: RDS
-- masters hold rds_superuser and would bypass row-level security.
SELECT format(
  'CREATE ROLE hax_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'app_password'
) WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hax_app') \gexec
SELECT format('ALTER ROLE hax_app WITH PASSWORD %L', :'app_password') \gexec

GRANT USAGE ON SCHEMA public TO hax_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hax_app;
-- Tables created by future migrations (run as the master user) get the same
-- grants. The role name here is db_master_username; change both together.
ALTER DEFAULT PRIVILEGES FOR ROLE hax IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hax_app;

-- Verification: hax_app present without superuser/bypassrls; vector installed.
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'hax_app';
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
