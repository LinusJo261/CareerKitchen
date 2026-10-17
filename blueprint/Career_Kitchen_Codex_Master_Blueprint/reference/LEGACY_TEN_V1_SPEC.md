---
title: "TEN v1 - Product & Technical Specification"
subtitle: "Codex Implementation Blueprint"
author: "Design specification generated from the frozen TEN v1 product architecture"
date: "2026-09-28"
geometry: margin=0.72in
toc: true
toc-depth: 3
numbersections: true
fontsize: 10pt
papersize: letter
colorlinks: true
linkcolor: NavyBlue
urlcolor: NavyBlue
---

# Document status and build contract

**Status:** TEN v1 conceptual design is frozen for implementation. This document is the normative source of truth for the first product build. Real-world causal validation, production calibration, and patentability conclusions are explicitly **deferred** and must not be fabricated or assumed by the implementation.

**Purpose:** This specification is written so that Codex, another software engineer, or a small engineering team can build the product without repeatedly redesigning the core mechanism. Where a parameter cannot be known before real usage, this document defines a configurable default or an interface rather than pretending the value is empirically settled.

**Normative language:**

- **MUST / SHALL**: required for TEN v1 to conform to the product design.
- **MUST NOT / SHALL NOT**: prohibited behavior.
- **SHOULD**: strongly preferred unless an implementation constraint is documented.
- **MAY**: optional capability compatible with the architecture.
- **DEFERRED**: intentionally outside the initial implementation or impossible to validate before deployment.

## 0.1 Codex non-negotiables

Codex MUST preserve the following invariants even if implementation details differ:

1. TEN is **not an open application board**. Candidates cannot submit unlimited applications to arbitrary vacancies through TEN.
2. TEN is **not an infinite-scroll recommendation feed**. Candidate and employer decision surfaces are bounded.
3. A candidate may have at most **10 active decision cards** at one time across the platform.
4. An employer may have at most **10 active candidate decision cards per vacancy** at one time.
5. "10" is a maximum attention surface, not a requirement to show bad recommendations and not a lifetime limit.
6. The system is event-driven and replenishes empty decision slots only when a positive-value interaction exists.
7. The system can initiate an interaction from either side. It MUST NOT permanently hard-code "candidate applies first" or "employer recruits first."
8. There is **no public global candidate score, percentile, ELO, desirability number, or employability rank**.
9. Paying TEN MUST NOT buy ranking priority, candidate priority, or preferential allocation.
10. Candidate use is free in v1. Employers fund the product through subscriptions, active-role capacity, enterprise tooling, or integrations.
11. Candidate and employer decisions MUST be separated from protected-attribute audit data.
12. The matching system MUST be auditable: every exposure must be reconstructable from a model/version, feature snapshot, ruleset, prices, and timestamp.
13. Background screening is not a core matching signal and MUST NOT be silently folded into ranking.
15. Real-world performance claims are DEFERRED until a real replay or pilot is performed.

## 0.2 The one-sentence product definition

> **TEN is an event-driven two-sided labor-market clearing system that allocates bounded human attention to candidate-job pairs, dynamically chooses which side should move first, and minimizes human decisions per successful hire while preserving hiring value.**

## 0.3 Product thesis

Traditional job boards make a huge search space easier to navigate. TEN attempts to make most of that search unnecessary.

The central research and product objective is:

$$
\min_{\pi} \; D_C(\pi) + D_E(\pi)
$$

subject to

$$
V(\pi) \ge (1-\varepsilon)V^*,
$$

where:

- $\pi$ is the clearing policy,
- $D_C$ is candidate human decisions,
- $D_E$ is employer human decisions,
- $V(\pi)$ is realized hiring value under TEN,
- $V^*$ is the best achievable reference value under a much less attention-constrained process,
- $\varepsilon$ is the acceptable value loss.

TEN therefore optimizes **attention compression subject to hiring-value preservation**, rather than clicks, applications, time-on-site, or feed engagement.

# 1. Product principles

## 1.1 Finite consideration

Human attention is treated as a scarce system resource. Every recommendation consumes attention and therefore carries a cost. The system should prefer fewer, better-timed interactions over large candidate pools or large job feeds.

**TEN-INV-001:** Candidate active decision count SHALL never exceed 10.

**TEN-INV-002:** Employer active decision count SHALL never exceed 10 per vacancy.

**TEN-INV-003:** The clearing engine SHALL leave capacity unused when no candidate-job interaction has positive expected net value.

## 1.2 Double opt-in

A candidate and employer only become a mutual TEN match after both sides independently express interest.

A first-mover "Interested" decision does not by itself create a mutual match. It changes the state so the second mover may be asked to decide.

## 1.3 Direction is a control variable

The platform may ask the candidate first or the employer first for a given pair. Direction is selected using predicted mutual outcome value, attention scarcity, queue congestion, time urgency, and uncertainty.

## 1.4 Unknown is not bad

Cold-start or poorly measured participants must not be treated as low quality solely because the model lacks evidence. The system requires controlled exploration and explicit uncertainty.

## 1.5 Evidence over opaque scores

Candidates may present verified evidence of skill, education, work, portfolio, or credential claims. Employers see relevant evidence and fit explanations, not a mysterious global score.

## 1.6 Reciprocal accountability

Employers are not exempt from measurement. TEN records objective process behavior such as response timeliness, completion rate, salary consistency, verified-opening status, and cancellation/ghosting behavior. These signals inform candidate-facing trust displays and internal allocation where appropriate.

## 1.7 Monetization cannot corrupt allocation

No amount of employer payment may directly increase a pair score, remove an attention penalty, bypass feasibility constraints, or displace a higher-value organic interaction.

# 2. Scope, non-goals, and deferred work

## 2.1 In scope for TEN v1

TEN v1 includes:

- candidate registration, profile, preferences, availability, and evidence;
- employer organization creation, verification, team membership, and permissions;
- vacancy creation with structured requirements and compensation;
- hard feasibility filtering;
- semantic/structured retrieval of plausible pairs;
- directional probability estimation through a stable scorer interface;
- attention and congestion accounting;
- event-driven clearing and active-decision allocation;
- candidate-first and employer-first interaction flows;
- double opt-in mutual matching;
- post-match messaging and lightweight scheduling;
- recruitment-stage tracking through interview, offer, accepted, rejected, withdrawn, and closed;
- explanation generation;
- candidate and employer reliability/trust signals;
- verification status and evidence management;
- notifications;
- audit trails;
- admin/support tooling;
- privacy, deletion, and data export;
- analytics and north-star metrics;
- fairness/audit infrastructure separated from ranking;
- billing boundaries that never affect rank;
- a replaceable heuristic scorer for cold-start deployment;
- interfaces for later learned models.

## 2.2 Explicit non-goals

TEN v1 SHALL NOT attempt to become:

- a full ATS;
- payroll or HRIS;
- employee onboarding software;
- benefits administration;
- a social network;
- a public resume directory;
- an unrestricted recruiter search database;
- an unrestricted job application board;
- a personality-test product;
- an emotion/face/voice-analysis hiring tool;
- a background-check provider;
- a credit-scoring product;
- a global human ranking system;
- a pay-to-play marketplace;
- an ad auction that changes recommendation order;
- a gig-work dispatch marketplace;

## 2.3 Deferred because real usage is required

The following are not design gaps. They require deployment evidence and are intentionally deferred:

- final calibrated probability models;
- definitive attention-price dynamics;
- optimal active-set size below the cap of 10;
- exact exploration frequency;
- causal measurement of reduced applications per hire;
- causal measurement of hire quality or retention;
- market-specific fairness thresholds;
- final pricing levels;
- final SLA defaults;
- patentability or freedom-to-operate conclusions.

All such values MUST live behind configuration or replaceable interfaces where practical.

# 3. Actors and permission model

TEN has seven logical actor types.

## 3.1 Candidate

A candidate can:

- maintain a private structured profile;
- maintain preferences and hard constraints;
- upload evidence and a resume;
- set availability and pause matching;
- receive no more than 10 active decision cards;
- choose Interested or Pass;
- see outbound-interest status without repeated decision prompts;
- receive employer-initiated opportunities;
- enter messaging only after a mutual match;
- track interviews/offers;
- block organizations;
- hide from selected employers, including a current employer;
- export or delete personal data.

A candidate cannot:

- browse and submit unlimited applications;
- pay for higher ranking;
- see another candidate's ranking or score;
- message recruiters before mutual interest unless the product later adds an explicitly audited exception.

## 3.2 Recruiter

A recruiter belongs to an organization and can, subject to permissions:

- create/manage vacancies;
- view TEN-selected candidate decision cards per vacancy;
- choose Interested or Pass;
- see match explanations and verified evidence;
- message mutual matches;
- update process stages;
- record offers and disposition;
- invite organization teammates.

Recruiters cannot query a public unrestricted candidate database in v1.

## 3.3 Hiring manager

A hiring manager is an organization member with vacancy-level access. They may participate in candidate decisions and interviews but may not have organization administration or billing privileges.

## 3.4 Organization administrator

Can manage:

- legal/company profile;
- verified domains;
- team membership and roles;
- billing;
- integrations;
- data-retention settings where supported;
- organization-level trust/security settings.

## 3.5 Verification operator

A constrained role that can review verification artifacts and mark claims verified, rejected, expired, or requiring more evidence. This role MUST NOT have arbitrary access to matching internals unless separately authorized.

## 3.6 Support/compliance auditor

May inspect audit trails and user-reported issues. Sensitive access MUST be logged and purpose-limited.

## 3.7 System administrator

Technical role for platform operation. Production access should be break-glass, logged, and minimized.

# 4. Core domain concepts

## 4.1 Candidate profile

A candidate profile is a structured private representation containing:

- identity/contact;
- location and work-mode preferences;
- work authorization eligibility as a structured qualification, without unnecessary document exposure;
- desired role families;
- seniority range;
- compensation floor/target and currency;
- availability date/status;
- experience history;
- education;
- skills;
- certifications/licenses;
- portfolio/projects/publications where relevant;
- verification/evidence references;
- company blocks and privacy exclusions;
- candidate-side hard constraints;
- optional resume attachment.

## 4.2 Vacancy

Every active vacancy MUST have enough structure to support meaningful feasibility filtering. Minimum required fields:

- organization;
- title;
- internal occupation cluster;
- description;
- employment type;
- seniority band;
- location/work mode;
- compensation range and currency;
- required work authorization condition if applicable;
- must-have requirements;
- preferred requirements;
- skill requirements with importance;
- opening count;
- target start date if known;
- hiring process outline;
- vacancy capacity/owner;
- active/paused/closed state.

TEN SHOULD require compensation disclosure for all roles because hidden compensation creates avoidable mismatch and wasted attention.

## 4.3 Pair

A candidate-vacancy pair is the atomic object scored by the clearing system. A pair may be infeasible, eligible, queued, exposed to one side, waiting for the other side, mutually matched, or closed.

The same candidate-vacancy pair can re-enter only through a new **interaction cycle** after a meaningful state change or cooldown. The system MUST NOT repeatedly nag users with the same pair.

## 4.4 Active decision

An active decision is a card currently requiring a human answer.

Only these states consume the TEN cap:

- `CANDIDATE_DECISION_REQUIRED`
- `EMPLOYER_DECISION_REQUIRED`

Sent interest, waiting status, mutual matches, interviews, and archived items appear in separate UI sections and do not count toward the active-decision cap.

## 4.5 Mutual match

A mutual match exists only after both parties select Interested for the same interaction cycle.

