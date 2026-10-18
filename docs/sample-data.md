# Large synthetic sample market

The backend can load **20,000 applicant profiles and 20,000 vacancies** into
the separate local PostgreSQL database `career_kitchen_samples`. The ordinary
database and existing 30-candidate demo are preserved. This is a development
fixture, not real applicants, available jobs, consent, or hiring outcomes.

The source is Michael Ozon's
[Candidate-Job Matching Synthetic Dataset](https://huggingface.co/datasets/michaelozon/candidate-matching-synthetic),
revision `178ab864dcad9910c5670d43e4bdbbb901a11f18`, listed under MIT in its
[pinned dataset card](https://huggingface.co/datasets/michaelozon/candidate-matching-synthetic/blob/178ab864dcad9910c5670d43e4bdbbb901a11f18/README.md).
It contains 10,000 resumes and 2,500 jobs. The default import makes two labeled
variants of each resume and eight of each job, yielding 40,000 sample entities.
These variants repeat source content; they do not add independent observations.
The importer never downloads the source's match labels, embeddings, or outcomes.

The [RecSys 2017 rules](https://www.recsyschallenge.com/2017/#rules) restrict
the dataset to academic use and prohibit redistribution and commercial use, so
it is excluded. Kaggle's competition data is excluded because its access and
reuse terms were not verified. JTH is excluded by `AGENTS.md`.

## Interactive demo in the same app

The homepage **Demo mode** button opens the existing candidate or employer
workspace with the large sample market. The banner lets you switch sides,
run matching, browse the market, or exit to the homepage. Normal sessions
continue to use their configured API; demo sessions use the separate local
sample API and an HttpOnly cookie bound to that destination.

After fetching and importing below, prepare the fictional market once:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_sample_demo
.\.venv\Scripts\python.exe -m scripts.serve_samples
# In another terminal, with FRONTEND_LOCAL_DEMO=true in the local .env:
pnpm dev
```

Open [Career Kitchen](http://127.0.0.1:3000), select **Demo mode**, and choose
**Try as a candidate**. The prepared market includes 20,000 active sample
applicants and 20,000 active sample jobs. Preparation creates explicitly
fictional participation confirmations and company verification inside the
marked sample database. These are fixture eligibility, never actual people's
consent, credentials, or hiring outcomes. Learning remains opted out.

**Run matching** uses the same deterministic optimizer and transactional
executor as ordinary introductions. Each run works on a bounded shortlist
from the market and respects the attention ceilings; it does not attempt to
materialize 400 million candidate/job combinations. Candidate entry has a
small initial menu issued by the executor. Click **Interested**, switch to
**Employer**, and open **View suggestions** to make the separate employer
decision. Only both decisions create an introduction. The employer inbox is
empty until a demo participant expresses interest; no human choices
are manufactured by setup.

The catalogue under **Browse market** searches and pages through original
sample jobs and applicants. Browsing does not bypass matching attention
limits or create an introduction. Only importer-audited, unchanged fixtures
are included; later profile/job edits retain ordinary workspace privacy and
are excluded from the shared catalogue. There is no private compensation,
evidence or contact information in the catalogue.

Demo mode is disabled for production builds and non-loopback requests. This
workflow was built for the local application; hosted deployment and Supabase
demo identities have not been configured or verified. Exiting clears the demo
session even if its API is offline.

`CAREER_KITCHEN_SAMPLE_API_URL` selects the separate loopback API and is also
the default port used by `scripts.serve_samples`. The default is port 8001;
if the ordinary API already uses that port, choose another, such as
`http://127.0.0.1:8002`. The gateway refuses to use the same port for both.

## Fetch and import

Use the repository's existing local PostgreSQL setup with `ENVIRONMENT=development`,
`AUTH_MODE=local`, `ALLOW_DEV_AUTH=true`, and independent configured secrets.
The importer requires a loopback `career_kitchen` or `career_kitchen_test`
configuration and forces the target database to `career_kitchen_samples`.
It rejects connection options that could override that destination.

The explicit download step uses optional PyArrow in the research environment;
the API and worker do not gain that dependency. If needed, create the research
environment and install `requirements-research.txt` plus `httpx` there first.

```powershell
.\.venv-research\Scripts\python.exe -m scripts.sample_dataset --download
.\.venv\Scripts\python.exe -m scripts.seed_samples
```

The download freezes the pinned dataset card, original Parquet files, validated
JSONL, counts and SHA256 checksums under ignored `.local/sample-dataset/`.
The import checks every checksum before opening a database. Its receipt is
stored transactionally in PostgreSQL and copied to `.local/sample-import-report.json`.
Repeat either command to verify/reuse its completed result. An identical import
does not duplicate or overwrite rows. Different source content or counts are
rejected once a receipt exists. There is no reset or delete option.

For a smaller **initial** import, use `--candidates 1000 --vacancies 500`.
Each count supports 1 through 100,000. Use the default counts for the full market.
Batch inserts reduce round trips but the complete import has one transaction:
failure rolls back all entities, audit records, outbox events and the receipt.
Database creation and migrations happen before this data transaction; an empty,
marked database may remain after a failed import and can be retried.

## Inspect through the existing API

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_samples
# In a second terminal, explicitly print a short-lived local fixture token:
.\.venv\Scripts\python.exe -m scripts.serve_samples --token employer
# Or inspect an applicant's own profile:
.\.venv\Scripts\python.exe -m scripts.serve_samples --token candidate-000001
```

Open [sample API Swagger](http://127.0.0.1:8001/docs), authorize with the chosen
token, and use `GET /v1/candidates/me`, `GET /v1/candidates/me/skills`,
`GET /v1/organizations`, or `GET /v1/organizations/{org_id}/vacancies`.
The default market has 200 explicitly synthetic organizations, each with 100
draft jobs. Tenant reads use the normal database memberships and vacancy ACLs.
Candidate tokens cannot read another candidate's private profile or an
employer's draft jobs. Local fixture tokens are not Supabase accounts.

Before interactive preparation, profiles and vacancies stay `DRAFT`, with attention cap 3. Candidate terms,
privacy and learning consent remain false; skills are unconfirmed. Companies
remain `PENDING_VERIFICATION`, have no approved signatory, and do not opt into
learning. Pay, work mode, employment type and region are explicitly labeled
fixture values because the source does not supply those business terms.
Dataset skill labels become unreviewed preferences, never lawful essential
requirements. Source ID and variant number appear in each profile or job and
its reference-only audit/outbox event. Aggregate audit hashes also cover all
dependent users, skills, memberships, requirements and ACL rows.

The basic import creates no decision cards, interactions, mutual matches, verified
employment or training outcomes. Sample import events do not trigger live
reconciliation. API activation still requires the existing consent,
verification and authorization checks. No worker is needed to inspect the data
or to run matching from the demo banner.
Do not treat replicated sample content as independent evidence of matching
accuracy or promote a model using this fixture.

The homepage demo entry chooses this API automatically for its session. The
existing small-demo account picker keeps using its original API and accounts.
The CLI tokens above remain useful for independent backend inspection.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/tests/algorithm/test_sample_dataset.py
.\.venv\Scripts\python.exe -m pytest apps/api/tests/integration/test_sample_import.py
.\.venv\Scripts\python.exe -m pytest apps/api/tests/integration/test_sample_demo.py
.\.venv\Scripts\python.exe -m ruff check scripts/sample_dataset.py scripts/seed_samples.py scripts/serve_samples.py
```

Source tests use fixtures and HTTP mocks. Integration tests require real local
PostgreSQL and create isolated schemas in `career_kitchen_test`. They cover
atomic rollback, identical replay, conflicting imports, signed aggregate audits,
source provenance, terms hashing, tenant reads and the absence of fabricated
consent or outcomes. Successful local checks do not establish hosted Supabase,
Kaggle access, or production deployment.

The local run on October 18, 2026 passed 42 source tests and 20 PostgreSQL
integration tests. The full import was then checked separately: 20,000 draft
profiles, 20,000 draft vacancies, 200 organizations, 129,776 skill assertions,
99,944 vacancy preferences, and 40,275 valid audit signatures with corresponding
outbox events. The existing API returned 200 for authorized fixture reads and
403 for candidate access to employer draft jobs. All outcome and model tables
were empty. An identical full import preserved these counts. Local receipts are
in `.local/sample-import-report.json` and `.local/sample-verification-report.json`.

Interactive demo validation also passed the production frontend build,
TypeScript and backend type checks, generated API contract checks, 69 frontend
checks, and 25 PostgreSQL regression cases for import, retrieval and the demo.
The browser walkthrough verified entry, a matching run, catalogue search and
paging, role switching and a mutual introduction after two separate choices.
