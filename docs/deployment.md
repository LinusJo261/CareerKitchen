# Deployment and operations

The backend uses FastAPI, PostgreSQL, Supabase Auth, private Supabase Storage, and a
PostgreSQL transactional outbox. API and worker are separate persistent Railway
services built from the same image. No production service has been provisioned by
this repository, and no remote credentials have been supplied or tested.

## Local development

Create a Python 3.12 virtual environment, then run `pip install -e '.[dev]'`.
Copy `.env.example` to `.env` and replace placeholders. The application rejects SQLite:
integration and concurrency tests depend on real PostgreSQL row/advisory locks.
For Docker, set `LOCAL_DATABASE_PASSWORD`, run `docker compose up -d postgres`,
then `alembic upgrade head`. Start `uvicorn app.main:app --host 127.0.0.1 --port 8000`
and `python -m app.workers.runner` in separate terminals. Do not expose local demo
authentication to the network.

The complete Compose API/worker setup should use real Supabase authentication;
Docker bridge requests do not meet the loopback-only development-token policy.
For fictional development tokens, run only Compose PostgreSQL and run the API
natively bound to `127.0.0.1` as above. Run migrations before starting the API or
worker; their startup commands do not create tables implicitly.

An ignored `.env` and `.local/` PostgreSQL runtime may exist in the implementation
workspace for credential-free verification. They are machine-local, contain random
development secrets, and are excluded from Git and Docker build contexts. The
portable Windows server binds only `127.0.0.1:55432`; stop it with
`.local\postgresql\pgsql\bin\pg_ctl.exe -D .local/postgres-data -m fast -w stop`.

## Supabase

1. Create a separate Supabase project for each environment. Configure asymmetric
   ES256 or RS256 JWT signing keys, confirmed email, appropriate session lifetime,
   provider credentials, and permitted Vercel redirect URLs.
2. Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and server-only
   `SUPABASE_SERVICE_ROLE_KEY`. Never send service secrets to the frontend.
3. Use the direct PostgreSQL endpoint or session pooler URL with
   `DATABASE_URL=postgresql+psycopg://...?...&sslmode=require`; prefer `verify-full`
   with the project's CA where available. Use a separate migration owner role and
   restricted runtime role, configured as described below. Transaction poolers require explicit compatibility
   review because allocation uses transaction-scoped advisory locks.
4. Create a **private** bucket named `career-kitchen-private` (or `STORAGE_BUCKET`).
   Store only application-encrypted data. Do not add public read or unrestricted
   browser upload policies. The API owns upload, validation, consent checks,
   decryption, and download; this prevents unrevocable bearer URLs bypassing current
   disclosure permission. Bucket limits should match `MAX_RESUME_BYTES` plus Fernet
   overhead (at least 7 MB for the default 5 MB plaintext limit) and permit
   `application/octet-stream`.
5. Apply the backend migrations to its application tables (currently in `public`);
   the migrations enable default-deny RLS and revoke browser-role access. Keep application
   tables inaccessible to Supabase anonymous/authenticated API roles unless an
   explicit audited RLS policy is introduced. The API performs tenant checks.

## Database owner and runtime roles

Run migrations in a separately credentialed release job using the table-owner
PostgreSQL URL. `MIGRATION_DATABASE_URL` is accepted by Alembic for that job; the
API and worker **must not receive it**. A direct environment owner URL lets the
migration command run without Supabase Auth/Storage or application encryption
secrets. Production/staging migration connections must enforce TLS. Never run
migration downgrades automatically during a production rollout.

After `alembic upgrade head`, execute `infra/postgres/runtime-role.sql` with the
owner/role administrator using `psql --single-transaction -v ON_ERROR_STOP=1 -f
infra/postgres/runtime-role.sql` against the intended database. It creates a
NOLOGIN, non-superuser, NOBYPASSRLS group named `career_kitchen_backend` and uses
an exact allowlist of 44 public application tables. It grants normal application
DML, with **SELECT/INSERT only** on audit, exposure, and stage history. It grants
read-only access to `alembic_version`. It grants no permanent-schema DDL,
TRUNCATE, table-ownership, default-table privileges, or auth/storage/compliance
schema access. PostgreSQL's database TEMP privilege is a separate database policy.

The SQL creates explicit RLS policies **only for this trusted backend group**.
These are service-tier policies; tenant and personal authorization still happen
inside FastAPI and are tested separately. They are not per-user tenant RLS.
Anonymous/authenticated Supabase browser roles retain no access. The script
refuses unsafe existing group attributes, inherited ownership/CREATE privileges,
or browser membership in the backend group. Adding a new table requires a reviewed
allowlist/policy update; no blanket default privileges are installed.

Create a distinct LOGIN role through the managed secret flow, grant it
`career_kitchen_backend`, and put only its URL in API/worker `DATABASE_URL`. Keep it
out of table-owner and BYPASSRLS roles. Supply the login password with an interactive
`psql` password command or managed secret mechanism rather than source or shell
history. Re-run the role SQL after reviewed schema changes. `python -m
app.check_schema` is a read-only release gate and works with this runtime role.

