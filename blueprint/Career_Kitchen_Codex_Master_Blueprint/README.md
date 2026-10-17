# Career Kitchen — Complete Codex Implementation Blueprint

**Status:** implementation-ready **pseudocode**, contracts, sequencing and tests; **NOT a runnable application**. Product name is **Career Kitchen**. Historical project/research name TEN must not appear in public UI, marketing, routes, API domain models, or newly created components, except migration aliases and provenance notes.

## Start here

1. Read `AGENTS.md` (non-negotiable implementation instructions and safety invariants).
2. Read `spec/01_PRODUCT.md` and `spec/02_ARCHITECTURE.md` (product behavior and stack).
3. Read `spec/03_DATA_MODEL.md` (every stateful object, relationship, index, and uniqueness rule).
4. Read `pseudocode/04_BACKEND_FOUNDATIONS.md` (auth, RBAC, CRUD, privacy, state machine, events).
5. Read `pseudocode/05_MATCHING_INTELLIGENCE.md` (v1 fallback, candidate retrieval, PACT, WITNESS, Global R99, adaptive rollout, model/risk).
6. Read `pseudocode/06_FRONTEND.md` and `pseudocode/07_WORKERS_OPERATIONS.md` (entire application behavior).
7. Read `contracts/08_API.md` (REST endpoint inventory and payload shape).
8. Read `delivery/09_TESTS.md`, `delivery/10_IMPLEMENTATION_PHASES.md`, and `delivery/11_DEMO_AND_METRICS.md`.
9. Use `CODEX_IMPLEMENTATION_PROMPT.md` when delegating a phase to Codex.

## Definition of 'ALL'
This package specifies an implementable end-to-end **full-stack design**: identities, onboarding, candidates, organizations, roles, requirements, consent, evidence, vacancy readiness, shortlist algorithms, core clearing state transitions, chat, scheduling, notifications, process tracking, pilot analytics, billing isolation, privacy requests, migrations, workers, web UI, demo, testing and deployment. This is not literal source code; Codex must generate and test the implementation file-by-file. Auth provider, email/SMS, object store and payment gateway are swappable adapters.

## Research and reliability disclaimer
The 99.9% number is a **research goal** for `P(verified employment start from Career Kitchen delivered shortlist by fixed deadline)`; it is not a product claim, guarantee or calibrated model output. The existing Global R99, PACT, WITNESS and adaptive attention components are research prototypes based heavily on synthetic experiments. JTH v1.1 includes historical offer statuses, not verified starts nor outcomes for unobserved recommendations. A production API must answer `cannot_certify` until prespecified statistical, calibration, external prospective data, and legal/fairness gates pass. A company is not owed a hire and candidates must have full agency.

## Ground-truth baseline
This blueprint adapts the prior `TEN_v1_Codex_Specification.md` and PACT/R99/WITNESS research notes. When there is disagreement, the more restrictive authentication, privacy, double opt-in, human oversight, explicit authorization, and no-unsupported-claims rule wins. Preserve the **v1 scheduler** for fallback and shadow parity; never overwrite it with the research simulator. In this chat the actual Career Kitchen repository has not been supplied; all file paths below are proposed locations.

## Suggested stack
- Next.js + React + TypeScript, App Router, Tailwind, accessible component primitives, Zod schemas.
- Python FastAPI, Pydantic, SQLAlchemy 2 + Alembic; REST and generated OpenAPI client.
- PostgreSQL (authoritative state), pgvector optionally (retrieval), Redis (cache/queue/rate limits; never authoritative decisions), durable outbox + task workers.
- OIDC provider (no custom passwords), object storage for evidence, transactional email, optional billing gateway (isolated from allocation features).
- Separate analytics/audit namespace; object storage and encrypted secrets. Containerized local development.

## Three implementation modes
- `BASELINE`: only original bidirectional event-driven clearing.
- `SHADOW`: BASELINE executes; proposed advanced plans are logged, **never mutate state or contact humans**.
- `PILOT`: enabled only after explicit operations approval and scoped to consenting employers and candidates, with model/risk gating and automatic fallback.

## Important metric denominators
- `fill_rate`: # enrolled vacancies with verified starts from delivered shortlist by deadline / # all enrolled vacancies whose deadlines elapsed. Includes zero-shortlist, declined, cancelled, and unfilled vacancies, with separate reason breakdowns.
- `conditional_shortlist_fill`: fraction among vacancies receiving a shortlist (supplemental, never replace primary).
- `precision_of_predicted_99.9`: reliability calibration on a prospective cohort; **not** historical model confidence and never from acceptance proxy alone.
- `n_delivered`: unique candidates whose profiles were actually made visible to a vacancy, per recorded delivery event; queued/reserved/unshown candidates must NOT count as delivered. Candidate-side preflight efforts still count toward attention metrics.
- All metrics by window, cohort, role type, predicted-risk group, and consent/authority state; suppress small groups.

## Source links for implementers
- FastAPI security: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- Next.js Server Function security: https://nextjs.org/docs/app/api-reference/directives/use-server
- Source of original TEN spec: user's project document (not public)

**Never market research simulation gains or 99.9% as verified real-world performance.**