Mutual matching unlocks:

- direct messaging;
- scheduling;
- contact exchange according to privacy settings;
- interview/process tracking.

## 4.6 Market cell

Attention scarcity is not globally uniform. TEN partitions the labor market into hierarchical market cells, e.g.:

1. occupation/job-family cluster;
2. geography or remote region;
3. seniority band;
4. employment type.

A cell might conceptually be:

`Photonics Engineering | Seattle Metro | Entry-Junior | Full-time`

Cells require fallback hierarchy when sparse. Price estimates should back off from narrow cells to broader parents rather than become unstable.

# 5. System invariants

The following invariants MUST be enforced at both application and database/transaction boundaries where feasible.

**TEN-INV-010:** Candidate active decisions <= 10.

**TEN-INV-011:** Active employer decisions for one vacancy <= 10.

**TEN-INV-012:** A pair cycle cannot simultaneously require decisions from both sides.

**TEN-INV-013:** Messaging cannot begin before mutual match.

**TEN-INV-014:** A passed pair cycle cannot become mutual without a new cycle.

**TEN-INV-015:** Closing a vacancy invalidates all active decisions for that vacancy.

**TEN-INV-016:** Pausing/deactivating a candidate invalidates or suspends candidate-visible decisions according to policy.

**TEN-INV-017:** Ranking functions cannot read billing-plan priority or ad-spend fields.

**TEN-INV-018:** Ranking services cannot read protected-attribute audit tables.

**TEN-INV-019:** Every exposure has an immutable audit record.

**TEN-INV-020:** Reprocessing an event is idempotent.

**TEN-INV-021:** One human decision produces at most one state transition for a specific decision token.

**TEN-INV-022:** An expired decision cannot be answered after expiry without issuance of a new decision token.

**TEN-INV-023:** A job cannot expose a candidate if hard feasibility is false at exposure time.

**TEN-INV-024:** The product must not synthesize a global employability score from stage outcomes.

# 6. End-to-end candidate journey

## 6.1 Candidate onboarding

1. Create account and verify email.
2. Consent to platform terms/privacy.
3. Create candidate profile.
4. Import resume optionally; parser proposes structured fields but candidate confirms them.
5. Select desired roles/occupation clusters.
6. Set location/work-mode preferences.
7. Set compensation floor/target privately.
8. Set availability.
9. Add skills and evidence.
10. Optional identity/education/employment verification.
11. Choose organizations to block/hide from.
12. Activate matching.

Activation MUST be impossible until minimum completeness rules pass.

## 6.2 Candidate opportunity inbox

The candidate sees a bounded section:

`Active decisions: N / 10`

Each card contains:

- job title;
- company;
- compensation range;
- location/work mode;
- verified employer status;
- concise reason surfaced;
- major requirement alignment;
- known first-mover context, e.g. "Employer already expressed interest";
- expiration/decision deadline;
- Interested / Pass actions.

The candidate does not see a normalized match percentage unless later research demonstrates it improves decisions without false precision.

## 6.3 Candidate Interested

If candidate is first mover:

- candidate active-decision card closes;
- interaction transitions to `CANDIDATE_INTEREST_SENT`;
- if employer has decision capacity, employer decision is issued;
- otherwise interaction enters `WAITING_EMPLOYER_SLOT` and contributes to job congestion/backlog.

If candidate is second mover after employer interest:

- choosing Interested creates a mutual match immediately;
- choosing Pass closes the cycle.

## 6.4 Candidate Pass

Pass closes the current cycle. Optional structured reason can be collected for model/debugging:

- compensation;
- location/work mode;
- role content;
- seniority;
- company preference;
- timing;
- requirement mismatch;
- other/no reason.

Reason is private by default. Do not expose raw rejection reasons to the other party.

## 6.5 After mutual match

Candidate moves from the active-decision surface to a Match workspace:

- chat;
- scheduling;
- process stage;
- interview details;
- offer details if entered;
- withdraw action;
- report/block action.

# 7. End-to-end employer journey

## 7.1 Organization onboarding

1. Recruiter signs up.
2. Organization created or joined.
3. Work email/domain verified.
4. Organization administrator established.
5. Company details entered.
6. Billing configured before paid capacity is used.
7. Optional legal-entity verification.

## 7.2 Vacancy creation

The vacancy wizard MUST collect the structured minimum listed in Section 4.2.

Before activation, system runs validation:

- compensation lower <= upper;
- currency valid;
- title and description present;
- no prohibited discriminatory hard filters;
- at least one owner;
- opening count >= 1;
- work-mode/location coherent;
- must-have requirements machine-readable where possible.

## 7.3 Employer candidate inbox

Per vacancy:

`Active candidate decisions: N / 10`

Candidate card includes:

- name or privacy-preserving identity according to product policy;
- relevant experience;
- skill/evidence alignment;
- compensation alignment indicator, not candidate's exact private floor unless candidate chose to reveal it;
- location/work authorization alignment;
- verification badges;
- concise "Why TEN surfaced this candidate" explanation;
- whether candidate already expressed interest;
- decision deadline;
- Interested / Pass.

## 7.4 Employer Interested

If employer is first mover:

- employer decision closes;
- interaction becomes `EMPLOYER_INTEREST_SENT`;
- candidate decision is issued when capacity permits;
- if candidate active-decision capacity is full, state becomes `WAITING_CANDIDATE_SLOT`.

If employer is second mover after candidate interest:

- Interested immediately creates mutual match.

## 7.5 Employer Pass

Closes current pair cycle. Optional structured reason is stored privately and is never directly converted into a candidate skill downgrade.

## 7.6 Vacancy closure

Closing/filling a vacancy:

- prevents new allocations;
- expires active decisions;
- resolves waiting interactions with `JOB_CLOSED`;
- requires disposition of existing mutual matches where possible;
- preserves audit history.

# 8. Mathematical model

## 8.1 Hard feasibility

For candidate $i$, vacancy $j$, time $t$:

$$
F_{ij}(t) \in \{0,1\}.
$$

`F=0` means the pair cannot be allocated. Hard feasibility may include:

- candidate blocked the organization;
- vacancy not active;
- candidate not active;
- incompatible employment type;
- required location incompatible with candidate's hard constraint;
- compensation band below candidate hard floor;
- required license/certification absent when truly mandatory;
- required work-authorization condition not satisfied;
- duplicate/cooldown rule;
- explicit organization block;
- administrative/safety restriction.

Hard filters SHOULD be kept intentionally small. Requirements that are preferences rather than truly mandatory belong in scoring, not feasibility.

## 8.2 Direction-dependent interest

TEN models four distinct probabilities:

$$
a^0_{ij}=P(C=1\mid\text{candidate sees job cold}),
$$

$$
a^E_{ij}=P(C=1\mid\text{candidate knows employer is interested}),
$$

$$
b^0_{ij}=P(E=1\mid\text{employer sees candidate cold}),
$$

$$
b^C_{ij}=P(E=1\mid\text{employer knows candidate is interested}).
$$

The superscript denotes context, not exponentiation.

These probabilities must be modeled separately because the information that the other side has already expressed interest can materially change behavior.

## 8.3 Downstream funnel

For mutually interested pair:

$$
p^I_{ij}=P(\text{interview}\mid\text{mutual}),
$$

$$
p^O_{ij}=P(\text{offer}\mid\text{interview}),
$$

$$
p^A_{ij}=P(\text{acceptance}\mid\text{offer}).
$$

Optional later-stage retention/satisfaction can be added behind a versioned interface, but v1 must not invent it without data.

Define:

$$
R_{ij}=p^I_{ij}p^O_{ij}p^A_{ij}.
$$

For v1, conditional quality value $Q_{ij}=1$. Thus the system optimizes accepted-hire probability, not an opaque "employee quality" label.

## 8.4 Time/survival

Let:

$$
S_C(i,t)=P(\text{candidate remains actionable long enough}),
$$

$$
S_J(j,t)=P(\text{vacancy remains actionable long enough}).
$$

Then:

$$
S_{ij}(t)=S_C(i,t)S_J(j,t).
$$

Initial implementation MAY use a simple monotonic urgency function rather than learned survival, but it must implement the same interface.

## 8.5 Expected gross value by direction

Candidate first:

$$
V^{C\to E}_{ij}=F_{ij}a^0_{ij}b^C_{ij}R_{ij}S_{ij}.
$$

Employer first:

$$
V^{E\to C}_{ij}=F_{ij}b^0_{ij}a^E_{ij}R_{ij}S_{ij}.
$$

## 8.6 Attention prices

Let:

- $\mu_C(m,t)$ = marginal price of candidate attention in market cell $m$,
- $\mu_E(m,t)$ = marginal price of employer attention in market cell $m$.

Candidate-first expected attention cost:

$$
A^{C\to E}_{ij}=\mu_C + a^0_{ij}\mu_E.
$$

Employer-first expected attention cost:

$$
A^{E\to C}_{ij}=\mu_E + b^0_{ij}\mu_C.
$$

## 8.7 Congestion/backlog penalties

Let $\lambda_j$ be vacancy-side congestion and $\kappa_i$ candidate-side inbound congestion.

Candidate-first adds expected vacancy backlog approximately proportional to candidate interest:

$$
C^{C\to E}_{ij}=a^0_{ij}\lambda_j.
$$

Employer-first adds expected candidate inbound backlog:

$$
C^{E\to C}_{ij}=b^0_{ij}\kappa_i.
$$

## 8.8 Net allocation surplus

$$
G^{C\to E}_{ij}=\mathbb{E}[V^{C\to E}_{ij}]-A^{C\to E}_{ij}-C^{C\to E}_{ij},
$$

$$
G^{E\to C}_{ij}=\mathbb{E}[V^{E\to C}_{ij}]-A^{E\to C}_{ij}-C^{E\to C}_{ij}.
$$

Direction:

$$
d^*_{ij}=\arg\max_{d\in\{C\to E,E\to C\}}G^d_{ij}.
$$

A pair is eligible for exposure only if the best direction has positive surplus and the first mover has capacity.

## 8.9 Exploration

Models must return uncertainty/posterior information where available.

Exploit slots rank using expected net surplus.

A configurable exploration budget MAY use posterior sampling:

$$
\widetilde{V}_{ij}\sim P(V_{ij}\mid D)
$$

and compute the same surplus using the sampled value.

Initial v1 default:

- maximum exploration allocation: 1 of 10 active decisions per actor scope;
- never override hard feasibility;
- never expose obviously negative-value pairs solely for exploration;
- exploration status is internal and not shown as a user stigma.

The rate MUST be configurable.

# 9. Attention-price controller

## 9.1 Capacity definition

For each market cell over a rolling control interval, define candidate and employer decision capacities. Capacity represents how many new decision cards can be responsibly introduced without creating persistent backlogs.

Inputs MAY include:

- number of active users;
- current open decision slots;
- median response time;
- expiration rate;
- hidden waiting backlog;
- vacancy hiring capacity;
- recent decision completion throughput.

## 9.2 Scale-adaptive dual update

For side $s\in\{C,E\}$:

$$
g_s(t)=\frac{A_s(t)-B_s(t)}{\max(B_s(t),1)},
$$

$$
H_s(t)=\sum_{\tau\le t}g_s(\tau)^2,
$$

$$
\mu_s(t+1)=\left[\mu_s(t)+\frac{g_s(t)}{\sqrt{H_s(t)+1}}\right]_+.
$$

This avoids a fixed learning-rate dependency in the conceptual controller. Production may use bounded/clipped variants for stability.

## 9.3 Vacancy congestion update

