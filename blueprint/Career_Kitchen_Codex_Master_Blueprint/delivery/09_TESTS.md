# 09 — Complete test plan and acceptance pseudocode

## Testing hierarchy
- `unit`: pure functions, eligibility, pricing, models, status transitions, ACL, hashing.
- `integration`: PostgreSQL transaction, row/advisory locks, Alembic, outbox, API authorization, event replay.
- `contract`: generated OpenAPI and TypeScript API type compatibility; standard error envelopes.
- `E2E`: real browser sign-in stub, candidate/employer flow, chat, PACT readiness, offers, role edits.
- `algorithm`: reproducible exact toy fixtures, adversarial failure scenarios, synthetic holdout, ablations, calibration.
- `security`: tenant isolation, privilege escalation, PII/attachment access, rate limits, SSRF/XSS, consent revocation.
- `nonfunctional`: load, migrations, backups, latency, accessibility and observability.

## Critical invariant tests (must exist before any optimizer)
```python
TEST candidate_card_cap:
  candidate selected cap=3 and platform cap=10;
  issue 3 valid ACTIVE candidate cards;
  4th concurrent request -> reject CAP_FULL;
  after one expires, 1 new card may be issued;
  assert max active_count never >3
TEST vacancy_card_cap:
  company role with cap=2; send 20 concurrent proposals; exactly 2 ACTIVE employer cards
TEST double_opt_in:
  first side Interested -> WAITING/other side decision, never mutual;
  other side Interested on SAME cycle -> one MUTUAL_MATCH;
  same actor Interested twice -> single transition, idempotent response
TEST stale_pass_cycle:
  Pass closes cycle permanently; old Interested token rejects;
  new cycle only after cooldown/meaningful allowed reset
TEST expired_token:
  after TTL -> 409 EXPIRED_DECISION, even if late request occurs at same time
TEST role_closed:
  closing vacancy invalidates active cards + waiting; no new proposals or messages without mutual
TEST race_last_slot:
  50 workers race for candidate's final slot; exactly 1 commits
TEST race_same_pair:
  50 proposals for same candidate/job -> 1 active cycle & 1 issued card
TEST idempotent_events:
  process same outbox message N times -> one stage transition, no duplicate notifications
TEST cross_tenant:
  employer A cannot see B's candidates, match, evidence URLs, policies or analytics
TEST private_candidate_floor:
  employer response exposes only consented compensation alignment; cannot query floor
TEST identity_spoof:
  body.user_id/body.org_role cannot self-promote to signatory/verifier
TEST billing_isolation:
  changing paid tier with all else fixed cannot change match ranking or feature vectors
TEST audit_data_isolation:
  import protected_audit module from scorer must fail architecture/CI test
TEST no_chat_before_mutual:
  attempt POST /messages after one interested -> 403
TEST model_failure:
  no confidence/model -> baseline transparent heuristic; no filler card if surplus<=0
TEST no_auto_hire:
  PACT READY + mutual + offer accepted still not START_CONFIRMED
TEST candidate_withdrawal:
  withdrawal allowed, no discriminatory candidate score penalty
```

## PACT consent, evidence and role versions
```python
TEST policy_signature:
  recruiter without signatory role cannot authorize policy;
  signatory can only approve exact assigned role versions; step-up required
TEST optional_requirement_vs_essential:
  essential hard requirement cannot be relaxed by algorithm;
  ambiguous does not trigger automated exclusion without human clarification
TEST stale_policy:
  approval role version=3; edit salary increments role version=4;
  readiness v3 -> STALE; no disclosure until renewed auth+candidate consent
TEST reuse_evidence_not_disclosure:
  claim VERIFIED once but no grant for Org B; Org B cannot see claim nor document
TEST consent_revoked_midflight:
  grant revoked while shortlist being planned; execute role candidate reveal fails
TEST claim_expiration:
  claim VERIFIED until date; on date expires; proof invalidated and snapshot refreshed
TEST examiner_self_verification:
  candidate cannot certify own evidence as independent verifier
TEST authority_revoked:
  org removes signatory while question pending; subsequent approve attempt -> 403
TEST verification_status:
  no actual issuer/independent check -> PENDING not VERIFIED, even if uploaded
TEST invalid_authorization_scope:
  policy for role A cannot apply to role B despite same employer/title
TEST proof_tamper:
  modified terms/evidence digest or proofId from other actor -> invalid
TEST candidate_consent_distinct:
  candidate acknowledging terms is not Interested decision; cannot create mutual
```

