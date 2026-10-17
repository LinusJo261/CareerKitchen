# 10 — Codex implementation order, ownership and 'done' checks

Do NOT implement every module simultaneously. Codex should complete one vertical slice, write tests, run them, inspect failures, then continue. Where an existing Career Kitchen repo exists, extend it instead of generating a duplicate codebase. This document assumes we are building a fresh repo if none is provided.

| Phase | Deliverable | Exit criterion |
|---|---|---|
| P0 | repo/bootstrap, Docker compose, FastAPI, Next.js, Postgres, migrations, auth, API client, CI | health, OIDC stub, DB migration, type checks and a basic page pass |
| P1 | user, candidate, organization, vacancy/requirements onboarding, tenancy | one candidate and verified employer can create active profiles/jobs; ACL tested |
| P2 | v1 reciprocal match engine, scorer interfaces, hard feasibility, decision state machine, 10-card cap, outbox | duplicate/race/stale transition tests pass; mutual only after double opt-in |
| P3 | candidate/employer dashboard and decision inbox, waiting, chat and process timeline | end-to-end cold-start -> two human interests -> mutual chat works |
| P4 | PACT terms, scoped policy approvals, evidence attestations, candidate consent, revocation, readiness | fresh proof, stale-version and no-permission paths tested E2E |
| P5 | shadow snapshot adapter, no-op WITNESS/R99 sidecar, audit parity | running shadow on/off yields identical live outcomes and state hashes |
| P6 | research Global R99, WITNESS, scenario risk, dynamic exposure in SHADOW only | bounded runtime, no live side effects, benchmark and ablations reproducible |
| P7 | employer PACT UI and internal research/shortlist dashboard + branching demo | fictional demo resets twice, truthful research labels |
| P8 | messaging/scheduling/offers/verified starts, notifications, privacy and abuse tools | actor-only endpoints, stage correctness, opt-in and export/delete |
| P9 | pilot opt-in executor + scope and human-review gates | legal/privacy review, model drift fallback, approved staged pilot fixtures |
| P10 | production hardening: backup, monitoring, fairness, security, load | deployment smoke, restore drill, 403 IDOR tests, no false guarantees |

## Recommended hackathon implementation subset
To get a strong demo without falsely claiming production research results, prioritize P0→P1→P2→P3→P4→P5→P7 and a small read-only Global R99/WITNESS visualization. Do not sacrifice core double opt-in, consent or transactional correctness just to show complex algorithms. PACT question approval and demo flows should work with real backend persisted events and fictional candidates, not static wireframes.

## Task ownership if team has 3–4 people
- Backend/matching lead: models, state machine, v1 scheduler, PACT domain semantics, integration, correctness.
- Frontend/product lead: auth-aware Next.js pages, candidate/employer UX, dashboard, PACT wizard, demo.
- Backend/infrastructure lead: OIDC, Postgres/Alembic, workers, notifications, storage, CI, deployment.
- Research/algorithm lead (can combine with backend): shadow R99, WITNESS, benchmarks, model safety and demo analysis.
These are roles, not necessarily distinct team members; no separate 'testing engineer' needed. Every engineer tests their own module and reviews shared invariants.

## Precise per-phase Codex loop
```text
1. Read AGENTS.md + README + relevant detailed files.
2. Inspect existing code and tell us which files will change.
3. Implement the smallest complete vertical slice; no placeholder fake success.
4. Add migration and data schema if needed, plus rollback/recovery note.
5. Add unit + authorization + concurrency/integration tests, then API contract tests.
6. Run code format, types and all relevant tests. Show actual commands and results.
7. Document what is real, what is mocked, and next dependency.
8. Commit or produce a patch for review (if authorized); don't overwrite unrelated code.
9. Proceed to next phase only after exit tests pass.
```

## Minimum acceptance criteria for milestone handoffs
P2 handoff must contain a real DB-backed `POST /decisions/{id}/interested` path; P4 handoff must demonstrate revoking claim access invalidates proof; P5 must show exact baseline replay equality with shadow on/off; P6 must show risk under correlation and a deliberately misspecified model fails 99.9 certification; P7 must show live API-driven demo states without exposed real user information.

## Risk register
- Unknown actual legacy repo => do not claim migration of actual app; use adapter contract and separate module.
- Model reliability unknown => can't show numerical 99.9 guarantee.
- Pilot job offers/starts missing => collect real verified starts before certification.
- Limited hackathon hours => build true simple product core before speculative optimizer.
- Consent and employer authority => false approvals are a launch blocker.
- Shared candidate demand => do not promise candidate as a guaranteed fallback to multiple employers.
- Hackathon organizer rules => separate pre-event research assets from new event-period submitted work, comply with current rules and disclose use accurately.