For vacancy $j$:

$$
g_j(t)=\frac{L_j(t)-C_j(t)}{\max(C_j(t),1)},
$$

$$
\lambda_j(t+1)=\left[\lambda_j(t)+\frac{g_j(t)}{\sqrt{1+\sum_{\tau\le t}g_j(\tau)^2}}\right]_+.
$$

Here $L_j$ is pending/expected employer-side load and $C_j$ is processing capacity.

Candidate-side inbound congestion $\kappa_i$ can be updated analogously from hidden inbound wait queues and active candidate decision capacity.

## 9.4 Safety bounds

All online prices MUST have configured min/max clamps and observability. A software or data bug must not drive prices to infinity and freeze a market.

# 10. Retrieval architecture

The clearing engine must never score every candidate against every job in a large market.

Retrieval is a two-stage process.

## 10.1 Stage A: hard-filter retrieval

Use indexed structured constraints to remove infeasible pairs.

Examples:

- active status;
- occupation family;
- work mode;
- geography radius/region;
- employment type;
- compensation overlap;
- work authorization;
- required credentials.

## 10.2 Stage B: approximate relevance retrieval

Retrieve a manageable pool using:

- title/occupation embedding similarity;
- skill overlap;
- experience/seniority similarity;
- industry/domain similarity;
- prior preference signals;
- optional portfolio semantic similarity.

Reference v1 stack: PostgreSQL + `pgvector` plus structured indexes. Do not introduce Elasticsearch/vector infrastructure until needed.

## 10.3 Candidate pool size

`retrieval_pool_size` is a configuration parameter, not a product invariant. A default of 100-300 plausible candidates/jobs per affected actor is reasonable for initial engineering, but MUST be tunable and benchmarked.

## 10.4 Retrieval recall audit

Because the ranking engine can only select retrieved pairs, retrieval quality must be monitored independently. Offline tests should report whether known positive interactions are present in top-N retrieval before evaluating final ranking.

# 11. Scoring architecture

## 11.1 Stable scorer interface

The clearing controller SHALL depend on an interface, not a specific model implementation.

```python
class PairScorer(Protocol):
    def score(self, candidate_id: UUID, vacancy_id: UUID, context: ScoreContext) -> PairScore:
        ...
```

`PairScore` MUST include at least:

```python
class PairScore(BaseModel):
    feasible: bool
    p_candidate_cold: float
    p_candidate_after_employer_interest: float
    p_employer_cold: float
    p_employer_after_candidate_interest: float
    p_interview_given_mutual: float
    p_offer_given_interview: float
    p_accept_given_offer: float
    survival_probability: float
    uncertainty: dict[str, float]
    feature_snapshot_id: UUID
    model_bundle_version: str
    explanation_factors: list[ExplanationFactor]
```

All probabilities must be in `[0,1]` and validated.

## 11.2 Heuristic cold-start scorer

Before TEN owns enough first-party data, a deterministic/interpretable scorer implements the interface.

It may use:

- compensation overlap;
- location/work-mode compatibility;
- hard requirement coverage;
- skill overlap;
- seniority fit;
- title/occupation similarity;
- evidence strength;
- candidate/company preference alignment;
- freshness/activity.

Weights live in configuration and are versioned. The heuristic scorer's outputs are estimates for routing, not claims of calibrated real-world probability.

The UI MUST NOT display these values as "82% match" merely because the backend stores them numerically.

## 11.3 Learned scorer

Once sufficient interaction data exists, train separate calibrated models for the funnel probabilities. They may share embeddings/features but must remain separately evaluable.

Requirements:

- temporal train/validation split;
- calibration curves;
- Brier/log loss in addition to ranking metrics;
- market-cell performance breakdown;
- cold-start breakdown;
- missing-data robustness;
- versioned model artifacts;
- rollback support;
- no direct protected-attribute features.

## 11.4 Model promotion gate

A learned model cannot replace the current production model solely because offline AUC improves. Promotion requires:

- no regression in calibration;
- no regression in retrieval-adjusted relevant metrics;
- acceptable subgroup audit;
- shadow-mode comparison;
- deterministic replay compatibility;
- explanation availability;
- model-card update.

# 12. Event-driven clearing engine

## 12.1 Trigger events

Clearing is triggered by events that materially change state, including:

- candidate activated/paused/resumed;
- candidate profile/preferences changed;
- vacancy activated/paused/closed;
- vacancy requirements changed;
- active decision Interested/Pass/Expired;
- candidate/employer slot freed;
- mutual match closed;
- interview/offer/acceptance stage update;
- model version promoted;
- market price update;
- verification status change that affects feasibility/evidence;
- scheduled reconciliation.

## 12.2 Online allocation algorithm

Reference pseudocode:

```text
handle_event(event):
    apply event idempotently
    determine affected candidates, vacancies, and market cells
    expire invalid decisions
    recompute available human-decision capacity

    for each affected actor scope with free capacity:
        retrieve feasible counterpart pool
        score candidate-vacancy pairs
        compute both directional net surpluses
        create proposal for direction with higher surplus

    merge proposals into priority queue by positive net surplus

    while proposal queue not empty:
        proposal = pop highest surplus
        re-check current state and feasibility
        re-check first-mover capacity under transaction lock
        ensure pair-cycle not already active/closed
        if valid and surplus > 0:
            issue exactly one first-mover decision card
            write immutable exposure audit record

    publish resulting state-change events through outbox
```

## 12.3 Local greedy vs global optimization

TEN v1 SHOULD use a transactional event-driven greedy allocator because it is understandable, low-latency, and easier to build safely.

The architecture MUST leave room for a periodic batch optimizer or min-cost-flow/b-matching reconciler later. A later optimizer may fill empty slots but MUST NOT revoke an already-issued human decision solely because another pair now scores higher.

## 12.4 Transactional capacity enforcement

When allocating a candidate decision:

1. acquire candidate-scoped database/advisory lock;
2. count active candidate decisions;
3. if count >= 10, abort allocation;
4. verify pair cycle still eligible;
5. insert decision and exposure record atomically.

Employer-side allocation uses a vacancy-scoped lock and identical pattern.

This prevents race conditions from multiple workers.

# 13. Pair interaction state machine

Canonical states:

```text
ELIGIBLE
  -> CANDIDATE_DECISION_REQUIRED
  -> EMPLOYER_DECISION_REQUIRED
  -> CANDIDATE_INTEREST_SENT
  -> EMPLOYER_INTEREST_SENT
  -> WAITING_CANDIDATE_SLOT
  -> WAITING_EMPLOYER_SLOT
  -> MUTUAL_MATCH
  -> INTERVIEWING
  -> OFFERED
  -> ACCEPTED

Closed terminal states:
  CLOSED_CANDIDATE_PASS
  CLOSED_EMPLOYER_PASS
  CLOSED_EXPIRED
  CLOSED_WITHDRAWN
  CLOSED_JOB_CLOSED
  CLOSED_CANDIDATE_UNAVAILABLE
  CLOSED_REJECTED
  CLOSED_OFFER_DECLINED
  CLOSED_FILLED_ELSEWHERE
  CLOSED_ADMIN
```

## 13.1 Candidate-first path

```text
ELIGIBLE
 -> CANDIDATE_DECISION_REQUIRED
    -> Pass: CLOSED_CANDIDATE_PASS
    -> Interested: CANDIDATE_INTEREST_SENT
         -> employer capacity available: EMPLOYER_DECISION_REQUIRED
         -> otherwise: WAITING_EMPLOYER_SLOT
              -> slot available: EMPLOYER_DECISION_REQUIRED
         -> Employer Pass: CLOSED_EMPLOYER_PASS
         -> Employer Interested: MUTUAL_MATCH
```

## 13.2 Employer-first path

```text
ELIGIBLE
 -> EMPLOYER_DECISION_REQUIRED
    -> Pass: CLOSED_EMPLOYER_PASS
    -> Interested: EMPLOYER_INTEREST_SENT
         -> candidate capacity available: CANDIDATE_DECISION_REQUIRED
         -> otherwise: WAITING_CANDIDATE_SLOT
              -> slot available: CANDIDATE_DECISION_REQUIRED
         -> Candidate Pass: CLOSED_CANDIDATE_PASS
         -> Candidate Interested: MUTUAL_MATCH
```

## 13.3 Waiting queue rules

Waiting queues are not visible human decisions, but they MUST be bounded to avoid accumulating stale interest.

Configurable defaults:

- per candidate `waiting_candidate_slot_limit = 10`;
- per vacancy `waiting_employer_slot_limit = 10`.

When the waiting queue is full, the congestion penalty should make further first-mover allocations unlikely or impossible.

Waiting items are prioritized by:

1. already-expressed interest;
2. current net expected value;
3. age/urgency;
4. deterministic tie-breaker.

# 14. Decision lifecycle and TTL

## 14.1 Decision token

Every active decision has:

- decision UUID;
- interaction cycle UUID;
- actor type;
- actor/scope ID;
- issue time;
- expiration time;
- model/version snapshot;
- immutable exposure audit ID;
- one-time decision status.

## 14.2 Expiration

Initial configurable defaults:

- candidate decision TTL: 72 hours;
- employer decision TTL: 72 hours.

These are operational defaults, not research conclusions.

Expiration:

- frees the slot;
- closes the decision token;
- usually closes the interaction cycle as `CLOSED_EXPIRED` unless policy deliberately retries after cooldown;
- updates reliability metrics only after sufficient sample size and with context.

## 14.3 Reminders

At most two reminders per active decision by default. Notification pressure must not recreate the attention problem TEN is designed to solve.

# 15. Profile and preference model

## 15.1 Candidate hard constraints vs preferences

Candidate settings must clearly distinguish:

**Hard constraints** - pair should not be shown:

- minimum compensation;
- unacceptable geography/work mode;
- employment type;
- authorization restrictions;
- blocked companies;
- unavailable start period.

**Preferences** - scoring features only:

- desired compensation above minimum;
- industry;
- company size;
- technology domain;
- commute preference;
- preferred seniority;
- role keywords.

The UI must explain this difference.

## 15.2 Employer hard requirements vs preferences

Employer vacancy editor similarly distinguishes:

- legally/operationally mandatory requirements;
- strongly preferred qualifications;
- nice-to-have signals.

The product SHOULD discourage excessive hard filters because they reduce market liquidity and can encode bad hiring habits.

# 16. Candidate skills and evidence

## 16.1 Skill object

A skill record contains:

- canonical skill ID;
- display label;
- candidate self-assessed usage level (optional, not a rank);
- recency;
- years/months evidence if known;
- evidence references;
- verification status;
- machine-extracted confidence;
- candidate-confirmed flag.

## 16.2 Evidence types

- work history;
- project/portfolio;
- publication;
- education/coursework;
- certification/license;
- assessment if TEN later supports validated assessments;
- external profile/credential;
- recruiter/verification operator verification.

## 16.3 Evidence display

Employer sees relevant evidence such as:

`FPGA - supported by 2 projects and prior role`

not:

`FPGA score: 8.47/10`.

# 17. Verification and trust

## 17.1 Candidate verification levels

Independent statuses:

- email verified;
- phone verified;
- identity verified;
- education claim verified;
- employment claim verified;
- credential verified;
- portfolio evidence verified.

Verification SHOULD be granular. "Verified candidate" should not imply every claim is verified.

## 17.2 Employer verification

- recruiter work email/domain;
- organization domain;
- organization/legal entity where available;
- vacancy authenticity;
- compensation consistency;
- role ownership.

## 17.3 Background checks

