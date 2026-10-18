# Implementation status and verification boundary

The implementation is a locally testable application with a Next.js frontend
connected to the persistent FastAPI backend. It has not been deployed to a live
Supabase/Railway/Vercel environment. Initial
`FEATURE_MODE=SHADOW` keeps advanced proposals read-only while the original
baseline owns live decisions.

| Blueprint phases | Implemented backend scope |
| --- | --- |
| P0–P1 | FastAPI, strict environments, Supabase JWT validation, PostgreSQL models/migrations, candidate/profile/skills/availability, pending and independently verified organizations, team invitations and vacancy ACLs, versioned job requirements |
| P2–P3 | Both first-mover directions, exact double opt-in, global candidate/per-vacancy ceilings, waiting/cooldown/expiry, transaction locks, encrypted durable idempotency, exposure audit, matches and participant messaging |
| P4 | Exact role/version/stage policies, recent signatory authentication, independent evidence attestations, scoped document/summary grants, candidate terms, revocation and live short-lived readiness proofs, optional-requirement clarification, exclusive holds |
| P5–P6 | Immutable shadow snapshots, baseline parity/isolation tests, original reciprocal formulas, persistent attention/congestion dual controllers, correlated scenario risk, global sparse allocation/exchanges/pruning, minimum shortlist math, WITNESS dependencies/budgets and adaptive exposure |
| P7 | Fictional resettable market, OpenAPI and generated types, connected Next.js workspace pages, server-side Supabase session handling, scoped BFF reads and versioned actions |
| P8 | Durable worker/retries/dead letters/receipts, in-app notifications/reminders, interviews, encrypted written offers, separate corroborated starts/disputes, privacy export/deletion and moderation/report workflow |
| P9 | Advanced live execution intentionally refuses pilot approval. External prospective evidence, employer/candidate enrollment, independent governance and deployment approval are required before this can be enabled |
| P10 | CI, dependency/source checks, migration round trips, browser-role RLS denial, immutable audit triggers, Railway/Compose configuration and backup/restore runbooks; actual cloud load/security review and restore drill remain external deployment work |

## Limits that are deliberate or need external configuration

- `CANNOT_CERTIFY` is the production reliability status. No model has been trained
  or prospectively validated on employment starts. Synthetic tests do not establish
  hiring performance, legal suitability, fairness or real-world probabilities.
- Supabase JWT/storage adapters are implemented; local tests use provider fixtures
  and loopback-only fictional JWTs. Real provider credentials and sign-in flows
  have not been exercised. Real organization/evidence/start verification requires
  an independently authorized operator with actual corroboration.
- Binary resume/evidence uploads fail closed unless a real ClamAV scanner is
  available. Parsing produces an untrusted draft and requires candidate confirmation;
  there is no OCR service or automatic credential inference.
- In-app notifications and persisted interview scheduling work locally. External
  email, connected calendars, payment checkout and billing webhooks are not
  configured. Invitations explicitly report manual delivery; no request returns
  fake provider delivery or checkout success. Ranking cannot read billing data.
- Deletion immediately removes access and schedules local minimization. Minimal
  identity tombstones and immutable security/process references are retained.
  Supabase Auth deletion, remote object inventory, backups and applicable retention
  obligations require provider/operator review; the final job records that state.
- No real third-party profile scraping, JTH dataset, protected-attribute store,
  background checks or opaque global employability score is included.
- The existing frontend uses live backend state. Production Supabase confirmation,
  cookie refresh and hosted deployment checks still need configured environments.
- Git was initialized locally. No remote repository, push, cloud deployment or
  production credential was invented or created.

## Executed verification

Verification was executed locally on 17 October 2026 with Python 3.12 and
PostgreSQL 17.11. Tests use actual PostgreSQL, including isolated schemas,
competing sessions, version races, duplicate decisions, tenant negatives and
consent revocation.

- Backend regression before frontend integration: **185 passed**, one upstream TestClient deprecation
  warning, **85% measured application coverage**, in 270.07 seconds. Command:
  `python -m pytest -q --cov=app --cov-report=term:skip-covered`.