`scripts/validate_migrations.py` verifies the exact SQL on a temporary local
PostgreSQL database using SET ROLE: backend reads/writes succeed, event mutation,
permanent DDL, TRUNCATE, version tampering, and private-schema reads are denied,
and a browser probe with a SELECT grant still sees zero rows under RLS. The
validation owner needs CREATEDB and CREATEROLE; it drops the temporary database and
only test-created roles after verification.

## Railway

Set `ENVIRONMENT=production`, `AUTH_MODE=supabase`, `ALLOW_DEV_AUTH=false`,
`STORAGE_BACKEND=supabase`, `FEATURE_MODE=LIVE`, and all keys from
`.env.example`. Apply migration `0006_matching_learning` and the reviewed runtime
role allowlist before starting this release. Live deterministic attention
allocation uses the transactional executor; learned scoring requires qualified
observed outcomes and explicit registry activation. `MATCHING_MODEL_MAX_AGE_DAYS`
defaults to 90; expired or invalid models use deterministic scoring. SHADOW
additionally records read-only scenario diagnostics. Set `CORS_ORIGINS` to exact HTTPS Vercel frontend origins and
`TRUSTED_HOSTS` to API domain names **and `healthcheck.railway.app`**; Railway sends
deployment probes with that Host value. Wildcards are rejected. Generate independent
Fernet encryption, audit HMAC, and private readiness secrets. Keep encryption keys
in a managed secret store with a tested recovery/rotation procedure. Existing
encrypted data must be re-encrypted before retiring an old encryption key.

The current Railway configuration is `.railway/railway.ts`. Install its SDK with
`npm install --prefix .railway`, link the intended project/environment using the
Railway CLI, and inspect `railway config plan` before applying infrastructure.
The source repository/image must be connected separately; the root Dockerfile is
auto-detected. Secrets remain environment configuration. The configuration declares
API and worker services; it provisions no duplicate database or Supabase services.
The API runs the read-only `python -m app.check_schema` as a predeploy command;
the separate owner release job must finish migrations and runtime grants first.
The worker uses the same
image and `python -m app.workers.runner`, without an HTTP healthcheck. Run migrations
once from the owner release job and use backward-compatible migrations for rolling
releases. The worker must never run against preview data with production credentials.

Railway deprecated root `railway.json`/`railway.toml` for new services. A legacy
single-service example is retained under `infra/deploy/railway.legacy.json` as a
reference only. See [Railway's current IaC guide](https://docs.railway.com/infrastructure-as-code).

`/v1/health` reports process liveness. Keep database/schema readiness private with
`READINESS_TOKEN`. Alert on outbox age, repeated failures, dead letters, lock
timeouts, capacity-invariant violations, and unauthorized-access rates. Do not log
Authorization headers, request bodies, resume contents, signed URLs, or secrets.

Binary PDF/DOCX resume uploads require a maintained ClamAV service configured with
`CLAMAV_HOST`/`CLAMAV_PORT`; unavailable scans fail closed. The parser never executes
document text or retrieves URLs. Strict UTF-8 plaintext resumes work locally.
After a successful malware scan, PDF/DOCX text extraction runs in a separate
credential-free Python child with input/output, wall-time, CPU, page, decompression,
and memory bounds. Windows uses a Job Object; POSIX uses resource limits. Python
audit hooks reject network/process APIs, but this is not a full OS network sandbox.
The resulting text is a proposed draft for candidate confirmation. Image-only
PDFs have no OCR; limits, unsupported content, or unavailable process controls
produce `MANUAL_ENTRY_REQUIRED` without a fabricated extraction result.

In-app notification records, interview scheduling records, and billing capacity
records are persistent. Outbound email, provider calendar synchronization, and
payment checkout/webhooks need separately configured provider adapters; the current
backend reports their unconfigured state and does not claim delivery or payment.
Railway's deployment probe is not continuous monitoring; configure an external
uptime check and queue-lag alerts separately.

## Backups, rollout, and recovery

Enable Supabase backups/PITR and object lifecycle retention, and rehearse restores
to an isolated project. Back up encryption keys separately from encrypted data.
Stage migration up/down and integration tests before production. Railway deploy
and GitHub credentials are external setup steps; no workflow pretends a deployment
succeeded. Pause allocation on invariant alerts, preserve audit events, repair
through reviewed migrations or versioned administrative transitions, and replay
the durable outbox after recovery. Provider outages return temporary failures;
they never switch to permissive authentication or in-memory decision state.

The repository's local `scripts/restore_demo_check.py` drill restores a real
PostgreSQL dump into a separate database and verifies fictional data counts,
migration revision, RLS, and immutable-history triggers. This verifies the local
backup/restore path; Supabase-managed backup/PITR and disaster recovery still need
their own live deployment restore drill.

## External API references

- [Supabase JWT validation](https://supabase.com/docs/guides/auth/jwts)
- [Signing keys and cache/rotation behavior](https://supabase.com/docs/guides/auth/signing-keys)
- [Private Storage access control](https://supabase.com/docs/guides/storage/security/access-control)
- [Storage uploads](https://supabase.com/docs/reference/python/storage-from-upload)
- [Railway IaC reference](https://docs.railway.com/infrastructure-as-code/reference)
- [Railway healthcheck host and monitoring behavior](https://docs.railway.com/deployments/healthchecks)