Background checks are outside the ranking core. If an employer requires lawful background screening after an appropriate stage, integrate through a separate consented workflow. Results MUST NOT silently become global matching features.

# 18. Employer reliability/accountability

TEN calculates objective process metrics, subject to sample-size and privacy rules.

Possible candidate-facing signals:

- verified employer;
- median first-response time;
- final-disposition completion rate;
- interview cancellation rate;
- compensation accuracy;
- vacancy verification rate;
- candidate ghosting rate;
- process-duration distribution.

Rules:

1. Do not display unstable metrics below minimum sample threshold.
2. Do not allow employers to pay to hide unfavorable factual reliability signals.
3. Provide an appeal/correction path for measurement errors.
4. Distinguish organization-level and recruiter-level metrics when enough data exists.
5. Avoid a single employer star rating; show interpretable components.

# 19. Explanations

## 19.1 Candidate explanation template

"Why this reached you" may include up to 4 concise factors:

- key skill/experience alignment;
- compensation overlap;
- location/work-mode alignment;
- seniority alignment;
- employer already expressed interest;
- verified requirement match;
- strong recent activity/availability.

Never state protected-attribute or audit-only factors.

## 19.2 Employer explanation template

"Why TEN surfaced this candidate" may include:

- meets mandatory requirement;
- relevant verified skill/evidence;
- seniority fit;
- compensation alignment;
- candidate already expressed interest;
- location/work authorization fit;
- recent availability.

## 19.3 Explanation fidelity

Explanations MUST be derived from actual features/rules used for the decision. Do not generate generic LLM explanations disconnected from the scoring path.

# 20. Messaging and scheduling

## 20.1 Messaging unlock

Direct messaging opens only after mutual match.

Capabilities:

- text;
- safe links;
- limited file attachments;
- system stage messages;
- report/block;
- message read status optional.

Files must be malware scanned and size/type restricted.

## 20.2 Scheduling

TEN v1 provides lightweight scheduling:

- either side proposes time windows;
- counterpart selects;
- timezone normalized;
- calendar file/invite generated;
- later integrations may sync Google/Microsoft calendars.

Calendar integration is useful but not required for the first functional clearing MVP.

## 20.3 Messaging privacy

Message content is not used for ranking by default. Metadata necessary for delivery and abuse prevention may be stored. Any future model use of content requires explicit product/legal review and user disclosure.

# 21. Recruitment process tracking

After mutual match, process stages are distinct from recommendation state.

Canonical process stages:

```text
MATCHED
CONTACTED
SCREEN_SCHEDULED
SCREEN_COMPLETED
INTERVIEWING
FINAL_INTERVIEW
OFFER_PLANNED
OFFERED
ACCEPTED
REJECTED
WITHDRAWN
CLOSED
```

Each transition stores timestamp, actor, and reason category where applicable.

Employers SHOULD be prompted to disposition candidates before closing a role. Missing outcome is represented as missing data, never silently assumed rejection.

# 22. Notifications

Channels:

- in-app mandatory;
- email default;
- push optional when mobile exists;
- SMS not required in v1.

Priority classes:

1. employer/candidate already expressed interest in you;
2. new active decision;
3. decision expiring;
4. new mutual match/message;
5. interview/offer update;
6. digest/non-urgent.

Notification frequency is bounded. The notification service must deduplicate repeated events.

# 23. Search and browsing policy

TEN is intentionally not an unrestricted application board.

Candidates MAY browse:

- company pages;
- educational content;
- their own history;
- public role information if the product exposes it.

But public browsing must not expose an "Apply to everything" path that bypasses clearing.

Employers MAY browse their own candidate history and matches, but there is no unrestricted global candidate search endpoint in v1.

If future product research adds user-initiated search, the same attention budgets and clearing constraints must still apply.

# 24. Monetization boundaries

## 24.1 Candidate pricing

Candidate access is free in v1.

No candidate feature may sell ranking priority.

## 24.2 Employer pricing

Permitted monetization dimensions:

- organization subscription;
- number of active vacancies;
- recruiter seats;
- enterprise analytics;
- verification tooling;
- ATS integrations;
- support/service tier.

Prohibited:

- pay to increase pair score;
- pay to bypass the 10-card cap;
- sponsored candidates inserted ahead of better matches;
- sponsored vacancies inserted into candidate decision slots solely because of payment.

## 24.3 Billing isolation

The scoring/clearing service receives entitlement/capacity facts only when needed (e.g. whether an organization may activate another vacancy). It MUST NOT receive price paid or spend as ranking features.

# 25. Fairness, compliance, and human agency architecture

This section is product/engineering guidance, not legal advice.

## 25.1 Protected attributes

Protected/sensitive demographic attributes MUST NOT be direct matching/ranking inputs merely because they are available.

If TEN collects demographic attributes for voluntary auditing, they MUST live in a logically and access-controlled separate audit store.

## 25.2 Proxy risk

Removing explicit protected fields is insufficient. Model audits must test whether proxies or correlated features produce unacceptable outcome disparities.

## 25.3 Audit measurements

Where legally and ethically appropriate, measure by relevant groups and qualification strata:

- retrieval exposure;
- active-decision exposure;
- Interested rate;
- mutual-match rate;
- interview rate;
- offer rate;
- acceptance rate;
- expiration rate;
- time-to-opportunity;
- model calibration.

## 25.4 Human correction

Users require mechanisms to:

- correct profile/job data;
- dispute verification status;
- appeal suspected erroneous restriction;
- report discriminatory/inappropriate content;
- request accommodations/support.

## 25.5 No automated final employment decision

TEN produces introductions and routing. Employers remain responsible for employment decisions. The platform should not market a model score as an objective determination of who should be hired.

# 26. Security and privacy

## 26.1 Baseline controls

- TLS for all network traffic;
- encryption at rest;
- field-level encryption for selected sensitive values;
- secrets management, never source-code secrets;
- RBAC;
- tenant isolation;
- rate limiting;
- CSRF/XSS/SQLi protections;
- secure headers;
- file malware scanning;
- immutable audit log for privileged access;
- backup and restore procedure;
- environment separation;
- production access logging.

## 26.2 Candidate privacy

Candidate private details such as exact salary floor, hidden employers, contact information, and certain verification documents must not be exposed to employers unless product policy explicitly says so.

Show derived facts when possible:

- `Compensation aligned` instead of private minimum salary;
- `Work authorization requirement satisfied` instead of unnecessary document detail.

## 26.3 Data deletion

Account deletion workflow:

1. deactivate matching immediately;
2. invalidate active decisions;
3. close or anonymize interactions where legally/contractually appropriate;
4. delete or anonymize PII according to retention policy;
5. preserve minimum immutable audit/security records when legally necessary, with separation from active profile data;
6. confirm completion.

## 26.4 Data export

Candidate and employer users should be able to export their principal account/profile/process data in machine-readable form.

# 27. Abuse and fraud prevention

Threats include:

- fake jobs;
- fake candidate identities;
- credential inflation;
- scraping;
- bot decisions;
- recruiter spam;
- coordinated reputation manipulation;
- discriminatory pass-reason abuse;
- malicious attachments;
- duplicate organizations;
- candidate impersonation.

Controls:

- email/domain verification;
- anomaly detection;
- rate limits;
- device/session risk signals;
- verification escalation;
- duplicate detection;
- content moderation;
- file scanning;
- manual review queue;
- block/report;
- audit trail.

A single rejection/pass must never directly damage a candidate's global skill model.

# 28. Reference technical architecture

TEN v1 SHOULD begin as a **modular monolith plus workers**, not a premature fleet of microservices.

Reference stack:

- Web: Next.js + React + TypeScript.
- Backend API: FastAPI + Python.
- ORM: SQLAlchemy 2.
- Validation/contracts: Pydantic.
- Primary DB: PostgreSQL.
- Vector retrieval: pgvector.
- Cache/locks/queues: Redis where needed, while correctness remains DB-backed.
- Background jobs: Celery or equivalent.
- Object storage: S3-compatible.
- Email: provider behind interface.
- Observability: OpenTelemetry + metrics/error tooling.
- Local dev: Docker Compose.
- Production: containerized deployment; exact cloud is not a product dependency.

## 28.1 Logical modules

```text
frontend/
backend/
  app/
    auth/
    candidates/
    organizations/
    vacancies/
    verification/
    retrieval/
    scoring/
    clearing/
    decisions/
    matches/
    messaging/
    scheduling/
    process_tracking/
    notifications/
    billing/
    audit/
    fairness_audit/
    admin/
    analytics/
    common/
workers/
infra/
```

## 28.2 Separation rules

- `fairness_audit` may read protected audit attributes; `scoring` may not.
- `billing` may control entitlements; `scoring` may not consume spend.
- `verification` stores sensitive evidence; candidate/employer views consume redacted status objects.
- `audit` receives append-only records from all modules.

# 29. Database schema - conceptual

All primary entities use UUIDs, `created_at`, `updated_at`, and appropriate soft-delete/deactivation fields.

## 29.1 Identity and tenancy

Core tables:

- `users`
- `user_sessions` or external IdP references
- `organizations`
- `organization_domains`
- `organization_members`
- `organization_roles`

## 29.2 Candidate tables

- `candidate_profiles`
- `candidate_preferences`
- `candidate_blocks`
- `candidate_experience`
- `candidate_education`
- `candidate_skills`
- `candidate_evidence`
- `candidate_documents`
- `candidate_availability`
- `candidate_verifications`

## 29.3 Employer/vacancy tables

- `vacancies`
- `vacancy_locations`
- `vacancy_requirements`
- `vacancy_skills`
- `vacancy_owners`
- `vacancy_process_templates`
- `employer_verifications`

## 29.4 Matching/control tables

- `pair_cycles`
- `pair_feature_snapshots`
- `pair_predictions`
- `active_decisions`
- `decision_events`
- `waiting_interactions`
- `market_cells`
- `market_attention_prices`
- `entity_congestion_prices`
- `clearing_runs`
- `exposure_audit_records`

## 29.5 Post-match tables

- `matches`
- `match_participants`
- `recruitment_processes`
- `recruitment_stage_events`
- `offers`
- `interview_events`
- `conversation_threads`
- `messages`
- `attachments`
- `scheduling_events`

## 29.6 Platform operations

- `notifications`
- `notification_deliveries`
- `audit_log`
- `reports`
- `moderation_cases`
- `feature_flags`
- `config_versions`
- `model_registry`
- `model_deployments`
- `outbox_events`
- `idempotency_keys`

# 30. Core SQL-like schema

The following is intentionally close to executable PostgreSQL DDL. Codex may adapt names/types while preserving semantics.

