# Matching accuracy: evidence and evaluation protocol

Algorithmic optimality, human relevance, and observed hiring outcomes are different
targets. A better allocation objective establishes that the planner makes better
use of its supplied scores. It does not establish that those scores predict what
people will do. No single accuracy percentage combines these targets honestly.

The user has authorized enabling the improved deterministic allocation path.
That authorization changes execution scope; it does not turn synthetic tests into
observed hiring evidence. Double opt-in, eligibility, consent, tenant isolation,
attention ceilings, transactional execution and audit/outbox requirements still
apply. A learned model must have an explicit target and version.

## Evidence available in this checkout

An October 18, 2026 targeted inventory found local synthetic allocation reports
under `.local/matching-allocation-benchmark/` and
`.local/allocator-threshold-verification/`. The public synthetic training files
and public human-ranking source/model caches described by the older research
guides were not present in this checkout. Existing documentation is a record of
earlier experiments, rather than a newly reproduced result.

The first-party inspection used the existing `require_local` development/test
and loopback guard, a three-second connection timeout, a read-only transaction
and a five-second statement timeout. The initial sandboxed connection was denied;
an approved retry succeeded. The configured local database's public schema had
**zero candidates, vacancies, pair cycles, decision cards, exposures, mutual
matches, offers and verified starts**. No observed first-party response,
mutual-interest or employment-start accuracy can be estimated from those empty
tables. This inspection did not access hosted Supabase or another deployment.
Local fixtures and demonstration data must never be classified as real
participant observations.

| Evidence | What it can measure | What it cannot establish |
| --- | --- | --- |
| Exhaustive small allocation oracle | Objective gap, feasibility, stable replay, exact solution within numeric tolerance on those inputs | Relevance of the supplied scores or future hiring accuracy |
| Larger synthetic market stress test | Runtime, fallback behavior, invariants and gains over a fixed comparator | A guaranteed global optimum or behavior of real people |
| Public generator-labelled pairs | Agreement with the generator's declared rule | Human judgment, mutual interest, interviews or starts |
| Public human rankings | Agreement with the specific annotators and ranking direction | Reciprocal interest or observed employment success |
| Mature, consented first-party exposures | Prediction quality on the logged exposed population for the declared outcome | Outcomes of unexposed pairs or causal improvement by a new policy |
| Prospective concurrent comparison | Policy-level effects on the prespecified population and horizon | Unmeasured outcomes or unlimited generalization |

