# Independent matching allocator benchmark

The stronger portfolio allocator improves optimization of a declared mathematical
objective. Its evaluation uses fictional sparse markets and an independent
exhaustive oracle. It does not measure real matching accuracy, mutual interest,
hiring, job satisfaction or verified employment. Experimental planning remains
read-only `SHADOW`; the transactional live matching baseline remains authoritative.

The implementation is `scripts/benchmark_matching_allocator.py`, with independent
checks in `tests/research/test_matching_allocator_benchmark.py`. It compares the
preserved `allocate_heuristic` with `allocate_global` on identical immutable
`MarketSnapshot` objects. No external dataset, network, database, private profile,
JTH data or model download is used.

## Fixed protocol

Protocol `stipulated-allocation-oracle-v1` uses seed `270318` and these cases:

| Family | Cases | Declared purpose |
| --- | ---: | --- |
| Seeded linear | 300 | Four candidates, four vacancies, capacity one, independent edge probability `.65`, routing values drawn uniformly from integer hundredths `.01` through `1.00` |
| Seeded modeled | 60 | Four candidates, three vacancies, capacities one or two, two plausible models per vacancy, two equally weighted scenarios per model, heterogeneous stipulated probabilities and attention/delay costs |
| Adversarial linear | 3 | Sparse cycles across four, six and nine vacancies that require reassignment beyond the old local exchange neighborhood |
| Adversarial modeled | 1 | A complementary two-candidate bundle with negative individual marginal gains but positive joint robust value |
| Boundary | 3 | Fixed/shared commitments, unavailable consent, ineligibility, zero limits, unprofitable edges and empty markets |
| Larger sparse | 1 | Eighty candidates, forty vacancies, capacity two and 320 edges; descriptive objective and runtime comparison without an exhaustive oracle |

Every case uses the same two million operation limit and ten second cooperative
wall-clock limit per method. The edge limit is 2,000 and the legacy exchange limit
is twenty steps. These explicit comparison limits differ from deployment defaults.
They are recorded in `protocol.json` before either method executes. The benchmark
does not tune parameters against its outcomes.

The oracle enumerates every candidate's possible vacancy or unassigned state,
rejects capacity violations, preserves existing commitments and prevents a
contingent candidate from appearing in multiple vacancies. Its independent
objective directly evaluates routing value less declared costs, or the weighted
conditional nonfill equation and worst case across supplied plausible models.
It does not call production objective, scenario, assignment or exchange helpers.
Unknown model support is determined across the entire optimization-feasible pool;
it cannot switch from modeled fill to routing units depending on the chosen
subset. Candidates fixed elsewhere and slots with no residual capacity are
excluded from that pool. Shared existing commitments make affected risk unknown.

Oracle enumeration refuses a state bound above two million instead of returning
a partial optimum. All 367 tiny cases fit that bound. Seeded modeled cases use
`target_fill=1.0`, so threshold pruning does not introduce a lower-value policy
tradeoff into the optimization comparison. This benchmark cannot establish the
optimum of larger nonlinear markets or of an alternative objective.

Every completed output is checked for retained vacancies and commitments,
shortlist limits, candidate uniqueness, eligible and opted-in edges, unchanged
input hashes, independently replayed objective, `SHADOW` mode and
`CANNOT_CERTIFY`. A failure stops publication. Budget exhaustion is separately
reported without inventing a plan or score. Scores within `1e-9` count as matching
the independent optimum.

## Executed results

The completed local run is
`.local/matching-allocation-benchmark/run-4/report.json`, with protocol SHA256
`6d62ee29cd82d2bd6350d418afbac5cfdcaabe184c8835c513c3b99b3be127eb` and
fixture-inventory SHA256
`d3f9a6449ed244910aa8f848f82a289d9d771e44eb56cb7bbdc88830cff451f5`.
The protocol also retains Python version, source hashes, exact fixture hashes and
limits. These ignored local artifacts contain only stipulated inputs and software
results; they are not real candidate outcomes.