```sql
CREATE TABLE candidate_profiles (
    candidate_id UUID PRIMARY KEY REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('draft','active','paused','unavailable','deactivated')),
    headline TEXT,
    home_region TEXT,
    work_mode_preferences JSONB NOT NULL DEFAULT '[]',
    desired_occupation_cluster_ids JSONB NOT NULL DEFAULT '[]',
    desired_seniority_min TEXT,
    desired_seniority_max TEXT,
    compensation_floor_amount NUMERIC,
    compensation_target_amount NUMERIC,
    compensation_currency CHAR(3),
    compensation_visibility TEXT NOT NULL DEFAULT 'private',
    available_from DATE,
    profile_version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vacancies (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    status TEXT NOT NULL CHECK (status IN ('draft','active','paused','filled','closed','expired')),
    title TEXT NOT NULL,
    occupation_cluster_id UUID NOT NULL,
    description TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    seniority_min TEXT,
    seniority_max TEXT,
    work_mode TEXT NOT NULL,
    region TEXT,
    compensation_min NUMERIC NOT NULL,
    compensation_max NUMERIC NOT NULL,
    compensation_currency CHAR(3) NOT NULL,
    opening_count INT NOT NULL DEFAULT 1 CHECK (opening_count > 0),
    hiring_capacity INT,
    vacancy_version BIGINT NOT NULL DEFAULT 1,
    activated_at TIMESTAMPTZ,
    closes_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pair_cycles (
    id UUID PRIMARY KEY,
    candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id),
    vacancy_id UUID NOT NULL REFERENCES vacancies(id),
    cycle_no INT NOT NULL,
    state TEXT NOT NULL,
    first_mover TEXT CHECK (first_mover IN ('candidate','employer')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    close_reason TEXT,
    UNIQUE(candidate_id, vacancy_id, cycle_no)
);

CREATE TABLE active_decisions (
    id UUID PRIMARY KEY,
    pair_cycle_id UUID NOT NULL REFERENCES pair_cycles(id),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('candidate','employer')),
    candidate_id UUID,
    vacancy_id UUID,
    status TEXT NOT NULL CHECK (status IN ('active','interested','passed','expired','cancelled')),
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ,
    exposure_audit_id UUID NOT NULL,
    UNIQUE(pair_cycle_id, actor_type)
);

CREATE INDEX active_candidate_decisions_idx
ON active_decisions(candidate_id)
WHERE status = 'active' AND actor_type = 'candidate';

CREATE INDEX active_vacancy_decisions_idx
ON active_decisions(vacancy_id)
WHERE status = 'active' AND actor_type = 'employer';
```

Capacity <=10 must be transactionally enforced in service code; PostgreSQL advisory locks or a dedicated capacity-counter row are acceptable.

# 31. API conventions

## 31.1 General

- REST JSON for v1.
- `/v1/...` versioning.
- UUID identifiers.
- ISO-8601 timestamps UTC.
- OIDC/JWT authentication.
- role/tenant authorization on every endpoint.
- pagination for histories.
- idempotency key required for state-changing decision endpoints and billing-sensitive mutations.
- structured error codes.
- OpenAPI generated from backend types.

## 31.2 Candidate endpoints

```text
GET    /v1/candidate/profile
PUT    /v1/candidate/profile
POST   /v1/candidate/activate
POST   /v1/candidate/pause
GET    /v1/candidate/preferences
PUT    /v1/candidate/preferences
GET    /v1/candidate/skills
POST   /v1/candidate/skills
POST   /v1/candidate/evidence
GET    /v1/candidate/decisions
GET    /v1/candidate/waiting
GET    /v1/candidate/matches
GET    /v1/candidate/history
POST   /v1/candidate/blocks
DELETE /v1/candidate/blocks/{organization_id}
```

## 31.3 Decision endpoints

```text
POST /v1/decisions/{decision_id}/interested
POST /v1/decisions/{decision_id}/pass
GET  /v1/decisions/{decision_id}
```

Request must include decision token/version and idempotency key. Server must reject stale/expired decisions.

## 31.4 Employer endpoints

```text
POST   /v1/organizations
GET    /v1/organizations/{id}
POST   /v1/organizations/{id}/members
POST   /v1/vacancies
GET    /v1/vacancies/{id}
PUT    /v1/vacancies/{id}
POST   /v1/vacancies/{id}/activate
POST   /v1/vacancies/{id}/pause
POST   /v1/vacancies/{id}/close
GET    /v1/vacancies/{id}/decisions
GET    /v1/vacancies/{id}/matches
GET    /v1/vacancies/{id}/analytics
```

## 31.5 Match/process endpoints

```text
GET  /v1/matches/{id}
GET  /v1/matches/{id}/messages
POST /v1/matches/{id}/messages
POST /v1/matches/{id}/stage-events
POST /v1/matches/{id}/withdraw
POST /v1/matches/{id}/schedule/proposals
POST /v1/matches/{id}/schedule/confirm
POST /v1/matches/{id}/offers
POST /v1/offers/{id}/accept
POST /v1/offers/{id}/decline
```

## 31.6 Verification/admin/internal endpoints

These must be separately authorized and not accessible to ordinary users.

# 32. Event catalog

All important mutations emit durable outbox events.

Examples:

```text
candidate.created
candidate.profile_updated
candidate.preferences_updated
candidate.activated
candidate.paused
candidate.availability_changed
candidate.verification_changed

organization.verified
vacancy.created
vacancy.updated
vacancy.activated
vacancy.paused
vacancy.closed

clearing.decision_issued
decision.interested
decision.passed
decision.expired
interaction.waiting_for_candidate_slot
interaction.waiting_for_employer_slot
match.created
match.withdrawn

process.stage_changed
interview.scheduled
interview.completed
offer.created
offer.accepted
offer.declined

model.promoted
config.updated
market.price_updated
```

Consumers must be idempotent because delivery is at-least-once.

# 33. Audit model

Every exposure audit record includes:

- timestamp;
- candidate ID;
- vacancy ID;
- pair cycle ID;
- first mover selected;
- decision recipient;
- feature snapshot ID;
- scorer/model bundle version;
- config version;
- market cell;
- attention prices;
- congestion prices;
- gross values by direction;
- net surpluses by direction;
- exploration flag;
- retrieval source/rank;
- explanation factors;
- code/build version where practical.

Audit records are append-only and should be immutable to application users.

# 34. Candidate UI specification

## 34.1 Primary navigation

Candidate navigation:

- Opportunities
- Sent interest / Waiting
- Matches
- Profile
- Preferences
- Verification
- Settings

No "Browse 100,000 jobs" tab.

## 34.2 Opportunities screen

Top summary:

- `Active: 6 / 10`
- availability status;
- profile completeness/verification warnings only when relevant.

Cards must be decision-oriented and compact. Required visible fields:

- role title;
- employer;
- compensation;
- location/work mode;
- high-level fit explanation;
- employer verification;
- whether employer already expressed interest;
- expiration timer/date;
- Interested / Pass.

## 34.3 Empty state

If fewer than 10 positive-value opportunities exist, say so plainly. Do not invent filler.

Example:

`You have 3 active opportunities. TEN is holding the remaining slots open rather than showing low-confidence matches.`

## 34.4 Waiting screen

Shows non-action states:

- Interest sent - waiting on employer;
- Employer interested - queued for your next decision slot only if not already active;
- Recently expired;
- closed.

This screen must not require repeated decisions.

# 35. Employer UI specification

## 35.1 Primary navigation

- Vacancies
- Matches
- Team
- Verification
- Analytics
- Billing
- Settings

## 35.2 Vacancy dashboard

For each active role:

- status;
- active candidate decisions `N/10`;
- waiting candidate interest;
- mutual matches;
- interviews;
- offers;
- hired/opening count;
- process response metrics;
- pause/close controls.

## 35.3 Candidate card

Required:

- candidate identity per privacy setting;
- relevant experience;
- relevant verified evidence;
- must-have alignment;
- compensation alignment;
- location/work authorization alignment;
- candidate already interested indicator;
- concise explanation;
- Interested / Pass;
- expiry.

No global candidate score.

# 36. Admin and support UI

Admin tools require separate privileged routes.

Features:

- user/org lookup;
- verification cases;
- abuse reports;
- decision/exposure audit viewer;
- state-machine repair tool with controlled permissions;
- config/version viewer;
- model deployment viewer;
- notification delivery diagnostics;
- market health dashboard;
- feature flags;
- account suspension/reactivation;
- data export/deletion workflow status.

Any manual state repair MUST write an audit event.

# 37. Analytics and north-star metrics

## 37.1 Primary metric

Human decisions per accepted hire:

$$
D/H = \frac{D_C + D_E}{H}.
$$

Always report components:

$$
D_C/H, \qquad D_E/H.
$$

## 37.2 Guardrail metrics

- accepted hires;
- mutual matches;
- interview rate;
- offer rate;
- acceptance rate;
- time to first opportunity;
- time to mutual match;
- time to accepted hire;
- active-decision expiration rate;
- candidate and employer backlog;
- retrieval recall offline;
- model calibration;
- cold-start exposure;
- market-cell coverage;
- user block/report rate;
- employer process completion;
- verification rate.

## 37.3 Metrics the product must not optimize in isolation

- raw applications;
- clicks;
- time spent in app;
- notification opens;
- number of recommendations shown.

# 38. Reliability metrics

## 38.1 Employer reliability

Internal counters:

- decisions issued;
- decisions answered;
- median decision latency;
- mutual matches created;
- process final dispositions;
- cancellations;
- no-response closures;
- compensation changes after activation;
- verified vs unverified roles.

Candidate-facing values require configured minimum denominator to avoid noise.

## 38.2 Candidate reliability

Candidate reliability may be used narrowly for abuse/interaction quality (e.g. repeated no-shows), but MUST NOT be collapsed into a public employability score.

A missed interview should not reduce technical skill estimates.

# 39. Model feature policy

## 39.1 Allowed feature families

Subject to legal/product review:

- role/occupation features;
- skills;
- verified evidence;
- experience relevance;
- education where relevant;
- compensation compatibility;
- geography/work mode;
- availability;
- activity freshness;
- prior candidate preference behavior;
- prior employer preference behavior;
- funnel outcomes;
- organization reliability signals;
- time/market-cell state.

## 39.2 Prohibited/default-excluded features

- protected demographic attributes as ranking inputs;
- facial analysis;
- voice/emotion analysis;
- inferred political/religious beliefs;
- private message semantics without explicit review/consent;
- payment amount;
- ad spend;
- arbitrary social popularity;
- raw background-check results as generalized rank features.

# 40. Cold-start behavior

## 40.1 New candidate

Use:

- structured profile;
- skills/evidence;
- role preferences;
- embeddings;
- market priors;
- explicit uncertainty.

A new candidate may receive exploration allocation when plausible.

## 40.2 New vacancy/employer

Use:

- structured vacancy requirements;
- company/industry metadata;
- market priors;
- employer verification;
- explicit uncertainty.

New employers must not be permanently suppressed because they lack historical response data.

# 41. Configuration registry

All empirically uncertain constants must be centrally versioned.

Examples:

```yaml
matching:
  max_candidate_active_decisions: 10
  max_vacancy_active_decisions: 10
  candidate_decision_ttl_hours: 72
  employer_decision_ttl_hours: 72
  waiting_candidate_slot_limit: 10
  waiting_employer_slot_limit: 10
  retrieval_pool_size: 200
  max_exploration_slots_per_scope: 1
  pair_cooldown_days: 30
  reminder_offsets_hours: [24, 60]

scoring:
  scorer_type: heuristic_v1
  min_positive_surplus: 0.0

market_control:
  attention_price_min: 0.0
  attention_price_max: 10.0
  congestion_price_min: 0.0
  congestion_price_max: 10.0
```

Every config change produces a new immutable `config_version` and audit event.

# 42. Feature flags

Feature flags are required for high-risk or experimental changes:

- learned scorer;
- posterior exploration;
- calendar integration;
- candidate identity masking;
- employer reliability display;
- new market-cell definition;
- new explanation format;
- new verification vendor;
- model version.

Flags must support organization/user cohort targeting and rollback.

# 43. Observability

## 43.1 Technical SLO measurements

Track:

- API latency/error rate;
- clearing event lag;
- decision issuance latency;
- queue depth;
- outbox lag;
- DB connection/lock contention;
- model scoring latency;
- notification failures;
- object-storage failures;
- worker retries;
- active-decision invariant violations (should be zero).

