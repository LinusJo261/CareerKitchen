# Career Kitchen

Next.js frontend connected to the persistent FastAPI backend. Workspace pages use
authenticated server routes and PostgreSQL state rather than in-memory demo data.
Career Chef adds public onboarding guides and an optional, consent-based Gemini
conversation through the server-side API bridge.

The API implements candidate/employer onboarding, organization verification and
team ACLs, versioned vacancies and requirements, reciprocal decision cards,
double opt-in, bounded attention, waiting/expiry/replenishment, PACT, scoped
evidence disclosure and revocation, chat and private attachments, interviews,
offers, independently attested starts, notifications, abuse reports, and privacy
jobs. PostgreSQL owns state, transactions, locks, idempotency, audit and the durable
worker queue. Supabase provides production identity and private storage.

Live matching optimizes reciprocal compatibility across both participants' actual
attention limits. `FEATURE_MODE=LIVE` is the default; the transactional executor
rechecks consent, eligibility, versions and capacity. Optional machine learning
uses explicitly consented, frozen outcomes and requires held-out improvement
before activation. No observed model has been trained yet. R99, WITNESS and
scenario research remain read-only and cannot certify employment reliability.
See [matching verification](docs/live-matching-verification.md) and
[outcome learning](docs/matching-learning.md).

Start with [implementation status](docs/STATUS.md), [v0 integration](docs/v0-integration.md),
[API contracts](docs/api.md), and [deployment](docs/deployment.md). The complete
archived blueprint is not present in this checkout.

## Test Career Chef

Career Chef answers navigation questions using Gemini at `POST /v1/navigation/chat`.
The Next.js website includes a floating **Career Chef** assistant and a standalone
test page at `http://127.0.0.1:3000/career-chef`. See [website and API testing](docs/career-chef-testing.md).
Test API messages separately in Swagger at `http://127.0.0.1:8000/docs`;
the answer appears in `data.reply`. The [API walkthrough](docs/navigation-chat.md)
covers PostgreSQL setup, safe local authentication, Gemini configuration and errors.
Opening Swagger alone does not verify that those dependencies are ready.

## Run locally

Python 3.12 and PostgreSQL 17 are the tested runtime. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[dev]"
Copy-Item .env.example .env
# Replace placeholders; select Supabase or explicitly enable loopback development auth.
docker compose up -d postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the persistent worker in another terminal:

```powershell
.\.venv\Scripts\python.exe -m app.workers.runner
```

An ignored `.venv`, `.env` or local PostgreSQL runtime may exist on an individual
machine; these are not included in the checkout. Fresh machines can use Compose
PostgreSQL with the native loopback API; see the deployment guide for container
authentication and production configuration. `python -m scripts.local_dev init`
can create explicit fictional local auth configuration without overwriting `.env`.

Interactive API reference: [local Swagger UI](http://127.0.0.1:8000/docs).
Liveness: `/v1/health`; readiness: `/v1/ready`. Hosted readiness requires a private
credential. Production authentication validates Supabase signatures, issuer,
audience, expiry, session identity and provider-confirmed email; all application
roles and vacancy permissions are resolved from PostgreSQL.

## Run the connected frontend

Install the root dependencies with `pnpm install --frozen-lockfile`, then run
`pnpm dev` and open [Career Kitchen](http://localhost:3000). Configure
`CAREER_KITCHEN_API_URL` in the server environment; Supabase sign-in uses the
existing `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. Session credentials remain
in HttpOnly cookies. Database and service-role credentials never enter browser code.

For the existing local fictional market, set `FRONTEND_LOCAL_DEMO=true` in the
ignored `.env` alongside the explicit development/local-auth settings. Start
`python -m scripts.serve_demo` and `python -m scripts.serve_demo --worker` in
separate terminals. The sign-in page then offers fictional candidate/employer
accounts backed by `career_kitchen_demo`; it does not create real Supabase users.
This account selector is disabled in production and on non-loopback hostnames.
Do not reset an existing demo database just to reconnect the frontend.

Profiles, decision cards, mutual matches, messages, interviews, offers,
organization/team administration, PACT, consent, notifications and privacy jobs
use backend endpoints. Authority checks, double opt-in, attention ceilings,
versions and idempotency remain enforced by FastAPI. Independently verified
employment, external mail/calendar delivery and model certification are never
inferred from a button click.

Frontend checks: `pnpm typecheck`, `pnpm test`, and `pnpm build`.
With the local app and fictional API running, `pnpm smoke:frontend` checks real
HTTP sign-in, persistent save/restore, exact retry, stale versions, scoped reads,
CSRF and logout. It temporarily edits and restores candidate-30's fictional
summary; it never resets the database. See [integration details](docs/v0-integration.md).

## Fictional development market

For 20,000 synthetic applicant profiles and 20,000 draft jobs from a pinned MIT
dataset, see [large sample market](docs/sample-data.md). That importer uses its
own local PostgreSQL database and preserves the small demo below.

The homepage **Demo mode** button opens the same UI against that large market.
Run `python -m scripts.prepare_sample_demo` once, then `python -m scripts.serve_samples`
alongside the frontend with `FRONTEND_LOCAL_DEMO=true`. The demo banner supports
candidate/employer switching, real matching runs, catalogue search and exit.
All activity stays in the separate synthetic database; see the guide above.

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_demo
# Subsequent resets target only the recognized local fictional demo database:
.\.venv\Scripts\python.exe -m scripts.seed_demo --reset
.\.venv\Scripts\python.exe -m scripts.serve_demo
```

Run `python -m scripts.serve_demo --worker` in another terminal to replenish demo
cards. This uses the separate `career_kitchen_demo` database, with 30 fictional
candidates, three fictional organizations, and ten fictional vacancies.

Accounts: `candidate-01` through `candidate-30`, `employer`, `verifier`, and
`operations`, all at `@fictional.example.invalid`. These are local fixture
identities, not Supabase accounts or real verifications. For a repeatable real HTTP
check, follow the [fresh-fixture smoke procedure](docs/demo.md). Get a short-lived token
with `python -m scripts.demo_token candidate-01`, then use Swagger's **Authorize**
button. Tokens are printed only when this CLI is explicitly run; never commit
them. FastAPI has no password login or development role-assignment endpoint;
the frontend uses Supabase or its explicit local fictional account selector.

## Verify and generate contracts

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check apps/api scripts
.\.venv\Scripts\python.exe -m mypy apps/api/app
.\.venv\Scripts\python.exe scripts/validate_migrations.py
.\.venv\Scripts\python.exe scripts/export_openapi.py --check
```

The migration check creates and drops its own temporary test database. Integration
and concurrency tests use isolated PostgreSQL schemas in `career_kitchen_test`;
they never use SQLite to claim locking correctness. Client generation and strict
TypeScript checks are documented in `packages/api-client/README.md`.

All writes require `Authorization` and `Idempotency-Key`. Resource changes carry
the documented expected version; stale writes return 412. Handle 409/412 by
refreshing state and obtaining a new human decision. Messages and documents remain
behind live participant/disclosure authorization even when object IDs are known.

## External setup

No Supabase project, Railway service or GitHub remote was supplied. Configure
the server-only variables in `.env.example` before deployment. Real binary
document uploads require ClamAV; external email/calendar/payment providers and
prospective model validation require separate setup. The backend does not claim
delivery, payment, verification, employment or reliability from an absent provider.
See `docs/STATUS.md` for the precise verification boundary.
