# Migration safety

Run `alembic upgrade head` with the migration-owner PostgreSQL URL in a separate
release job. Alembic accepts `MIGRATION_DATABASE_URL`; never pass that owner secret
to API or worker containers. The API and
worker never call `create_all()` at startup. `scripts/validate_migrations.py`
creates a random temporary database, tests upgrade/downgrade/upgrade, RLS presence,
and database-enforced append-only audit history, then drops only that database.
It requires local database creation privileges and never downgrades the configured
application database.

Revision `0002_security_isolation` enables default-deny RLS and revokes anonymous,
authenticated, and PUBLIC access on application tables. The backend table owner
continues to have access through PostgreSQL owner semantics. For a separate
non-owner runtime login, run the exact allowlist grants/policies in
`infra/postgres/runtime-role.sql` after migrations and grant its NOLOGIN backend
group to a distinct managed runtime login. Do not grant these to Supabase browser roles.
Keep migration ownership separate from runtime credentials in production.

Every new table migration must include equivalent RLS and privilege restrictions.
Every event-history table must enforce its immutability in PostgreSQL as well as
ORM code. Never implement a migration by importing current model metadata: an
old revision must stay stable after later code changes.

