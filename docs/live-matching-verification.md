# Live matching and outcome learning

The deterministic attention optimizer now executes live through
`app.services.clearing`. `FEATURE_MODE=LIVE` is the default. Scenario portfolio
research remains read-only: its modeled employment probabilities have no observed
validation and do not control live decisions.

## How matching works

1. Retrieve a bounded pool using structured role, preferences, availability,
   consent, account, block, prior-cycle and attention filters. Check private
   compensation and essential evidence before scoring.
2. Compute transparent reciprocal compatibility from confirmed taxonomy skills
   and stated acceptable preferences. A qualified learned model can replace the
   ranking utility while retaining the native snapshot and deterministic score.
3. Subtract directional attention and congestion costs. Keep the chosen first
   mover; never quietly substitute a weaker direction just to fill a slot.
4. Optimize positive-utility proposals with sparse residual flow. Candidate-first
   work consumes candidate active space and vacancy receiving space; the reverse
   direction uses the other two resources. Residual paths can replace a greedy
   choice with several better compatible choices.
5. Lock selected participants and the model registry, then recheck versions,
   eligibility, cooldown, attention and model identity before transactional
   issuance. Actual human decisions still require independent double opt-in.

Pending first-side decisions reserve future receiving capacity across separate
matching runs. Budget exhaustion returns a complete feasible greedy plan. All
mutations retain versioning, idempotency, audit and outbox records. Worker
maintenance queues allocation into a separate transaction to avoid carrying its
earlier participant locks into the optimizer. Concurrent HTTP regression tests
also cover the repaired authentication/idempotency event-loop lock problem.

## Executed allocation evaluation

On 18 October 2026, the reproducible benchmark compared the live allocator with
an independent complete greedy comparator on identical proposals and capacities.
One curated trap and 999 seeded small markets were exhaustively enumerated;
two larger synthetic markets checked feasibility and objective improvement.

| Measure | Greedy | Live optimizer |
| --- | ---: | ---: |
| Exhaustive small-market optima | 974 / 1,000 | 1,000 / 1,000 |
| Feasible plans | 1,002 / 1,002 | 1,002 / 1,002 |
| Strict objective improvements | — | 28 |
| Objective regressions | — | 0 |
| 400-edge supplied utility | 107.940 | 108.733 (+0.73%) |
| 2,000-edge supplied utility | 147.820 | 148.299 (+0.32%) |

These fixtures do not establish population performance or hiring accuracy.
The gains depend on the market: the curated greedy trap improves from 1.0 to
1.8, while most random small markets tie. The latest larger-case live runtimes
were approximately 49 and 129 milliseconds on this machine; greedy was faster.
Large cases have no independent exhaustive optimality certificate. Production
planning uses a one-second/one-million-operation budget with deterministic
fallback. Database retrieval and transaction time are outside these pure timings.

[Committed result summary](evaluations/live-matching-2026-10-18.json) includes
source/input fingerprints, limits, scale measurements and limitations. Reproduce
the complete immutable inputs and per-market report from the repository root:

```powershell
$env:PYTHONPATH='apps/api'
.venv/Scripts/python.exe -m scripts.benchmark_live_matching `
  --output .local/live-matching-benchmark/reproduce --check
```

PostgreSQL tests separately verify actual scoring, improved allocation, receiving
reservations, concurrency, consent, tenant authorization, immutable outcome
capture, model gates and privacy erasure. A real structured compatibility fixture
improved total utility from 1.0 to approximately 1.414 with no attention violation.
That fixture is explicitly fictional, not a candidate success report.

The complete local backend regression run passed **697 tests and four subtests**
in 426 seconds. Final rolling-window export changes additionally passed three
PostgreSQL tests; all 50 learning/export/refresh/benchmark research tests passed.
Migration upgrade/downgrade/upgrade and runtime-role isolation passed for all 47
application tables. Ruff, mypy, OpenAPI consistency, generated TypeScript parity,
type checking, six client tests and source secret scanning passed. The broader
332-test research run passed 331 checks and encountered one existing Windows
symlink-creation permission error, including when retried outside the sandbox.
Its actual symlink check still needs the Linux CI environment.

## Machine learning and actual accuracy

The subsequent [public relevance measurement](matching-accuracy-measurement.md)
scores the actual compatibility core through a fixed ESCO text adapter. It exposes
a weakness against text baselines: 17.2% human first-choice agreement and
TalentCLEF MAP 0.556. These adapter-conditioned component results do not measure
live mutual interest or hiring accuracy.

The implementation supports regularized logistic regression with training-only
imputation/scaling, missingness indicators and optional held-out calibration.
Both candidate and organization must explicitly opt in before an introduction
can contribute to learning. Resolution snapshots are immutable; profile edits,
later consent grants and nonresponses cannot create historical labels.

The trainer reports accuracy, balanced accuracy, precision/recall/F1, ROC AUC,
average precision, Brier score, log loss and calibration with stated uncertainty
assumptions. Forward-time, identity-separated train/validation/test cohorts and
candidate/employer cluster comparisons reduce leakage. Activation requires
improvement over prevalence, raw compatibility, fitted compatibility and the
active incumbent. Every later promotion needs future evaluation cohorts even
after a previous model was retired. Consent revocation retires learned scoring;
invalid, future or stale models also restore deterministic scoring.

The refresh command connects export, training, evaluation and optional qualified
promotion for repeated runs. It is not per-click weight mutation and does not
install a scheduler. See [learning commands and gates](matching-learning.md).

The read-only local database audit found **zero introductions and zero outcomes**.
An actual empty isolated PostgreSQL refresh returned `NOT_TRAINED` with zero
exported rows. No observed model was trained or activated, so **real mutual-interest
and hiring accuracy are currently unmeasured**. Fabricated model metadata and
fictional training fixtures test software behavior only. Hosted migrations,
provider checks and a prospective outcome comparison have not run for this change.

## Remaining limitations

- Optimization is over the supplied graph. Candidate and vacancy retrieval is
  bounded; private compensation/evidence checks occur after the SQL pool limit,
  so unsuitable earlier rows can still exclude later eligible profiles. No
  exhaustive marketplace optimum or fair exposure coverage is claimed.
- Acceptable preferences are not ranked. Three current live input features are
  constant after eligibility; optional skill coverage supplies most variation.
  A more complex model cannot recover information absent from the input contract.
- Explicitly resolved historical introductions are a selected population. A
  conditional prediction does not describe unexposed pairs, nonresponders,
  employment offers or starts. No causal hiring improvement is established.
- Better total utility may concentrate exposure. Attention ceilings bound load,
  but do not establish fairness or measured satisfaction.
- Concurrent profile/capacity changes can reduce issued volume below a planned
  optimum. Existing worker retries/dead letters remain necessary for transaction
  conflicts; no general absence of lock conflicts is claimed.
- Evaluation declarations are privileged attestations; hashes establish integrity,
  not truth. Deployment needs authentic consented outcomes and prospective
  monitoring. Minimum sample gates do not certify employment reliability.
