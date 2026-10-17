# Career Kitchen matching implementation

The matching package is a pure Python planning boundary. It receives frozen,
sanitized snapshots and returns proposals. It has no database, storage, billing,
identity, messaging, network, or notification dependency. The authenticated service
builds snapshots; a separate transaction must recheck eligibility, live versions,
consent, and capacity before issuing a card. A proposal never grants access to
evidence, creates mutual interest, signs a policy, or records employment.

## Original routing and cold start

`score.score_v1(features, estimate, prices, now)` implements the legacy formulas:

```text
r = p_interview * p_offer * p_accept
s = candidate_survival * vacancy_survival
V_C = a0 * bC * r * s
V_E = b0 * aE * r * s
G_C = V_C - (mu_C + a0 * mu_E) - a0 * job_congestion
G_E = V_E - (mu_E + b0 * mu_C) - b0 * candidate_congestion
```

The four interest predictions remain separate. The downstream target is offer
acceptance, with legacy quality fixed to one. It is not a verified employment start.
All probabilities are supplied by the caller, finite, bounded in `[0,1]`, versioned,
and unavailable if their cutoff lies in the future. This package trains no model and
contains no default response, acceptance, or employment probabilities.

`baseline.HeuristicPairScorer` provides the cold-start route when no forecast is
supplied. Its trace is explicitly `NONPROBABILISTIC`. It combines four disclosed,
versioned relevance weights: skills `.4`, experience `.25`, work mode `.25`, and
authorized evidence alignment `.1`. These are engineering routing weights, not
empirical coefficients or an employability score. Without a response model it
charges immediate decision attention plus receiving-side congestion; it cannot
calculate an expected second decision or funnel probability. This separate fallback
avoids putting invented numbers into the legacy probability interface.

`baseline.plan_baseline` ranks positive-surplus proposals deterministically, chooses
the better direction, and respects each selected active cap in `1..10`, current
active usage, waiting limits, and existing pair cycles. Unknown capacity means no
proposal. It defers when the chosen first mover has no slot. It never fills a quota
or moves an active decision. Call it again after committed events to replenish.

`attention.update_price` and `update_congestion` preserve the original adaptive
dual update, with configurable clamps:

```text
g = (observed_load - processing_capacity) / max(processing_capacity, 1)
H_next = H + g*g
price_next = clamp(price + g / sqrt(H_next + 1), minimum, maximum)
```

Prices use routing value units. Learned empirical prices and calibration remain
deployment work. Narrow-market hierarchical price backoff belongs in the snapshot
builder, which has access to market-cell counts.

The persistent worker applies the dual update to `MarketPrice` once per
`MARKET_PRICE_WINDOW_SECONDS` (default 900 seconds). Its measured allocation load
is the actual count of issued decision cards in the half-open control window. Its
capacity estimate is currently free user-selected slots plus completed decisions
in that window; candidate occupied slots are counted globally. This is an explicit
engineering capacity rule, not a measured optimal economic model. The event stores
the window, observed counts, controller version, clamps, and new entity version;
stored `candidate_h` / `employer_h` preserve the gradient history across restarts.
`MARKET_PRICE_MAX` and `CONGESTION_PRICE_MAX` default to ten routing units. No field
depends on subscription spending. Market families with overlapping candidate pools
share physical attention; the executor's global candidate cap remains authoritative.

Entity congestion is also persisted, independently for each candidate and vacancy,
in `CongestionPrice`. For its control window, `L` is the actual number of active
decision cards plus hidden waiting items; `C` is the selected active cap plus
resolved decisions. The same `g/H/sqrt(H+1)` legacy update adjusts `lambda` or
`kappa`, clamps at `CONGESTION_PRICE_MAX`, records exact counts and versions, and
retains `gradient_h` across restarts. Oldest/uncontrolled scopes are visited first
in bounded batches. Price updates never assume acceptance or verified employment.
The live baseline and shadow snapshot consume these persisted prices.

## Eligibility and retrieval

`retrieval.hard_feasible(EligibilitySnapshot(...))` returns `ELIGIBLE`, `INELIGIBLE`,
or `NEEDS_HUMAN_CLARIFICATION`. An ambiguous requirement produces clarification,
while essential eligibility, blocks, lawful authorization, salary compatibility,
availability, safety restrictions, and closed cycles remain hard gates.

`SanitizedPairFeatures` admits only named, derived, job-related alignment values,
IDs, provenance, and eligibility booleans. It contains no compensation floor,
demographic data, arbitrary dictionaries, raw evidence, private messages, payment,
or background checks. Employer responses must still redact internal score traces.
No structural schema alone can prove a feature is lawful: source permissions,
job-relatedness, proxy review, and tenant scoping remain service responsibilities.

`sparse_retrieve` bounds top-k selection from an already authorized query stream;
it never constructs a candidate-by-vacancy matrix. The database must perform indexed
structured filtering and bound queries before calling it. Production embeddings,
ANN retrieval, duplicate-account resolution and measured recall are not fabricated
by this helper.

## R99 research models and minimum shortlists

`scenario.ScenarioModel` contains caller-supplied weighted scenarios. A scenario
contains candidate conditional success probabilities and a common vacancy failure:

```text
failure(S) = sum_z weight_z * [q_z + (1-q_z) * product_i_in_S(1-p_i_z)]
```

The formula is valid only under explicitly asserted conditional independence after
conditioning on the supplied scenario. Missing candidate probabilities, absent
models, or unsupported dependence return unknown. Unknown never becomes zero or an
independence estimate. The robust upper failure is the maximum across supplied
plausible models; this is model ambiguity robustness, not a statistical confidence
bound. A common failure of `.005` precludes modeled `.999` fill regardless of the
number of candidates.