- Migration upgrades, populated backfill, downgrade and clean upgrade passed.
  Browser roles were denied application rows; restricted backend-role operations,
  immutable audit/exposure/stage triggers and all 44 application-table RLS checks
  passed. The read-only schema release check recognized the current head.
- Ruff formatting/lint and mypy on both Windows and Linux targets passed; mypy
  checked 67 files. OpenAPI consistency and source secret scans passed.
- Generated TypeScript contracts, strict type checking and all six client runtime
  tests passed. Python and npm dependency audits reported no known advisories
  against the installed locked dependencies at check time.
- A wheel built successfully and was inspected for runtime modules, shadow routing
  and exclusion of secrets, local databases and private attachments.
- A real local `pg_dump`/`pg_restore` drill restored the fictional demo into a
  disposable database and verified row counts, migration head, RLS and triggers.
- A freshly reset fictional demo passed the real HTTP smoke: health/readiness
  200, 96 issued cards, candidate usage 3 of cap 3, two independent decisions
  creating one mutual match, message 200 and unrelated-user 403. The consumed
  fixture is explicit; repeat instructions are in [demo.md](demo.md).
- The running API accepted a replan with HTTP 202 and returned its durable outbox
  event ID. The separate running worker consumed it and recorded a `ShadowRun`
  with zero planner side effects.
- After frontend integration, the complete backend suite passed **226 tests**.
  The final targeted contract, authorization and workflow run passed **27 tests**,
  including viewer-specific interview permissions and persisted start reports.
- The backend CI isolation regression run passed **229 tests** with migrated
  `public` tables present. Each fixture owns all 44 tables in its private schema
  and excludes `public` from its search path. CI coverage selects `apps/api/app`
  explicitly to avoid the frontend's root `app` directory.
- The connected frontend passed **28 gateway tests**, strict TypeScript checking
  and a production build. All **six** generated-client runtime tests also passed.
- A real HTTP frontend-to-PostgreSQL smoke passed sign-in, HttpOnly session
  handling, profile save/reload/restore, exact retries, stale-version rejection,
  tenant-scoped employer reads, CSRF rejection and session revocation/logout.
  Browser checks confirmed candidate profile persistence and the employer
  workspace at the standard local app port. These used explicit fictional local
  accounts; live Supabase authentication and external delivery were not tested.

GitHub-hosted CI has been exercised; current check outcomes and CI fixes are
recorded on the [repository pull requests](https://github.com/LinusJo261/CareerKitchen/pulls).
Docker image execution and hosted Supabase/Railway end-to-end checks have not
been run. Local and CI verification do not establish cloud availability or
hiring-model reliability.

## Career Chef check repairs

Backend test fixtures create every application table in their own schema and
exclude migrated `public` tables from the search path. Fixture teardown also runs
when setup fails. CI coverage selects `apps/api/app` explicitly. OpenAPI error
descriptions for HTTP 413 and 422 use fixed phrases across Python versions, with
a regression test that simulates the legacy standard-library phrases.

Local Python 3.12 verification passed **321 backend tests** against PostgreSQL
with all 44 migrated application tables present in `public`. A disposable database
also passed the populated migration upgrade, downgrade, clean upgrade and
authorization checks. Ruff format/lint, OpenAPI consistency, generated-client
consistency, client TypeScript checking, six client tests and the source secret
scan passed. The recovered local environment lacks mypy and pytest-cov; those
checks require the locked CI environment. No live Gemini call was made for this
repair, and hosted check results must be read from the pull request.

## Career Chef integration merge

The PR #11 merge resolution retains authenticated, persistent workspace actions
alongside Career Chef's layout, navigation and accessibility improvements. The
assistant reuses the workspace's HttpOnly session on the server while preserving
explicit Gemini consent. Public guidance now describes the connected application.

The frontend build excludes the independently installed API client from its root
TypeScript project; CI checks that package separately. The privacy regression
suite now exercises connected employer state and rendered cards instead of the
retired demo allocator, and both navigation/privacy script suites run in CI.

On 18 October 2026, the production build, strict frontend typing, **58 frontend
tests**, generated OpenAPI/client consistency, client typing and **six client
tests** passed locally. PostgreSQL migration round trips, RLS/authorization
validation, Ruff formatting/lint and mypy also passed. These checks do not exercise
live Supabase sessions or paid Gemini generation.