| Family | Old allocator at oracle optimum | New allocator at oracle optimum |
| --- | ---: | ---: |
| Seeded linear | 278 / 300 | 300 / 300 |
| Seeded modeled | 59 / 60 | 60 / 60 |
| Adversarial linear | 0 / 3 | 3 / 3 |
| Adversarial modeled | 0 / 1 | 1 / 1 |
| Boundary | 3 / 3 | 3 / 3 |
| All oracle cases | 340 / 367 | 367 / 367 |

Across all 368 comparisons, the new allocator improved the stipulated objective
in 28 cases and regressed in zero. Both completed every case within the declared
comparison budgets. This demonstrates stronger optimization on these fixtures;
the selected case distribution does not estimate a production improvement rate.

The complementary model case has old objective `0.00` and new objective `0.96`:
each candidate alone has a robust gross value of zero and costs `.02`, while
together they cover both stipulated model alternatives. No percentage increase
is reported against the zero baseline. The four-vacancy cycle improves routing
objective from `4.00` to `4.47`.

On the larger sparse case, routing objective increases from `56.24` to `58.67`
(4.32%). The measured allocator call takes 1.1920 seconds / 293,148 operations
for the old method and 0.0313 seconds / 40,521 operations for the new method.
These timings describe this run and machine. That case has no independent
exhaustive optimum, and its lower call time does not establish production latency.

Two additional worker-shaped trials call the actual `run_shadow` entry point
using unchanged default limits: one second, one million operations and 20,000
edges. Both have one hundred candidates, twenty vacancies and capacity ten:

| Available graph | Result | Operations | Measured call including hashing |
| --- | --- | ---: | ---: |
| Four edges per candidate, 400 total | Completed | 44,980 | 0.0419 seconds |
| All twenty edges per candidate, 2,000 total | Completed | 154,632 | 0.1596 seconds |

Both retained the supplied baseline and reported zero side effects. Invariant
checks passed. These two trials establish that these particular snapshots fit
the current default budget; they do not establish an upper latency bound or a
real hiring outcome. Their objectives have no independent exhaustive oracle.

## Release-policy validation

Optimizing an allocation and only then releasing threshold-redundant members
can discard the apparent gain. A minimized one-vacancy example has target `.5`,
capacity three, two plausible models with candidate successes `(1, 1, .5)` and
`(1, .25, 1)`, and candidate costs `(.2, .05, .05)`. The latter two candidates
together have raw utility `.9`, but the release policy reduces them to one
candidate worth `.45`. The first candidate alone retains utility `.8`.
Joint search now scores the final released shortlist at every leaf, and bounded
bundle repair compares released members before accepting a change. A zero-target
vacancy therefore cannot consume a candidate and discard them after the search
has already starved another vacancy. Fixed human commitments remain unchanged.

An exact search can exhaust its policy-stable possibilities while the release
policy still constrains the unrestricted raw-utility optimum. In that case it
reports `_THRESHOLD_POLICY` and `search_complete=false`; the raw oracle remains
an upper bound. The benchmark does not mislabel this as an unrestricted optimum.

The fresh verification run uses seed `81237`, 1,500 linear cases, 300 modeled
cases, 1,000 varied-target cases, the seven fixed adversarial/boundary cases and
one larger sparse case. Both methods completed all 2,808 comparisons: 196 strict
improvements and zero regressions. The 1,807 original-style oracle cases reached
the raw optimum in 1,807 cases for the new method versus 1,673 for the old method.
The separate target-policy cohort reached the unrestricted raw optimum in
789 / 1,000 cases versus 743 / 1,000, with 61 strict improvements and zero
regressions; remaining gaps are explicitly constrained by release policy.
Both default-budget shadow trials also completed with the baseline intact.

