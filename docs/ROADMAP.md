# Backend implementation roadmap

This workspace contained only the supplied blueprint ZIP; no application or Git
remote was supplied. The archived documents remain unchanged in `blueprint/`.
The separately developed v0 frontend is outside this implementation.

| Milestone | Dependencies | Implementation and acceptance |
| --- | --- | --- |
| P0 Foundation | none | FastAPI, strict settings, Supabase JWT validation, transaction boundary, Alembic, local PostgreSQL, CI; health/auth/migration round trip |
| P1 Onboarding | P0 | Candidate preferences/skills, verified organizations/team ACL, versioned vacancies/requirements; ownership, activation, tenant/privilege negative tests |
| P2 Clearing | P1 | Both first-mover directions, row/advisory locking, caps, waiting/cooldown/expiry, double opt-in, outbox; duplicates, stale/expired tokens, concurrent last-slot races |
| P3 Workflow | P2 | Participant-scoped chat, interviews, stage timeline, offers, independently verified starts; API end-to-end and unauthorized access tests |
| P4 PACT | P1–P3 | Exact version authorizations, scoped disclosure, evidence, live readiness and revocation; stale consent/signatory/tenant tests |
| P5 Shadow | P2/P4 | Immutable sanitized inputs, research persistence, deterministic parity, no planner writes or messages |
| P6 Algorithms | P5 | Original reciprocal formulas/prices, scenario risks, sparse global allocation/exchanges, WITNESS DAG and exposure timing; mathematical counterexamples and fail-closed certification tests |
| P7 Integration | P1–P6 | OpenAPI export, generated TypeScript client, fictional deterministic seed, v0 instructions; generated contract check |
| P8 Operations | P3/P4 | Durable PostgreSQL queue/worker, retries/deduplication, notifications, privacy, abuse and factual metrics; replay/retry/ACL tests |
| P9 Pilot gates | P5/P6 | Advanced live execution remains disabled until externally reviewed trial, legal/fairness approval, scoped consent and calibrated models exist |
| P10 Deployment | all | Railway containers, Supabase grants/storage, monitoring/backup runbooks, security checks; cloud deployment and restore drill require actual target credentials |

Each milestone uses executable tests. Deployment, independent organization or
credential verification, calibrated model training, prospective research claims,
email provider delivery and frontend integration cannot be claimed from local
fixtures. Current evidence and remaining dependencies are recorded in STATUS.md.
