# Architecture — Risk-bounded, agreement-first hiring portfolios

## Target outcome

For each vacancy `j`, over a prespecified deadline `T` and cohort of enrolled jobs:

    P(actual employed start from the delivered shortlist by T) >= 0.999

This is a *target conditional probability*, not a demonstrated fact. Every enrolled vacancy must be included in denominator coverage even when no shortlist can be recommended. For job j, the shortlist S_j has variable size `0<=|S_j|<=K_j`. Candidate capacity is scarce and cannot be double-reserved.

Within an explicitly stipulated, partially observable scenario model:

    R_j(S) = q_j + (1-q_j) sum_z w_z prod_(i in S) [1 - p_ij(z)]

`q_j` is job-wide failure, `p_ij(z)` is conditional success, and `w_z` is the probability of a shared scenario. The formula assumes conditional independence after conditioning on z. Many real hiring failures violate it. Even with perfect candidate selection, `R_j(S)>=q_j`. If `q_j>0.001`, 99.9% is **impossible under that model** until the job-wide bottleneck is genuinely addressed.

An honest controller must be able to return `cannot_certify` without dropping the vacancy from the evaluation denominator.

## Four layers

1. **Eligibility and permissions.** Essential, role-validated requirements and voluntary candidate eligibility; employer authorizes exact roles/versions, never inferred from a related role. An ambiguous preference is not a hard exclusion. Audit protected data separately from scoring.
2. **Agreement state.** Candidate confirms terms, availability, and recipient-specific disclosure scope. Employer confirms authority, salary/conditions, and the job's exact rule set. An agreement-readiness proof is issued only if versions, hashes, consent, expiry, revocation, and evidence references match. These are pending prerequisites, **not** proof of actual employment.
3. **Market-wide optimizer.** Sparse reciprocal candidate retrieval, cross-employer capacity, chance-risk portfolio selection, bounded candidate exchanges, attention budgets and variable shortlist sizes. Old event-driven TEN scheduler remains an unchanged fallback.
4. **Contingent action compiler.** Compute conservative value of asking a permission question or requesting proof relative to a baseline that can already make introductions. Human responses are observed *after* charging their time. Conditional release of next candidate is scheduled based on results.

## Mathematical action value

    advantage(a) = E[future completed hiring value | take action a]
                   - E[future hiring value | continue baseline]
                   - employer_attention_cost(a)
                   - candidate_attention_cost(a)
                   - delay_cost(a)
                   - opportunity_cost(a)

`value_per_hire` represents an arbitrary experimental conversion of a completed match to attention units; this cannot be inferred from JTH. For real claims, expose a Pareto frontier over match value, candidate welfare, recruiter burden, time-to-hire and fairness, not a single opaque scalar.

## What has actually been implemented

- Global R99 sparse (in these small trials dense) expected-fill and tail-risk heuristics from the retained prior research package.
- Candidate exclusive reservations across jobs; no candidate can be simultaneously promised as an available reserve for two different employers.
- Early candidate-side check plus optional imperfect job-readiness check, charged by an explicit budget. A check has a stipulated 70% probability of detecting a modeled bad job-wide state and a 2% false-alarm probability; neither is empirical.
- Paired employer-first and candidate-first evaluation uses the *same* latent per-pair coins: `p_ij = sqrt(p_ij)*sqrt(p_ij)` is an invented factorization for an experimental stage-order comparison, not a real-world measured recruiter/candidate model.
- WITNESS prioritizes explicitly askable employer-policy adjustments; no actual approval, no permission change. Evidence still needs candidate opt-in and successful verification. Heuristic conservative variant discounts expected value.
- Versioned employer/candidate proof compilation with expiry, revocation, explicit recipient, and matched terms; a separate integration contract not exercised as real employment authorization.

## Robustness findings

- In the adversarial preauthorization-shift market, all model-threshold passes fail against the hidden scenario probabilities.
- In the deliberately low-success market, most vacancies remain unfilled within the short simulated process, even after preflight improves attention efficiency.
- The adaptive Bellman stage-order policy often selects candidate-first, matching the simpler PACT ordering in the tested settings. This is not evidence it has independently improved outcomes.
- WITNESS can add value when authorized employer adjustments genuinely alter feasible matching, but a question can be wasted. The guarded policy reduces questions and may miss some beneficial changes.

## Production reliability barrier

Before saying any vacancy is 99.9%-reliable: observe prospective job starts, adequate sample size and coverage, independent role/candidate state, external model calibration and drift, nonresponse/censoring, and competing offers. Confidence must be valid *after selecting the target vacancies* and under plausible common-cause risk. No finite algorithm can guarantee a future person's decision; exogenous job shutdown, changed terms, timing, and autonomy remain essential.

A naive binomial illustration requires 2,995 success out of 2,995 comparable, independent completed vacancy trials with zero failures to put a one-sided 95% lower bound at roughly 99.9%. Real cohorts have dependencies and selection and may need more evidence.