## 43.2 Product health alerts

Alert on:

- candidate/vacancy active decisions >10;
- sudden drop in matches;
- abnormal expiration spike;
- market price stuck at clamp;
- waiting queue growth;
- unexpected score distribution shift;
- model version missing audit metadata;
- high duplicate/retry rate;
- increased abuse reports.

# 44. Performance and scalability targets

Initial engineering targets, not absolute commitments:

- standard API p95 under 500 ms excluding large uploads;
- decision list fetch p95 under 700 ms;
- online scorer batch response under 1 s for a typical retrieval pool;
- clearing event to new decision issuance under 10 s for ordinary cases;
- asynchronous heavy recomputation allowed for bulk updates;
- database queries indexed by active state, candidate, vacancy, market cell, and timestamps.

The user experience must not block on model retraining or batch analytics.

# 45. Concurrency and idempotency

## 45.1 Decision action

`Interested` and `Pass` endpoints must be atomic and idempotent.

Race example: user double-clicks Interested while an expiration worker fires.

Correct behavior:

- one transaction wins based on row lock/version;
- the other receives deterministic already-resolved/expired response;
- no duplicate mutual match;
- no duplicate event.

## 45.2 Mutual match creation

`matches` table must enforce uniqueness per pair cycle. Mutual creation should occur in same transaction that commits the second Interested decision or via an idempotent state-transition function.

# 46. Outbox and background processing

Use transactional outbox:

1. business transaction mutates state;
2. same transaction inserts `outbox_events` row;
3. worker publishes/processes event;
4. marks delivered;
5. consumers dedupe by event ID.

This prevents state changes from being committed without corresponding downstream notifications/clearing work.

# 47. File/document handling

Candidate resumes/evidence and employer documents:

- direct-to-object-storage upload with signed URLs;
- virus/malware scan;
- MIME/type verification;
- size limits;
- access control;
- short-lived download URLs;
- audit download of sensitive verification documents;
- parsed resume text stored separately with provenance and candidate confirmation.

# 48. LLM use policy

TEN may use an LLM for bounded assistive tasks, not as an untraceable final ranker in v1.

Permitted examples:

- resume-to-structured-field extraction with user confirmation;
- job-description structuring with recruiter confirmation;
- explanation wording from already-selected structured factors;
- message drafting;
- support summarization.

LLM output MUST NOT silently invent credentials or requirements.

If an LLM contributes to a ranking feature, the feature must be reproducible/versioned and audited like any other model feature.

# 49. Billing and entitlements

## 49.1 Employer entitlements

Entitlements may limit:

- active vacancy count;
- recruiter seats;
- analytics depth;
- integration access;
- support tier.

They may not alter pair score/rank.

## 49.2 Vacancy activation

Activation flow checks entitlement before status becomes active. Once active, all clearing behavior is independent of payment amount.

# 50. Degradation and failure modes

## 50.1 Scoring service unavailable

Fallback:

- do not issue random recommendations;
- retain existing active decisions;
- queue clearing work;
- optionally use last known stable heuristic scorer if configured;
- alert operations.

## 50.2 Notification provider unavailable

In-app state remains authoritative. Queue delivery retries. Do not duplicate decisions to compensate.

## 50.3 Model drift

If calibration/quality alerts trip:

- freeze promotion;
- revert to previous model or heuristic;
- retain audit trail;
- do not retroactively alter already-issued decisions.

## 50.4 Market illiquidity

If no positive-value pairs exist, show fewer than 10 cards. UI should explain scarcity rather than pretending the system is broken.

## 50.5 Overloaded market

Rising attention/congestion prices reduce new exposures. Existing human decisions remain stable until resolved/expired.

# 51. Testing strategy

## 51.1 Unit tests

Must cover:

- feasibility rules;
- value formulas;
- direction selection;
- attention-price update;
- congestion update;
- TTL calculation;
- explanation generation;
- permissions;
- idempotency helpers.

## 51.2 State-machine tests

Property: only allowed transitions occur.

Examples:

- `CANDIDATE_DECISION_REQUIRED -> MUTUAL_MATCH` directly is impossible unless employer interest was already recorded in same pair cycle context;
- pass cannot later become interested on same decision token;
- expired token rejects answer;
- mutual match unique.

## 51.3 Invariant/property tests

Randomized/property-based tests should prove:

- candidate active count never >10;
- vacancy active count never >10;
- no duplicate active pair cycle;
- billing spend never appears in scoring feature schema;
- protected audit fields never appear in matching DB view/model feature contract;
- no pre-match message can be created;
- closing vacancy removes active decisions;
- repeated same event does not change final state.

## 51.4 Concurrency tests

Simulate:

- multiple workers filling last slot;
- simultaneous Interested/Pass;
- expiration racing decision;
- vacancy closure racing mutual match;
- duplicate webhook/event delivery.

## 51.5 Security tests

- tenant boundary;
- IDOR;
- role escalation;
- signed URL expiry;
- upload content validation;
- rate limits;
- CSRF/XSS;
- secret leakage;
- audit-log tampering.

## 51.6 Model tests

- calibration;
- missingness;
- temporal leakage;
- market-cell breakdown;
- cold-start;
- retrieval recall;
- direction-specific performance;
- distribution shift.

# 52. Acceptance criteria for TEN v1

A build is not TEN v1-complete until all following are true.

## 52.1 Candidate acceptance

- candidate can onboard and activate;
- hard preferences and blocks work;
- no more than 10 active decisions;
- candidate can Interested/Pass;
- employer-first inbound interest can reach candidate;
- sent interest/waiting is visible separately;
- candidate can mutual match and message;
- candidate can track interview/offer states;
- candidate can pause/deactivate/delete/export.

## 52.2 Employer acceptance

- org and team can be created;
- vacancy can be created/validated/activated;
- per vacancy no more than 10 active decisions;
- employer can Interested/Pass;
- candidate-first interest can reach employer;
- mutual match/message/process works;
- role can pause/close;
- disposition events can be recorded;
- billing entitlement does not change ranking.

## 52.3 Clearing acceptance

- hard feasibility enforced;
- retrieval returns candidate pool;
- scorer interface works;
- both direction surpluses calculated;
- first mover chosen dynamically;
- positive-surplus requirement enforced;
- waiting queues bounded;
- slots replenish event-by-event;
- exposure audit written for every issued decision;
- capacity invariant survives concurrency test.

## 52.4 Trust/compliance acceptance

- verification statuses visible appropriately;
- protected audit store separated;
- ranking service lacks access to protected fields;
- explanation tied to real factors;
- report/block supported;
- privileged access audited;
- account deletion/export works.

# 53. Implementation sequence for Codex

This is the recommended build order. Complete each layer with tests before moving on.

## Phase A - Repository and infrastructure foundation

Build:

- monorepo structure;
- Next.js app shell;
- FastAPI app shell;
- PostgreSQL migrations;
- Redis/background worker;
- auth/OIDC integration;
- organization/candidate role model;
- OpenAPI client generation if desired;
- Docker Compose dev environment;
- test harness;
- CI lint/type/test pipeline.

Definition of done: user can authenticate; candidate/employer tenant separation tested; migrations reproducible.

## Phase B - Candidate and employer data model

Build:

- candidate profile/preference/skills/evidence CRUD;
- organization/team CRUD;
- vacancy CRUD and validation;
- status activation/pause/close;
- object storage upload path;
- structured resume/job extraction optional but behind confirmation.

Definition of done: realistic candidate and vacancy can be created entirely through UI/API.

## Phase C - Pair state machine and decisions before intelligence

Build:

- pair cycles;
- active decisions;
- candidate/employer card UI;
- Interested/Pass;
- capacity locks;
- TTL/expiration worker;
- waiting queues;
- double opt-in;
- matches.

Use manual/admin-created pairs initially.

Definition of done: full two-sided flow works without any ranking model.

## Phase D - Retrieval and heuristic scoring

Build:

- hard feasibility service;
- occupation/skill taxonomy;
- pgvector embeddings;
- structured retrieval;
- `PairScorer` interface;
- `HeuristicPairScorer`;
- explanation factors;
- feature snapshots/prediction storage.

Definition of done: candidate-job pool and scores are reproducible/versioned.

## Phase E - Clearing controller

Build:

- market cells;
- attention price store;
- congestion price store;
- directional net-surplus computation;
- proposal queue;
- transactional allocation;
- event triggers;
- replenishment;
- audit record.

Definition of done: system autonomously fills empty slots without violating invariants.

## Phase F - Post-match workflow

Build:

- messaging;
- scheduling basics;
- recruitment stages;
- interviews;
- offers;
- accepted/declined/withdrawn outcomes;
- role closure/disposition.

Definition of done: a pair can proceed from exposure to accepted offer with full audit history.

## Phase G - Trust, verification, abuse, admin

Build:

- candidate/employer verification states;
- block/report;
- moderation cases;
- employer reliability metrics;
- privileged admin UI;
- security/audit viewer.

## Phase H - Notifications and analytics

Build:

- in-app/email notifications;
- dedupe/reminders;
- metrics pipeline;
- north-star dashboard;
- market health dashboard;
- invariant alerts.

## Phase I - Learned-model readiness

Build:

- training dataset extractor;
- temporal split tooling;
- model registry;
- calibration reports;
- shadow inference;
- promotion/rollback;
- posterior/uncertainty interface.

Do not claim the learned model is "better" without evidence.

# 54. Suggested repository layout

```text
ten/
  README.md
  docker-compose.yml
  .env.example
  frontend/
    app/
    components/
    lib/
    tests/
  backend/
    pyproject.toml
    alembic/
    app/
      main.py
      config.py
      db/
      auth/
      candidates/
      organizations/
      vacancies/
      retrieval/
      scoring/
      clearing/
      decisions/
      matches/
      messaging/
      scheduling/
      process_tracking/
      verification/
      notifications/
      billing/
      audit/
      fairness_audit/
      admin/
      analytics/
      common/
    tests/
  worker/
  infra/
  scripts/
  docs/
    adr/
    model_cards/
    api/
```

# 55. Core Python domain contracts

```python
from enum import StrEnum
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class FirstMover(StrEnum):
    CANDIDATE = "candidate"
    EMPLOYER = "employer"

class PairDirectionScore(BaseModel):
    direction: FirstMover
    gross_expected_value: float
    attention_cost: float
    congestion_cost: float
    net_surplus: float
    uncertainty: float | None = None

class PairScore(BaseModel):
    candidate_id: UUID
    vacancy_id: UUID
    feasible: bool
    p_candidate_cold: float
    p_candidate_after_employer_interest: float
    p_employer_cold: float
    p_employer_after_candidate_interest: float
    p_interview_given_mutual: float
    p_offer_given_interview: float
    p_accept_given_offer: float
    survival_probability: float
    feature_snapshot_id: UUID
    model_bundle_version: str
    explanation_factors: list[dict]

class AllocationProposal(BaseModel):
    pair_cycle_id: UUID
    candidate_id: UUID
    vacancy_id: UUID
    market_cell_id: UUID
    chosen_direction: FirstMover
    candidate_first: PairDirectionScore
    employer_first: PairDirectionScore
    config_version: str
    created_at: datetime
```

# 56. Clearing computation pseudocode