The existing [human benchmark guide](matching-human-benchmark.md) describes
30 CV queries against five vacancies and 58 valid, correlated query/rater rows.
The [semantic guide](matching-semantic-benchmark.md) records that frozen MiniLM
did not improve on BM25. Those figures evaluate job rankings for a CV and cannot
be inverted into candidate rankings for a vacancy. The
[authors' repository](https://github.com/NataliaVanetik/vacancy-resume-matching-dataset)
declares GPL-3.0 and supplies human ranking instructions. Source snapshots and
license/provenance checks are required before a new local experiment; no source
CV text or individual annotation is committed. No JTH data is used or downloaded.

## Outcome contract before training

Declare one target per dataset and artifact. Useful targets include:

- `FIRST_DECISION_INTEREST`: interest by the recipient of the first exposed card
  within the declared response horizon.
- `MUTUAL_INTEREST`: both sides explicitly interested within the declared horizon
  after the first exposure.
- `VERIFIED_START_BY_DEADLINE`: an independently verified employment start by a
  prespecified deadline. An accepted offer alone is not a start.

These names describe evaluation targets; an implementation must publish its
actual supported target enum. A first-decision model must not be presented as a
mutual-interest or hiring model.

The implemented learning artifact's target is `mutual_opt_in_within_horizon` and
its estimation population is
`eligible_issued_introductions_with_explicit_resolution_within_horizon`.
That population excludes unresolved/nonresponding introductions rather than
labelling them rejected. Its probability is consequently conditional on explicit
resolution in the historical exposure policy. It is not a mutual-interest rate
for all issued introductions. Its four inputs are optional skill coverage and
stated role, work-mode and employment-type compatibility, with learned missing
value handling. The latter three equal one for ordinarily eligible live pairs
because hard eligibility already requires them. This is a material signal limit;
training cannot manufacture absent experience, interest or outcome information.

For every accepted label, retain a reference to the exposure and immutable
pre-introduction feature snapshot, candidate and vacancy versions, recipient
side, first mover, feature/model/policy versions, exposure time, observation
cutoff, maturity horizon and observed event time. A model artifact stores numeric
coefficients and aggregate provenance, not identities, private documents, salary
floors, message text or protected attributes. An export must still be scoped and
authorized; offline processing does not bypass tenant or consent checks.

Only information available at prediction time enters features. A second-side
response is conditioned on the first person's interest; it is not an independent
first-side label. A person can have multiple exposures, and two exposures from
one cycle are not independent examples. Do not overwrite an old snapshot with a
profile's current state or a later re-score.

Every maturity rule must specify its treatment of passes, expirations,
cancellations, unavailable vacancies, consent withdrawal and missing events.
An unresolved exposure inside its horizon is censored, not negative. A pass can
be an immediate negative for interest; withdrawal and administrative cancellation
are not evidence of dislike. Missing/unexposed pairs remain unlabeled. For a
fixed-horizon outcome, either observe the whole horizon or use a separately
specified, validated censoring estimator. Do not silently mix the approaches.

Provenance is mandatory: explicitly fictional fixtures, public synthetic labels,
public human judgments and observed first-party events are distinct sources.
Unknown source provenance cannot be promoted to observed first-party evidence.
Counts alone do not verify source authenticity or label quality.

## Splits, comparators and statistical uncertainty

Freeze the protocol, dataset fingerprint, feature order, candidate model family,
regularization grid, maturity horizon, decision threshold and primary metric
before looking at the final test outcomes. Fit preprocessing on training data.
Use an earlier training period, a later validation/calibration period, and a
final untouched period with sufficient time for labels to mature. Predictions
must precede their evaluated outcome events. Repeatedly tuning against a test
set turns it into validation evidence.

Report returning and unseen candidate/vacancy cohorts separately. Group repeated
cycles, duplicate templates and linked entities when evaluating generalization
to new entities; a random row split can leak them across partitions. Strict
entity holdout and realistic temporal replay answer different questions and
should be named separately. The
[scikit-learn cross-validation guide](https://scikit-learn.org/stable/modules/cross_validation.html)
explains why dependent groups and time-ordered data need appropriate split
strategies rather than ordinary shuffled folds.

Compare on the same held-out observations and eligibility/retrieval universe:
the previous deterministic scorer/allocator, the improved deterministic version,
a training-only prevalence predictor, and the learned challenger. A prediction
model should improve on the prevalence reference; an allocator should be
compared using the same scores before crediting it with optimization gains.
Disclose coverage and exclusions, including missing feature snapshots and
unmatured rows. A model evaluated only where it can score must not conceal
performance or coverage of the complete deployed policy.

Publish point estimates, sample counts, positive counts and uncertainty. For
independent Bernoulli observations, a Wilson interval is preferable to reporting
a percentage without a range; the
[NIST interval guide](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)
also discusses exact intervals when counts are small. Repeated candidates,
vacancies, organizations, raters and market dates invalidate a naive independent
row interpretation. For policy/model differences, use paired resampling at the
declared independent experimental unit; account for crossed dependencies when
present. [Owen and Eckles](https://arxiv.org/abs/1106.2125) study bootstrap
reweighting for crossed-factor data. An iid row-bootstrap interval is only
descriptive when these dependencies have not been handled. Sparse cohorts and
one-class test partitions must be reported as insufficient for the affected
metrics, not assigned a perfect score.

## Metric definitions

For probability predictions, report Brier score and log loss, with the
training-only prevalence comparator scored on the same test rows. Lower is
better. Include a calibration table with the number of observations, mean
predicted probability and observed rate per prespecified bin; report test-set
base rate. Strictly proper scoring rules reward honest probability forecasts;
see [Gneiting and Raftery](https://doi.org/10.1198/016214506000001437).
Discrimination alone does not demonstrate calibration.
[Guo et al.](https://proceedings.mlr.press/v70/guo17a.html) distinguish confidence
calibration from classification performance. Calibration parameters, when used,
are fitted outside the final test period. A compatibility score of 0.8 remains
a utility score unless a valid target-specific probability model supports the
probability interpretation.

For ranking observed binary interest labels, report average precision with the
observed positive prevalence, precision at actual attention limits, and recall
only within a declared sufficiently labelled evaluation universe. ROC AUC may
be supplementary and is undefined when one class is absent. Accuracy at a 0.5
threshold can be high simply by always predicting the majority class.
[Saito and Rehmsmeier](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0118432)
explain the value of precision/recall analysis for imbalanced labels. Ranking
ties must be handled consistently. For human ordinal rankings use the existing
pairwise/top-choice/MRR protocol without inventing cardinal relevance gains.

For allocation, report objective gap versus an independent exhaustive oracle
on small cases, objectives against a fixed baseline on larger cases, runtime,
budget/fallback rate, issued/exposed volume and constraint violations. Do not
call an improved objective an accuracy gain. Nonlinear stipulated fill-risk
models also need scenario-coverage and assumption checks; they cannot certify
real employment reliability.

For actual deployed outcomes, measure mutual interest per exposed cycle,
decisions per mutual match, time to first mutual match, verified starts by
deadline and vacancy/candidate coverage, each with explicit denominators and
horizons. Report active and waiting attention, consent/eligibility violations,
blocked pairs and duplicate mutations as operational guardrails. Definitions
must remain fixed across comparisons.

## Selection effects and continued learning

The previous policy chose which pairs were exposed. Evaluating only observed
responses therefore measures predictive behavior under that exposure policy;
it does not estimate how every eligible pair would behave. Treating unseen
pairs as rejections makes the feedback loop reinforce earlier choices.
[Schnabel et al.](https://proceedings.mlr.press/v48/schnabel16.html) analyze this
selection problem. Logged action propensities can support counterfactual
evaluation only with suitable overlap and assumptions; a deterministic logger's
zero-probability actions have no evidence. Never invent propensities after the
fact. [Swaminathan and Joachims](https://www.jmlr.org/papers/v16/swaminathan15a.html)
show why propensity weighting and variance control matter for learning from
logged bandit feedback.

A future prospective comparison should prespecify its target, minimum useful
effect, randomization unit, stopping rule, maturity window and harm limits.
Because candidates compete across vacancies, per-pair randomization can create
interference; choose a market/time or otherwise justified unit and account for
its dependencies. Any exploration still requires eligible, consented pairs and
the existing attention ceilings. This is a proposed evaluation design, not a
claim that such an experiment has run.

Continued learning means collecting validated labels, fitting versioned candidate
artifacts and comparing them on later evidence. Automatic retraining is not
automatic proof of improvement. Retain a known deterministic fallback, reject
incompatible/nonfinite/malformed artifacts, record artifact and feature versions
in score traces, and avoid loading pickle or executable model content. Monitor
coverage, missingness, base rate, calibration and outcome drift on mature data.
If the data or required evidence is insufficient, publish that result and keep
the previous model; do not promote a synthetic model as observed hiring ML.
