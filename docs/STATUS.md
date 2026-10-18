# Implementation status and verification boundary

The implementation is a locally testable, persistent backend. It has not been
deployed to a live Supabase/Railway environment or connected to the unavailable v0
frontend source. The source ZIP was a specification, not an existing application. Initial
`FEATURE_MODE=SHADOW` keeps advanced proposals read-only while the original
baseline owns live decisions.

| Blueprint phases | Implemented backend scope |
| --- | --- |
| P0–P1 | FastAPI, strict environments, Supabase JWT validation, PostgreSQL models/migrations, candidate/profile/skills/availability, pending and independently verified organizations, team invitations and vacancy ACLs, versioned job requirements |
| P2–P3 | Both first-mover directions, exact double opt-in, global candidate/per-vacancy ceilings, waiting/cooldown/expiry, transaction locks, encrypted durable idempotency, exposure audit, matches and participant messaging |
| P4 | Exact role/version/stage policies, recent signatory authentication, independent evidence attestations, scoped document/summary grants, candidate terms, revocation and live short-lived readiness proofs, optional-requirement clarification, exclusive holds |
| P5–P6 | Immutable shadow snapshots, baseline parity/isolation tests, original reciprocal formulas, persistent attention/congestion dual controllers, correlated scenario risk, global sparse allocation/exchanges/pruning, minimum shortlist math, WITNESS dependencies/budgets and adaptive exposure |
| P7 | Fictional resettable market, OpenAPI and generated typed client, documented v0 authentication/workflow integration; frontend work excluded by user request |
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
- The TypeScript client and contracts are ready for the actual v0 source. Connecting
  its pages, buttons and forms requires that source and configured environments.
- Git was initialized locally. No remote repository, push, cloud deployment or
  production credential was invented or created.

## Executed verification

Verification was executed locally on 17 October 2026 with Python 3.12 and
PostgreSQL 17.11. Tests use actual PostgreSQL, including isolated schemas,
competing sessions, version races, duplicate decisions, tenant negatives and
consent revocation.

- Final full regression: **185 passed**, one upstream TestClient deprecation
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

GitHub-hosted CI has been exercised; current check outcomes and CI fixes are
recorded on the [repository pull requests](https://github.com/LinusJo261/CareerKitchen/pulls).
Docker image execution and hosted Supabase/Railway end-to-end checks have not
been run. Local and CI verification do not establish cloud availability or
hiring-model reliability.