```python
def compute_direction_scores(pair: PairScore, market, candidate_state, vacancy_state):
    r = (
        pair.p_interview_given_mutual
        * pair.p_offer_given_interview
        * pair.p_accept_given_offer
    )

    v_ce = (
        pair.p_candidate_cold
        * pair.p_employer_after_candidate_interest
        * r
        * pair.survival_probability
    )
    v_ec = (
        pair.p_employer_cold
        * pair.p_candidate_after_employer_interest
        * r
        * pair.survival_probability
    )

    cost_ce = market.mu_candidate + pair.p_candidate_cold * market.mu_employer
    cost_ec = market.mu_employer + pair.p_employer_cold * market.mu_candidate

    congestion_ce = pair.p_candidate_cold * vacancy_state.lambda_congestion
    congestion_ec = pair.p_employer_cold * candidate_state.kappa_congestion

    g_ce = v_ce - cost_ce - congestion_ce
    g_ec = v_ec - cost_ec - congestion_ec

    return g_ce, g_ec
```

Production implementation may normalize scales, but all terms must have a coherent documented unit. Do not add arbitrary terms without an ADR and config/model version.

# 57. Explanation factor contract

A scorer returns structured factors such as:

```json
[
  {
    "code": "SKILL_ALIGNMENT",
    "label": "Your verified optics experience matches a core requirement",
    "direction": "positive",
    "importance": "high"
  },
  {
    "code": "COMPENSATION_ALIGNED",
    "label": "The listed compensation overlaps your requirements",
    "direction": "positive",
    "importance": "high"
  },
  {
    "code": "EMPLOYER_ALREADY_INTERESTED",
    "label": "The employer already expressed interest in your profile",
    "direction": "positive",
    "importance": "high"
  }
]
```

UI chooses the top few factors. The text may be templated or LLM-polished, but codes/facts are deterministic.

# 58. Model-training dataset contract

One row per pair observation or stage transition with temporal provenance.

Required fields include:

- candidate ID pseudonym;
- vacancy ID pseudonym;
- observation time;
- profile/vacancy version IDs;
- market cell;
- first-mover context;
- exposure source;
- features available at observation time only;
- candidate decision outcome if exposed;
- employer decision outcome if exposed;
- interview/offer/accept outcome;
- censoring/unknown indicators;
- verification flags;
- model version responsible for exposure.

No future information may leak backward into training features.

# 59. Offline evaluation protocol

Until real deployment, use simulations/public datasets cautiously.

For first-party evaluation once data exists:

1. temporal split;
2. retrieval evaluation;
3. directional interest calibration;
4. downstream funnel calibration;
5. replay under historical availability constraints;
6. compare policies using off-policy methods only with explicit assumptions;
7. subgroup/cold-start breakdown;
8. report human decisions and outcome preservation separately.

Never label offline historical replay as causal proof that TEN reduces applications in production.

# 60. Experimentation boundaries

A/B experiments may change:

- card presentation;
- explanation wording;
- notification timing;
- scorer/model versions;
- exploration policy;
- active-slot target below 10;
- price-controller parameters.

Experiments must never:

- exceed hard active-decision cap;
- sell ranking priority;
- bypass consent/privacy rules;
- expose protected attributes to ranker;
- randomly suppress critical safety/compliance features.

# 61. Product copy principles

TEN should communicate scarcity as a benefit, not a defect.

Preferred language:

- "6 active opportunities"
- "Employer already expressed interest"
- "TEN is holding open slots rather than showing low-confidence matches"
- "Why this reached you"
- "Compensation aligned"

Avoid:

- "Your score is 81"
- "You ranked #37"
- "AI says you are a 92% fit" unless future calibration/product research justifies exact percentages
- "Rejected by AI"
- "You lost to a better candidate"

# 62. Data-retention categories

Define configurable retention classes:

1. active account/profile data;
2. hiring interaction history;
3. message content;
4. verification documents;
5. audit/security logs;
6. aggregated analytics;
7. model-training extracts.

Deletion/anonymization behavior must be documented per category before production launch.

# 63. Accessibility

Web UI should target WCAG 2.2 AA practices:

- keyboard-operable decision cards;
- semantic headings/forms;
- visible focus;
- contrast;
- screen-reader labels;
- no color-only status;
- accessible error messages;
- reduced-motion support;
- timezone/date clarity.

Candidate accommodation requests should have a human support path.

# 64. Internationalization readiness

V1 may launch in one locale, but schemas should not hard-code US-only assumptions.

Use:

- ISO currency codes;
- timezone-aware timestamps;
- structured country/region fields;
- locale-ready text;
- flexible compensation periods;
- configurable work-authorization vocabulary.

Do not implement all countries' compliance in v1; keep architecture capable of jurisdiction-specific policy gates.

# 65. Decision-quality UX safeguards

To keep the product from becoming swipe addiction:

- no endless deck after 10;
- no artificial streaks;
- no gamified candidate score;
- no pressure countdown shorter than operational need;
- allow user to pause matching;
- show enough context for a meaningful decision;
- do not hide compensation to drive clicks.

# 66. Employer process-quality safeguards

- require valid compensation range before activation;
- require role owner;
- require structured must-haves vs preferences;
- expire stale vacancies;
- flag repeated non-response;
- prevent recruiters from mass-opening duplicate roles to obtain more candidate slots;
- duplicate-vacancy detection;
- organization-level active-role entitlement.

# 67. Duplicate and gaming controls

## 67.1 Duplicate vacancies

Detect near-duplicate roles by organization, title, location, description embedding, and requirement overlap. Duplicates may be merged or blocked if used to multiply attention capacity.

## 67.2 Duplicate candidate accounts

Use verified email/phone/identity where appropriate and anomaly signals. Do not create invasive fingerprinting without privacy review.

## 67.3 Decision farming

If an employer repeatedly marks Interested to reveal candidate interest but does not proceed, reliability and allocation penalties may increase after robust evidence. The policy must be transparent and appealable.

# 68. Market health dashboard

Internal dashboard by market cell:

- active candidates;
- active vacancies/openings;
- candidate free slots;
- employer free slots;
- waiting queues;
- `mu_candidate`;
- `mu_employer`;
- median job congestion;
- decision completion;
- match rate;
- interview/offer rate;
- cold-start share;
- expiration rate;
- model calibration.

This is the operator view of whether TEN is actually clearing the market or merely generating cards.

# 69. Admin reconciliation jobs

Scheduled jobs:

- expire stale decisions;
- expire/flag stale vacancies;
- drain waiting queues into newly freed slots;
- recompute market prices;
- recompute reliability metrics;
- verify invariant counts;
- detect orphaned pair cycles;
- refresh embeddings after profile/job changes;
- archive old notifications;
- run audit integrity checks.

# 70. API security matrix

At minimum:

- Candidate endpoints: candidate self only.
- Vacancy decision endpoints: assigned recruiter/hiring manager for that organization/vacancy.
- Organization billing: org admin only.
- Verification documents: candidate + verification operator as explicitly authorized.
- Fairness audit data: restricted audit role only.
- Model/audit internals: service/admin roles only.
- Messages: only participants in mutual match plus narrowly scoped support access.

Never rely on UI hiding; enforce authorization in backend.

# 71. Privacy-preserving employer/candidate presentation

TEN may support privacy modes:

- candidate full name visible only after employer Interest;
- current employer hidden;
- exact address never necessary;
- employer sees region/commute/work-mode compatibility instead;
- contact details hidden until mutual match.

Policy should be configurable by launch market.

# 72. Candidate blocking and safety

Candidates can block an organization. Block immediately:

- makes all future pairs infeasible;
- removes active decision cards involving the org;
- closes waiting interactions;
- prevents contact except support/legal-required records;
- does not notify the blocked org of the block reason.

Report and block are separate: report may trigger moderation.

# 73. Employer blocking/safety

Employers may block an account for abuse/safety with structured reasons, but this mechanism must not become an unreviewed reputation weapon. Repeated organizational blocks should not automatically lower generalized employability without evidence and safeguards.

# 74. Reliability of employer claims

If employer edits materially important fields after candidates were exposed (e.g. compensation, location, employment type):

- record version diff;
- re-evaluate feasibility;
- notify affected active/matched candidates when material;
- optionally require re-confirmation;
- update compensation-accuracy/process metrics.

# 75. Candidate profile change behavior

Material candidate changes (availability, location constraints, compensation floor, work authorization) trigger:

- profile version increment;
- re-evaluation of active decisions;
- removal of now-infeasible decisions;
- clearing event.

Non-material copy edits need not churn allocations.

# 76. Explainable hard-filter failures

When a candidate asks why a visible role is not available through TEN, the system generally should not reveal another person's private ranking. But if the reason is the candidate's own explicit hard setting, it can say:

- compensation below your floor;
- location outside your settings;
- role requires a license not on your profile.

Do not expose employer-only secret filters if inappropriate; product should discourage secret hard filters altogether.

# 77. Taxonomy strategy

Use stable internal IDs for:

- occupation clusters;
- skills;
- industries;
- seniority;
- employment types;
- locations.

Display labels may change without breaking model data.

Skill taxonomy should support aliases/synonyms and hierarchical relationships. Embeddings may supplement, not replace, canonical IDs.

# 78. Embedding provenance

For every embedding store:

- source entity/version;
- embedding model name/version;
- creation timestamp;
- source text hash;
- dimensionality.

On embedding-model upgrade, dual-index or rebuild safely; do not compare vectors from incompatible models.

# 79. Resume/job parsing

Parser output is a proposal, not truth.

Flow:

1. upload;
2. parse;
3. show extracted fields;
4. candidate/recruiter confirms or edits;
5. only confirmed fields become authoritative profile/vacancy data;
6. retain extraction provenance.

# 80. System-generated messages

System messages should be explicit and factual:

- `Employer expressed interest`
- `Candidate expressed interest`
- `Mutual match created`
- `Decision expired`
- `Vacancy closed`
- `Interview scheduled`
- `Offer recorded`

Do not imitate a human recruiter with generated messages unless clearly marked and user-approved.

# 81. Audit replay

Given an exposure audit ID, an authorized engineer/auditor should be able to reconstruct:

1. candidate/vacancy versions;
2. feasibility result;
3. retrieved-pair context;
4. feature snapshot;
5. model/scorer version;
6. directional probability values;
7. market prices;
8. congestion values;
9. direction chosen;
10. net surplus;
11. config version;
12. resulting decision record.

This is essential for debugging, fairness analysis, and user disputes.

# 82. Architecture decision records (ADRs)

Any future change to a core invariant requires an ADR.

ADR template:

```text
Title:
Status: proposed / accepted / superseded
Context:
Decision:
Alternatives considered:
Effect on TEN invariants:
Data/model implications:
Security/privacy implications:
Migration plan:
Rollback plan:
```

Examples requiring ADR:

- changing active cap from 10;
- adding candidate search;
- adding paid ranking;
- using message content in models;
- allowing pre-match recruiter messages;
- changing first-mover objective;
- collecting new sensitive attributes.

# 83. Build-time seed/demo data

Codex should create deterministic seed data for development:

- 30 candidates;
- 3 organizations;
- 10 vacancies;
- varied preferences/skills;
- candidate-first and employer-first examples;
- waiting-queue examples;
- mutual matches;
- one closed job;
- verification statuses;
- market cells/prices.

Seed must support end-to-end screenshots and automated tests without using real personal data.

# 84. Developer commands

Repository SHOULD expose predictable commands such as:

```text
make dev
make test
make lint
make typecheck
make migrate
make seed
make worker
make web
make api
make e2e
```

Exact tooling may differ, but one-command local startup is a requirement.

# 85. CI/CD quality gates

Pull requests should require:

- formatting/lint;
- type checking;
- unit tests;
- state-machine/invariant tests;
- migration check;
- API schema diff check for breaking changes;
- frontend build;
- secret scan;
- dependency/security scan where available.

