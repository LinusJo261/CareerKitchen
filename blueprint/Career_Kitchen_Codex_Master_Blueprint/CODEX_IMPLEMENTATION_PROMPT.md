# Paste this message into Codex inside the Career Kitchen repository

You are the implementation engineer for **Career Kitchen**, a bounded-attention, two-sided hiring-market application. READ AND FOLLOW `AGENTS.md` and all numbered blueprint files before coding. The requested output is a fully functioning, tested codebase built incrementally. Do not translate pseudocode mechanically without checking its consistency, security implications, and framework APIs. Existing repository code takes precedence over a guessed file path, while the safety invariants in `AGENTS.md` take precedence over older implementations.

The blueprint's complete file map is in `spec/02_ARCHITECTURE.md`; full DB schema in `spec/03_DATA_MODEL.md`; all baseline/PACT/WITNESS/R99 pseudocode in `pseudocode/04_BACKEND_FOUNDATIONS.md` and `pseudocode/05_MATCHING_INTELLIGENCE.md`; frontend in `pseudocode/06_FRONTEND.md`; workers in `pseudocode/07_WORKERS_OPERATIONS.md`; endpoints in `contracts/08_API.md`; tests in `delivery/09_TESTS.md`; phase order in `delivery/10_IMPLEMENTATION_PHASES.md`; demo and research metrics in `delivery/11_DEMO_AND_METRICS.md`.

**Implement ONLY the next uncompleted phase** from the ordered plan, with the following contract:
1. Inspect the repository, report existing code you can reuse and any conflict with blueprint. Do not create a parallel API/auth/database if one already exists.
2. Present the concrete files to add or change and the acceptance tests for this phase.
3. Implement real, persistent backend/API/frontend paths (not static fake backend responses), including migrations, schema, and authZ. Use feature flags for experimental components.
4. Implement tests: positive, negative, duplicate, concurrent, tenant isolation and contract tests where applicable.
5. Run commands for lint, types, tests, migration and demo, and present *actual* results. Don't state they pass without running them.
6. Clearly distinguish mock OIDC/demo evidence from real identity or employment verification. Do not make unsupported 99.9% reliability claims.
7. If you cannot finish the phase or dependency is missing, complete the safe subset, state exactly what's incomplete, and preserve baseline behavior.
8. Do NOT advance to the next phase until this phase's exit tests pass. The user can authorize proceeding to the next one.

START by implementing P0 (bootstrap + API/Web + Postgres + OIDC stub + CI) if the repository is empty, or by auditing current code and selecting the first incomplete phase if it is not empty. Include a short architecture decision record for any material deviation.

Critical invariants: max 10 active human decision cards per candidate and per role employer scope; human double-opt-in; no pay-to-rank, no protected features in scoring, no automatic hire, authenticated employer policy scope and version, consented evidence with revocation, auditability, baseline fallback, research-only Global R99 forecasts, read-only shadow parity.