`optimistic_feasibility_bound` gives each scenario an ideal oracle selecting its own
best candidates without competition. Exceeding the risk threshold establishes
`MODEL_INFEASIBLE_EVEN_WITH_ORACLE`; passing proves neither a common shortlist nor
real-world feasibility.

`independent_minimum_n` provides the equal-probability mathematical illustration
with an explicit hard search cap: `.5` requires ten, `.9` requires three for `.999`.
These are stipulated inputs, not hiring forecasts. `minimum_feasible_shortlist`
enumerates increasing cardinalities for a small sparse pool and proves minimum
cardinality only after checking every smaller subset. Budget exhaustion abstains.

The active-card cap is separate from the cumulative delivery count. Research plans
have an explicitly supplied shortlist limit that may exceed ten for sequential
release. There is no automatic requirement to recommend ten people.

## Global allocation, fixed commitments and exchanges

`portfolio.allocate_global(MarketSnapshot(...))` greedily selects marginal aggregate
fill gains less separately supplied attention and delay costs. In the absence of
scenario models, it uses caller-supplied routing values and reports unknown fill.
It then searches bounded moves, swaps, and a two-vacancy augmenting path with one
refill. Finally it removes contingent candidates that are redundant to an achieved
modeled threshold and orders remaining proposals by marginal modeled value.

This is a sparse, budgeted heuristic. It does not claim global optimality or minimal
cardinality for the whole market. Longer augmenting paths, large-scale min-cost
flow and richer Pareto policies can later implement the same interface.

Each newly planned candidate consumes at most one hypothetical market capacity.
Plans are soft contingent proposals; this does not authorize actual exclusive
reservation. `ACTIVE_DECISION`, `MUTUAL`, and consented exclusive commitments remain
fixed. Conflicting live soft commitments are preserved but affected fill estimates
become unknown; the planner cannot count a shared fallback as available to both.
Actual reservations still require explicit candidate permission, expiry, and the
database uniqueness/locking guards.

All vacancies remain in output, including empty and model-infeasible vacancies.
Coverage and aggregate modeled fills are separate diagnostics. No aggregate fill
number is returned if any vacancy has unknown risk. This implementation models
at-least-one start per vacancy; multi-opening completion probabilities need a
separate count-distribution model. `openings_remaining` gates releases but does not
turn at-least-one probability into an all-openings claim.

## WITNESS and adaptive exposure

`witness.DependencyDAG` represents AND prerequisites and OR alternatives, rejects
cycles, and verifies attempted outcome order. An evidence check must follow an
explicit consent for that candidate, evidence claim, recipient organization, and
exact role versions. Essential requirements cannot be relaxed. Questions require
explicit employer question-process opt-in and a preference/ambiguous classification.
A question's approval still must be obtained later from the authorized signatory.

`WitnessCertificate` requires complete, caller-supplied modeled outcome weights.
It compares complete conditional continuation value against the baseline; no
probability is invented when a response model is absent. Complementary employer
approval, candidate consent and evidence can therefore be valued as a bundle.
Denied questions still consume their attempted attention cost. Every possible
modeled path must fit candidate, employer and total intervention budgets. Stale
scope, impossible prerequisites or nonpositive conservative advantage abstain.
`compile_witnesses` ranks supplied lawful bundles; production question wording,
independent evidence acquisition and automated bottleneck-to-policy enumeration
are service integrations, not simulated approvals.

`action_policy.propose_next_action` always preserves baseline behavior in BASELINE
and SHADOW. PILOT may select a positive conservative-advantage proposal only when
the state and scoped pilot authorization match. It returns a proposal only.
`next_release` checks fresh state, deadline, remaining openings, delivery budget,
recipient capacity, and current eligibility/consent before returning one next
introduction. Every response, expiry, partial fill or revocation requires a fresh
snapshot. Employer-visible delivery is counted only after the executor commits
that actual disclosure. Candidate-side attempts must be counted separately.

## Shadow and reliability barriers

`shadow_adapter.run_shadow` receives the already committed baseline output and an
immutable market copy. It receives no write or contact capability. Disabled flags,
exceptions, edge limits, operation limits, and wall-clock timeouts return the exact
same baseline proposal tuple/hash. Experimental results remain internal research.
The wall-clock limit is cooperative between bounded operations, so it is not a
hard process-level cancellation guarantee for arbitrarily large external model
objects. Input schemas and deployment workers must also bound model sizes.

`reliability.can_issue_reliability_claim` always returns `CANNOT_CERTIFY` in this
deployment. Self-asserted booleans, synthetic trials, model thresholds, and small
selected samples cannot authenticate independent prospective validation. A future
independent validation authority must verify employment starts, joint calibration,
selection-valid confidence intervals, population coverage, drift, policy versions,
and compliance approval before any replacement gate can issue a statement.

`calibration` supplies temporal filtering, Brier loss and log loss only. It excludes
records whose earliest evidence is already interview/offer, rejects future features,
and distinguishes offer acceptance from independently verified start. It is not a
training pipeline, calibration report, or empirical validation result.

## Reproducible verification

Run from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests/algorithm -q
.venv/Scripts/python.exe -m ruff check apps/api/app/matching apps/api/tests/algorithm
.venv/Scripts/python.exe -m mypy apps/api/app/matching
```

The deterministic tests exercise exact legacy formulas and prices, both directions,
lower caps, empty capacity, common-failure floors, scenario correlation, minimum
cardinality, a cross-employer greedy counterexample, fixed commitments, WITNESS
dependencies/denial/budgets, stale state, release limits, shadow parity, wall-clock
fallback, forbidden dependencies and fail-closed claims. These fixtures validate
implementation properties. They are not benchmarks or evidence of hiring efficacy.
