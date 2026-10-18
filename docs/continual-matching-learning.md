# Continual outcome learning

`scripts.continual_matching_learning` is a separate operator process that checks
for new immutable resolutions, runs the existing export/train/evaluate flow and
can request qualified promotion. It does not run inside the API or an outbox
transaction. Starting the API alone does not start training.

Apply the reviewed application migrations and configure the backend environment
before starting it. Install the optional operator dependencies with
`pip install -c requirements.lock -e '.[learning]'`. API inference still uses
only the standard library. From the repository root, one bounded check is:

```powershell
$env:PYTHONPATH='apps/api'
.venv/Scripts/python.exe -m scripts.continual_matching_learning `
  --output-root .local/matching-continual --once
```

Omit `--once` to keep checking, normally once per day. Run that process under
the deployment's process supervisor. In an already configured production
environment, append `--promote` to request automatic promotion **after all
existing observed-outcome evidence gates pass**. Development, test and staging
cannot request promotion. No supervisor, scheduled task or hosted deployment
was installed by this change.

## What makes a new model eligible

The controller first acquires a PostgreSQL session advisory lease, so another
controller on the same database cannot train concurrently. It reads aggregate
counts and registry history in a read-only transaction. No participant or
registry locks are held during numerical fitting. The existing promoter later
locks and checks the incumbent, consent epoch and unused future test cohort
inside its own audited transaction.

At least 100 new stored resolutions trigger an attempt. This count includes
rows that may later be excluded; it is **not** evidence of sufficient consented
labels or model quality. Export still requires consent at first exposure and
currently, immutable snapshots, explicit resolutions, and the unchanged account
and privacy checks. Nonresponse does not become a negative example.

Before export, UTC time determines a 365-day observation window, a 30-day
validation interval, a 30-day test interval and a 14-day resolution horizon.
Training and validation cutoffs are fixed before reading labels. Existing
candidate/organization separation, class counts, convergence and paired
comparisons against prevalence, raw/fitted compatibility and the incumbent
remain mandatory. Minimum counts and a varying-input check are practical
screens; they do not certify accuracy or guarantee enough statistical power.

All registered models, including retired versions, constrain the next holdout.
The controller also reserves its current evaluation period before training.
Rejected challengers and interrupted attempts cannot immediately reuse that
period in this controller. A new evaluated attempt normally needs about
75 days of future data with the default settings. An explicit early exit with
no model evaluation (`NOT_TRAINED` or `INSUFFICIENT_DATA`) instead waits for
another batch of resolutions without consuming a new holdout period.

The seven-field outcome contract captures confirmed-skill coverage, precision
and Jaccard overlap, plus stated role/mode/type compatibility and optional text
relevance. The last field stays unknown unless an appropriate versioned
extractor actually supplies it. Its immutable extractor hash must travel with
the value through exposure, export, fitting and inference. Public benchmark
rankers estimate different targets and cannot be promoted as observed
mutual-interest models. See [feature and inference contracts](matching-learning.md).

## State and recovery

Use **one shared persistent output directory** for every controller instance on
this deployment. Keep its `controller_state.json` and private run artifacts.
The database retains registered-model history, but rejected or interrupted
attempt history lives in this local state file. Losing it, choosing another
directory or invoking manual refresh separately can bypass that additional
rejected-attempt history. This file is an operational guard, not an independent
database experiment ledger or reliability certificate.

Each attempt uses a new run directory. `controller_status.json` reports a
waiting state, completed refresh, or uncertainty. `WAITING_FOR_NEW_OUTCOMES`
and `WAITING_FOR_FRESH_COHORTS` perform no training or promotion. Individual
refresh results distinguish an insufficient dataset, rejected challenger,
reviewable model and confirmed promotion. A promotion connection failure can
leave the server commit unknown: `REFRESH_STATE_UNKNOWN` / `promoted: null`
requires registry inspection before retrying. It never claims a rollback that
has not been established.

The process needs monitoring, writable private storage, operator dependencies
and sufficient future consented outcomes. Defaults leave roughly 15 days
between the next fresh evaluation window and the existing 90-day model age
fallback; failed attempts or inadequate data may keep deterministic scoring
active. No automatic system can guarantee that the next challenger is better.
The incumbent remains active only while its existing validity, age and consent
conditions hold; rejected challengers never replace it.

## Executed checks

Controller unit tests exercise empty sources, exact chronological cutoffs,
lease contention, prior registered history, insufficient-data retries, rejected
and failed attempt reservations, promotion restrictions, and uncertain commits.
Real PostgreSQL tests use disposable schemas in `career_kitchen_test` to verify
lease exclusion/release and an empty source waiting without model activation.
These are software checks using fictional fixtures, not accuracy evidence.