Production deployments require reversible migrations or documented rollback strategy.

# 86. Migration policy

Database migrations:

- append/change schemas in backward-compatible phases where possible;
- never delete columns required by current running code in same deploy;
- backfill asynchronously for large tables;
- version model/config references;
- preserve audit tables.

# 87. Data-quality rules

Core checks:

- compensation min/max coherent;
- currency present;
- active candidate has required preference fields;
- active vacancy has occupation and requirements;
- probability fields in bounds;
- no active decision references closed pair;
- no mutual match without two Interested events;
- no orphaned organization member;
- no inaccessible object-storage reference.

# 88. Product analytics events

Client analytics should be minimized and privacy-conscious.

Events:

- opportunity_card_viewed;
- decision_interested;
- decision_passed;
- explanation_expanded;
- profile_field_updated;
- vacancy_activated;
- match_opened;
- interview_scheduled;
- offer_recorded.

Do not track unnecessary cursor-level behavior or invasive fingerprinting.

# 89. Operational moderation workflow

Report categories:

- fake job;
- scam/payment request;
- harassment;
- discrimination concern;
- misleading compensation;
- impersonation;
- spam;
- unsafe/off-platform request;
- other.

Case states:

`OPEN -> TRIAGED -> INVESTIGATING -> ACTIONED / NO_ACTION -> CLOSED`

Actions can include warning, temporary restriction, vacancy removal, organization suspension, account suspension, verification escalation.

# 90. Data and model separation

Production ranking should read from a curated feature view, not directly from arbitrary application tables.

Benefits:

- enforce allowed-feature policy;
- version transformations;
- prevent protected-field leakage;
- reproducible snapshots;
- simpler model governance.

# 91. Minimum model-card contents

For every learned model:

- purpose;
- prediction target;
- training window;
- feature families;
- excluded features;
- data volume;
- missingness;
- calibration;
- ranking metrics;
- market breakdown;
- cold-start performance;
- fairness audit summary;
- known limitations;
- deployment version/date;
- rollback predecessor.

# 92. Scheduled model retraining

Do not automatically deploy retrains.

Pipeline:

`extract -> validate -> train -> calibrate -> evaluate -> audit -> register -> shadow -> approve -> deploy`.

A human/controlled promotion step is required initially.

# 93. Shadow mode

A candidate model can score live pairs without influencing allocation. Store its predicted outcomes beside production decisions for comparison.

This is the preferred way to validate a learned scorer before routing human attention through it.

# 94. Counterfactual/off-policy caution

Historical job-market data reflects the old policy that chose which pairs were exposed. Offline comparison is therefore biased.

TEN analytics must distinguish:

- predictive evaluation;
- historical replay;
- off-policy estimate;
- randomized experiment;
- causal result.

UI/docs must never present the first three as causal proof.

# 95. What "done" means for the conceptual model

The model is conceptually frozen when:

- product objective is fixed;
- bounded attention is fixed;
- double opt-in is fixed;
- dynamic first mover is fixed;
- event-driven replenishment is fixed;
- uncertainty/exploration is fixed conceptually;
- congestion pricing is fixed conceptually;
- no global candidate score is fixed;
- no pay-to-rank is fixed;
- auditability is fixed;
- real validation is explicitly deferred.

Those conditions are satisfied by this specification.

# Appendix A - Requirement index

## A.1 Candidate requirements

- **TEN-CAND-001** Candidate can create/edit profile.
- **TEN-CAND-002** Candidate can define hard constraints and preferences separately.
- **TEN-CAND-003** Candidate can activate/pause matching.
- **TEN-CAND-004** Candidate active decisions <=10.
- **TEN-CAND-005** Candidate can Interested/Pass exactly once per active token.
- **TEN-CAND-006** Candidate sees employer-first interest context.
- **TEN-CAND-007** Candidate cannot unrestricted-apply through TEN.
- **TEN-CAND-008** Candidate can block organization.
- **TEN-CAND-009** Candidate can manage evidence/verification.
- **TEN-CAND-010** Candidate can mutual match/message.
- **TEN-CAND-011** Candidate can export/delete data.

## A.2 Employer requirements

- **TEN-EMP-001** Organization/team management.
- **TEN-EMP-002** Structured vacancy with compensation.
- **TEN-EMP-003** Vacancy active decisions <=10.
- **TEN-EMP-004** Interested/Pass exactly once per token.
- **TEN-EMP-005** Candidate-first interest context visible.
- **TEN-EMP-006** No unrestricted global candidate database in v1.
- **TEN-EMP-007** Process stages and disposition.
- **TEN-EMP-008** Role pause/close invalidates relevant decisions.
- **TEN-EMP-009** Payment cannot affect rank.

## A.3 Clearing requirements

- **TEN-CLR-001** Hard feasibility before scoring.
- **TEN-CLR-002** Two directional values computed.
- **TEN-CLR-003** Attention cost included.
- **TEN-CLR-004** Congestion included.
- **TEN-CLR-005** Highest positive-surplus direction selected.
- **TEN-CLR-006** Event-driven replenishment.
- **TEN-CLR-007** Bounded waiting queues.
- **TEN-CLR-008** Explicit uncertainty/exploration support.
- **TEN-CLR-009** Market-cell price controls.
- **TEN-CLR-010** Full exposure audit.

## A.4 Trust/security requirements

- **TEN-SEC-001** Tenant isolation.
- **TEN-SEC-002** Sensitive fields protected.
- **TEN-SEC-003** File scanning.
- **TEN-SEC-004** Privileged access audited.
- **TEN-SEC-005** Protected audit fields inaccessible to ranker.
- **TEN-SEC-006** Delete/export workflows.
- **TEN-SEC-007** Block/report.
- **TEN-SEC-008** Idempotent state changes.

# Appendix B - Pair state transition table

| Current state | Event | Next state | Active slot consumed |
|---|---|---|---|
| ELIGIBLE | allocate candidate-first | CANDIDATE_DECISION_REQUIRED | candidate |
| ELIGIBLE | allocate employer-first | EMPLOYER_DECISION_REQUIRED | employer vacancy |
| CANDIDATE_DECISION_REQUIRED | pass | CLOSED_CANDIDATE_PASS | none |
| CANDIDATE_DECISION_REQUIRED | interested; employer had prior interest | MUTUAL_MATCH | none |
| CANDIDATE_DECISION_REQUIRED | interested; no prior employer interest | CANDIDATE_INTEREST_SENT / WAITING_EMPLOYER_SLOT | none |
| EMPLOYER_DECISION_REQUIRED | pass | CLOSED_EMPLOYER_PASS | none |
| EMPLOYER_DECISION_REQUIRED | interested; candidate had prior interest | MUTUAL_MATCH | none |
| EMPLOYER_DECISION_REQUIRED | interested; no prior candidate interest | EMPLOYER_INTEREST_SENT / WAITING_CANDIDATE_SLOT | none |
| WAITING_EMPLOYER_SLOT | employer capacity frees | EMPLOYER_DECISION_REQUIRED | employer vacancy |
| WAITING_CANDIDATE_SLOT | candidate capacity frees | CANDIDATE_DECISION_REQUIRED | candidate |
| MUTUAL_MATCH | interview starts | INTERVIEWING | none |
| INTERVIEWING | offer | OFFERED | none |
| OFFERED | accept | ACCEPTED | none |

# Appendix C - Example decision API payloads

Candidate interest:

```json
POST /v1/decisions/08d.../interested
Idempotency-Key: 9c1...

{
  "decision_version": 3
}
```

Response:

```json
{
  "decision_id": "08d...",
  "status": "interested",
  "pair_state": "CANDIDATE_INTEREST_SENT",
  "next": "waiting_for_employer"
}
```

Employer as second mover:

```json
{
  "decision_id": "50a...",
  "status": "interested",
  "pair_state": "MUTUAL_MATCH",
  "match_id": "c62..."
}
```

# Appendix D - Example scoring record

```json
{
  "candidate_id": "...",
  "vacancy_id": "...",
  "feasible": true,
  "probabilities": {
    "candidate_cold": 0.41,
    "candidate_after_employer_interest": 0.68,
    "employer_cold": 0.35,
    "employer_after_candidate_interest": 0.57,
    "interview_given_mutual": 0.52,
    "offer_given_interview": 0.31,
    "accept_given_offer": 0.74,
    "survival": 0.93
  },
  "market": {
    "mu_candidate": 0.04,
    "mu_employer": 0.08,
    "job_congestion": 0.02,
    "candidate_congestion": 0.01
  },
  "direction": {
    "candidate_first_net_surplus": 0.012,
    "employer_first_net_surplus": 0.019,
    "chosen": "employer"
  },
  "model_bundle_version": "heuristic_v1.0.0",
  "config_version": "2026-09-28.1"
}
```

The numbers above are illustrative only.

# Appendix E - Critical negative tests

Codex should implement automated tests asserting that each prohibited path fails.

1. Candidate already has 10 active decisions; 11th allocation attempt -> rejected.
2. Vacancy already has 10 employer decisions; 11th -> rejected.
3. Employer upgrades plan; rank order remains identical when all other state fixed.
4. Candidate tries to message employer before mutual match -> 403.
5. Scoring code attempts to import protected-audit schema -> architecture/test failure.
6. Candidate Pass then sends Interested on same token -> conflict.
7. Expired decision Interested -> conflict.
8. Job closes while decision active -> decision cancelled, no future mutual match.
9. Duplicate event delivered twice -> one resulting transition.
10. Two workers race for candidate's final slot -> exactly one succeeds.
11. Employer creates duplicate vacancy to multiply capacity -> flagged/blocked per duplicate policy.
12. Model scorer unavailable -> no random filler recommendation.
13. No positive-surplus pairs -> active count can remain below 10.
14. Background-check field appears in generic scorer features -> test failure.
15. Payment/spend field appears in scorer input -> test failure.

# Appendix F - Open empirical parameters

These remain intentionally configurable until deployment data exists:

- decision TTL;
- waiting queue cap;
- retrieval pool size;
- exploration budget;
- pair cooldown;
- market-cell granularity;
- attention-price clamp;
- congestion-price clamp;
- reliability display sample threshold;
- reminder timing;
- model retraining cadence;
- exact employer subscription levels.

Changing these values does not alter the fundamental TEN architecture.

# Appendix G - Future-compatible extensions

The following are compatible but not required for v1:

- mobile apps;
- calendar integrations;
- ATS integrations;
- enterprise SSO/SCIM;
- richer organization analytics;
- multi-opening pooled roles;
- interviewer panel workflow;
- reference checks;
- structured skills assessments;
- cryptographic/verifiable credentials;
- batch/global optimizer;
- contextual bandit exploration;
- learned survival models;
- learned congestion response;
- international jurisdiction policy engine.

Any extension must preserve the core invariants unless an ADR formally changes the product architecture.

# Appendix H - Final Codex instruction

Build TEN as a **bounded-attention clearing system**, not as a conventional job board with an AI recommender attached.

When a design choice is ambiguous, prefer the option that:

1. reduces unnecessary human decisions;
2. preserves double opt-in;
3. preserves bounded active decision surfaces;
4. keeps candidate/employer agency;
5. makes the decision auditable;
6. prevents monetization from corrupting rank;
7. treats uncertainty explicitly;
8. avoids inventing a global human score;
9. keeps data minimization and privacy intact;
10. leaves empirically unknown constants configurable rather than pretending they are proven.

**End of TEN v1 Product & Technical Specification.**