Artifacts are at `.local/matching-allocation-benchmark/pr-verification-final/`;
protocol SHA256 is
`71dda00a769d9a4adf6462ca862dc1079de51b35e0c047924c13a3a754e4984b`
and fixture-inventory SHA256 is
`c52b271f2f1a771e8789b98efc3e03b4689f166c35e6b0c93d334b86c9242cf9`.
This is a larger software verification cohort, not evidence of hiring efficacy.

## Reproduce and inspect

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = 'apps/api'
.venv/Scripts/python.exe -m scripts.benchmark_matching_allocator --output .local/matching-allocation-benchmark/run-new --check
.venv/Scripts/python.exe -m scripts.benchmark_matching_allocator --output .local/matching-allocation-benchmark/threshold-new --threshold-cases 300 --check
.venv/Scripts/python.exe -m pytest tests/research/test_matching_allocator_benchmark.py -q
.venv/Scripts/python.exe -m ruff check scripts/benchmark_matching_allocator.py tests/research/test_matching_allocator_benchmark.py
.venv/Scripts/python.exe -m mypy apps/api/app scripts migrations
```

The focused benchmark checks passed: nineteen tests and 82 subtests, including oracle
independence, known complementary-bundle arithmetic, incomplete model populations,
fixed candidates elsewhere, cap reductions, eligibility and consent, deterministic
input permutations, invalid output detection, budget exhaustion, and artifact
publication and CI failure conditions. Ruff passed; the full mypy command passed
across 93 source files.

Repository verification also ran the PostgreSQL-backed backend suite: 450 tests
passed. Earlier coverage measurement was 85% overall. After review, focused
algorithm, worker-snapshot, live-retrieval and benchmark checks were rerun against
the final release-policy correction: 170 tests and 86 subtests passed. These
test runs overlap and must not be
added as distinct cases. Formatting, Ruff, mypy, OpenAPI regeneration checks,
secret scanning and `git diff --check` passed.

The broader research suite ran using the declared research dependencies in
`.venv-research`: 291 tests passed and one existing semantic-model snapshot test
errored when Windows denied symlink creation (`WinError 1314`). That symlink
check remains unverified here; its restriction was not bypassed or hidden by
changing the test. The full output is retained locally at
`.local/matching-allocation-benchmark/pr-research-suite.log`. No hosted Supabase
service checks or evaluation on observed first-party hiring outcomes ran.

The output directory must be new. `--linear-cases`, `--modeled-cases` and `--seed`
declare a different fixture experiment and are recorded in its protocol;
`--threshold-cases` adds a separately seeded cohort cycling targets through
`0`, `.5`, `.8`, `.95`, `.999` and `1`; its raw-utility oracle remains an upper
bound when release policy constrains the result. `--skip-scale` omits both larger
comparisons and default-budget shadow trials. `--check` fails for a regression,
an incomplete comparison, a false complete-search claim or a default-budget
shadow timeout. CI sets `PYTHONPATH=apps/api`, runs the research tests, and then
executes the benchmark with 300 threshold-policy cases and `--check`.
Complete `protocol.json` and `report.json` are published together by directory
rename, with no overwriting of an existing result. Per-case reports preserve
objectives, oracle gaps, solver names, completion flags, operations, timings,
invariant checks and allocation hashes. Repeatable fixture/objective results are
separate from naturally variable measured runtimes.

## Evidence still required

No observed first-party introduction outcomes or the previously documented public
benchmark archives are present in this checkout. Existing synthetic skill labels
encode a known required-skill threshold, and the small human text benchmark ranks
five jobs per CV; neither supplies actual two-sided opt-in or hiring labels.
Previously documented frozen MiniLM results also underperformed lexical methods
on that human benchmark. Adding text complexity cannot be described as an
empirically validated improvement to this allocator.

Prospective, consented observations with frozen pre-exposure features, correct
explicit-decision labels, grouped temporal holdouts and selection-aware analysis
are still required to measure matching quality. More effective optimization of a
stipulated objective does not validate that objective, its model probabilities or
the quality of real introductions. No reliability certification is issued.