## Global matching/reliability/WITNESS tests
```python
TEST greedy_independence_counterexample:
  correlated shared failure makes top-10 lower fill P than risk-aware group in toy scenario;
  both produce RESEARCH_ONLY label, not certified
TEST correlation_floor:
  model common job failure q=.005; no shortlist passes modeled .999 threshold
TEST min_n_calculation:
  independent p=.5 -> n=10 needed; p=.9 -> n=3;
  implementation must define hard n limit and math rounding
TEST no_candidate_double_exclusive_reserve:
  same candidate across 10 employer roles -> at most one active exclusive reserve
TEST soft_shortlist_not_exclusive:
  candidate may be on multiple read-only plans, NEVER counted as certain hire by both
TEST existing_commitment_preserved:
  optimizer swap doesn't revoke already-issued human decision or mutual commitment
TEST gap_no_info:
  scenario model unknown -> CANNOT_CERTIFY, even if high point prediction
TEST misspecified_probabilities:
  hidden success rates reduced -> model-threshold pass cannot become verified badge
TEST shortlists_include_shared_risk:
  correlated risks lower yield vs independence; no optimistic multiplication if unknown
TEST consented_evidence_only:
  WITNESS compiler never proposes unapproved disclosure as completed action
TEST complementary_actions:
  only [human employer answer AND candidate proof AND consent] unlock edge;
  individually useless actions may still be bundled and scored jointly
TEST employer_denial:
  answer DENIED -> no edge unlock, no silent role change; costs still counted
TEST model_stale:
  model_version or role hash changes -> discard plan and recompute
TEST bounded_runtime:
  algorithm times out safely -> original v1 fallback, no blank UI or side effect
TEST pilot_scope:
  advanced controller cannot execute when not explicitly enrolled/authorized
TEST optimistic_feasibility_bound:
  if idealized oracle risk >.001, mark model-infeasible, NOT real-world impossible
TEST scenario_probabilities:
  weights sum 1, finite p in [0,1], no uncalibrated default '99.9'
TEST no_false_claim:
  status CANNOT_CERTIFY under all synthetic benchmarks; there is no public % label
```

## Historical data/causal evaluation tests
```python
TEST chronology:
  train before calibration before test, no future event in as-of features
TEST earliest_usable_stage:
  records only starting at interview/offer excluded from pre-introduction modeling
TEST label_proxy:
  historical 'Offer Accepted' not tagged as verified job start
TEST no_counterfactual_claim:
  unseen candidate-job pair cannot be labeled rejected or hired from JTH
TEST no_leakage:
  resume last-edited date, stage event, offer outcome not available at scoring time
TEST drift_detection:
  shift in accepted offers/base rate -> recalibrate or disable research reliability gate
TEST denominator:
  zero-shortlist and cancelled-role enrolled vacancies remain in primary rate denominator
TEST calibration_prospective:
  externally verified starts + sample threshold + cohort coverage required before VALIDATED
TEST audit_suppression:
  small protected group analytics cell suppressed, not served to employers
```

## API/auth tests
```python
for route in write_routes:
   reject missing auth, wrong tenant, wrong role, mismatched version,
          duplicate idempotency key different payload, invalid schema, forged HTTP origin
for route in sensitive_read_routes:
   reject direct object ID guessing, expired signed media URL, role-disabled member
for webhook in trusted_webhooks:
   reject unsigned, forged signature, wrong issuer, replayed event
for upload in resume_or_document_upload:
   reject oversized, MIME spoofed, malicious file, network URL SSRF, executable content
```

## Accessibility and E2E acceptance scenarios
```text
E2E 01 Candidate can sign in, complete profile, set max 2 active cards, pause/resume.
E2E 02 Employer can create verified org + active role with lawful requirements.
E2E 03 Candidate-first Interested creates employer card, not chat; employer Interested unlocks chat.
E2E 04 Employer-first Interested creates candidate card; candidate Pass closes cycle, no chat.
E2E 05 Signatory authorizes exact PACT policy; verifier validates evidence; candidate explicitly grants access; readiness status Ready.
E2E 06 Candidate revokes evidence; readiness Stale, file no longer accessible to new request.
E2E 07 Employer edits pay range; readiness invalidated, candidate sees re-acknowledge prompt.
E2E 08 Employer closes role; relevant cards cancelled and consistent across both dashboards.
E2E 09 Interview -> offer -> candidate accept -> still not verified hire; corroborated start -> verified status.
E2E 10 Shadow mode on/off yields byte-equivalent visible state and identical baseline decisions.
E2E 11 Admin sees fictional research diagnostic with clear no-reliability-claim labels.
E2E 12 Full demo reset twice yields deterministic scripted states, works on mobile and keyboard.
```

## Nonfunctional targets (engineering requirements, not benchmark claims)
- UI page loading and common API requests suitable for hackathon demo on standard laptop/mobile, with explicit profiling and no blocking global solver in web request.
- Model/optimizer wall clock bounded, e.g. 1–3 seconds for small snapshots in demo, configurable; safe fallback under timeout.
- DB transaction for issuing card intentionally short (<300ms target under local test; measure rather than assume).
- Scale tests for sparse graphs, 100k candidates/10k roles using synthetic fixtures and bounded retrieval; never materialize 1e9 edges.
- Replay reproducibility: same event stream and frozen model/config -> same state hashes, excluding nondeterministic recorded timestamps handled by injected clock.
- Accessibility smoke: focus return after modal, form errors announced, keyboard actions available, visually readable contrasts.

## Completion gates
1. No release if any invariant, tenant isolation or consent test fails.
2. No PILOT if shadow parity, calibration, legal review, fairness/appeal controls unavailable.
3. No 99.9% label without prospective evidence and approved statistical standard.
4. Actual claimed metrics must be generated by scripts against disclosed, permitted data—not hardcoded.
5. No background data collection of LinkedIn/Devpost without permission and compliant source agreements.
