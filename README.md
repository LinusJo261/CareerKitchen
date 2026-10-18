# Career Kitchen

Persistent FastAPI backend and a Next.js interactive preview of Career Kitchen.
The candidate and employer workspaces use fictional, in-memory demo data; they
do not create accounts or persist hiring actions to the API. Career Chef includes
public onboarding guides and an optional, consent-based Gemini chat through the
server-side API bridge. See [website and API testing](docs/career-chef-testing.md).

The API implements candidate/employer onboarding, organization verification and
team ACLs, versioned vacancies and requirements, reciprocal decision cards,
double opt-in, bounded attention, waiting/expiry/replenishment, PACT, scoped
evidence disclosure and revocation, chat and private attachments, interviews,
offers, independently attested starts, notifications, abuse reports, and privacy
jobs. PostgreSQL owns state, transactions, locks, idempotency, audit and the durable
worker queue. Supabase provides production identity and private storage.

The original reciprocal formulas remain available. Cold start uses explicitly
nonprobabilistic relevance routing. R99, WITNESS and adaptive exposure are research
components. The initial `FEATURE_MODE=SHADOW` records read-only diagnostics while
the baseline executes live matching; advanced execution is disabled and reliability
is `CANNOT_CERTIFY`.

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

## Fictional development market

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
them. No password/login endpoint or development role-assignment endpoint exists.

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
