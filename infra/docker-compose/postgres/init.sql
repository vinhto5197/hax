CREATE EXTENSION IF NOT EXISTS vector;

-- Runtime role for the app (least privilege). The bootstrap user `hax` is a
-- container superuser and superusers BYPASS row-level security entirely — so
-- the app must NOT connect as it or slice 2's RLS is decorative in dev. `hax`
-- stays the owner: Alembic migrations run as it (DDL needs ownership).
-- Mirrors prod (M3): RDS gives no superuser; app role ≠ master role there too.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hax_app') THEN
    CREATE ROLE hax_app LOGIN PASSWORD 'hax_app'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO hax_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hax_app;
-- Tables created by future migrations (run as hax) get the same grants.
ALTER DEFAULT PRIVILEGES FOR ROLE hax IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hax_app;
