# Hand-off for integrating R99 with actual TEN scheduler

## Non-negotiable behavior

- Keep actual v1 clearing, decision cards, timeout, cooldown, attention prices, and candidate-first/employer-first logic unchanged at first.
- R99 executes **read-only shadow evaluation**, never issuing a decision card, changing a role, or contacting a person.
- There is NO global personal desirability score. Recommendations are vacancy- and consent-context-specific. Payment status and protected audit attributes are excluded from matching signals.
- Treat the 99.9% metric as a research target, not a real-world claim. Do not show a confidence badge until a separate calibration and deployment validation standard exists.

## Adapter input (conceptual)

Provide: `market_timestamp`, hashed `state_version`, eligible candidate-job edges with validated qualification status, reciprocal probability model outputs plus uncertainty and model version, candidate opt-in status, competing live cards/availability, per-vacancy hiring authority and capacity, job-scoped risk factors, and precise authorization scopes/expiration for optional policy questions.

The shadow planner must produce: candidate/job IDs, ordered **proposed** reserve candidate IDs for each vacancy, conditional policy question proposals, scenario-conditioned modeled vacancy-fill risk, optimistic infeasibility reason codes, opportunity costs, and hash of input state. It cannot modify any real tables.

## State correctness

1. Filter out already hired, withdrawn, expired, and unavailable candidates/jobs before solving.
2. Preserve confirmed active cards and hire commitments; don't move them during swaps.
3. Validate all legal and operational hard requirements after any proposed repair, not only before it.
4. Require employer-scoped human authorization for every role version affected by clarification.
5. Require explicit candidate permission before sharing evidence with a particular company. Evidence reuse is not disclosure consent.
6. Use transactions/locks so two scheduler workers cannot promise the same candidate as an exclusive reserve.
7. Record every proposed but rejected action with score, reason, model version and deterministic state key for audit replay.
8. Inability to model shared risk or detect changing conditions must cause **abstention from a reliability claim**, not automatic display of 99.9%.

## Validation ladder

**Stage A: shadow parity.** Feed identical production-safe events into the actual TEN v1 scheduler, with and without R99 sidecar. Assert identical user-visible decisions and persistent state hashes. Apply zero R99 actions.

**Stage B: independent simulator.** On logged consent-compatible data or a defensible simulator, compare the actual v1 engine, global expected-fill allocation, risk-aware allocation, WITNESS planner, and post-allocation exchange. Same action budgets, deadlines and outcomes. Report coverage, fills, contacts, question costs, latency, utility and candidate welfare separately.

**Stage C: calibration.** Collect actual outcomes at all decision stages, pre-register a target population and time horizon, use time-separated train/calibration/evaluation sets, model correlated failure and non-random exposure, and attach confidence intervals to risk claims. A 99.9% claim should never be inferred from small, highly selected samples.

**Stage D: controlled human trial.** Employer opt-in to validated policies, candidate consent, prospective approval/qualification checks, accommodation paths, human override, audit of group-level and opportunity-level harms; turn off R99 on drift.

## What cannot be claimed

The current lab does not prove that a shortlist of six or ten candidates fills a vacancy with 99.9% real-world probability. It does not show superiority to a state-of-the-art matching algorithm. Even a model-based chance constraint can be invalid under misspecification; optimistic model bounds can only rule out feasibility within their assumptions.
