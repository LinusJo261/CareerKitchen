# 02 — Codebase architecture, interfaces and deployment topology

## Monorepo tree (target; pseudocode names are prescriptive)
```
career-kitchen/
  AGENTS.md
  apps/
    web/                                 # Next.js App Router
      src/app/(public)/                 # home, how-it-works, privacy, terms
      src/app/(auth)/                   # sign-in, callback, onboarding
      src/app/(candidate)/              # dashboard, decisions, matches, settings, evidence
      src/app/(employer)/               # company setup, roles, candidates, PACT, pipeline
      src/app/(admin)/                  # admin/reporting under RBAC
      src/components/{common,candidate,employer,matching,pact,chat}
      src/{lib,contracts,state,styles}
      e2e/
    api/                                 # FastAPI main API
      app/main.py
      app/api/v1/routers/{sessions,candidates,organizations,vacancies,requirements,evidence,consents,pact,decisions,matches,messages,offers,availability,shortlists,analytics,notifications,billing,privacy,admin}.py
      app/core/{settings,auth,roles,rate_limit,errors,logging,flags}.py
      app/db/{base,session,models,queries,migrations}.py
      app/schemas/{identity,candidate,employer,role,matching,pact,reliability}.py
      app/services/{profile,organizations,requirements,verification,consent,pact,readiness,decision_machine,offers,messaging,notifications,privacy,billing}.py
      app/matching/{retrieval,baseline,score,attention,scenario,portfolio,witness,action_policy,exchange,calibration,reliability,shadow_adapter}.py
      app/workers/{event_dispatcher,expiry,replenish,notification_worker,model_monitor,audit_metrics}.py
      app/integrations/{oidc,email,storage,verifier,calendar,payments}.py
      tests/{unit,integration,contract,concurrency,security,algorithm,fixtures}/
    worker/                               # worker process (may reuse apps/api package)
  packages/{api-client,schemas,ui}/
  infra/{compose,postgres,redis,deploy,secrets,monitoring}
  scripts/{reset_demo,seed_demo,run_replay,validate_evidence,benchmark}
  docs/{product,api,runbooks,compliance,architecture,adr}
  .github/workflows/{ci,security,deploy}
```

## The strict service boundaries
1. **Identity/authorization**: user auth, tenant membership, personal ownership, verifier roles. Never delegate auth to client.
2. **Core lifecycle**: candidate/role/decision/match states, approved stage transitions and locked card-cap accounting, PII disclosure.
3. **PACT**: records policy approvals, evidence attestation, consent, readiness proof, revocation. Separate from `MATCH` and `HIRED`.
4. **Matching**: takes immutable sanitized snapshots containing *only permitted features*; emits scored candidate plans; cannot directly mutate DB or contact users. Baseline engine can create proposals, but only a separate transactional executor can issue cards.
5. **Reliability**: separate empirical validation service. Predictive model produces `research_prediction`; a different proof gate returns `cannot_certify` until stringent deployment gates passed. Never conflated.
6. **Workers**: consume outbox, call services with idempotency, retry safely; no direct updating model-predicted hires.
7. **Analytics**: privacy-isolated factual counts and eval design. Audit protected data segregated and inaccessible to ranking.
8. **Billing**: employers can buy active role capacity or company admin services, but no ranking boost, placement fees tied to biased allocation, or promoted candidate ranking.

## Data/event movement
```
Browser -> Next.js server -> authenticated API request -> FastAPI router
  -> Pydantic validation -> RBAC and business invariant checks -> service
  -> Postgres transaction + outbox event -> commit
  -> outbox dispatcher -> worker -> notification/reconciliation

reconciliation event -> snapshot builder -> baseline score + proposals
  -> proposal_executor with locks -> decision cards + audit/outbox
  -> shadow sidecar read-only proposes PACT/R99/WITNESS alternatives
  -> secure research logs only (no UI exposure or messages)
```

## Request conventions
- HTTP JSON `/v1`; UUID IDs; UTC RFC3339 datetimes; typed enums, cursor pagination, bounded size.
- Bearer OIDC or secure backend-for-frontend session; all writes require idempotency key; all state changes include optimistic `expected_version`/If-Match.
- Validation errors 422, unauthorized 401, forbidden 403, absent 404, state conflict 409, version conflict 412, rate limit 429.
- Correlation ID, actor ID, request ID, typed error code; never include raw PII/resume in logs.
- Request validation applies to *every* FastAPI endpoint and every Next.js Server Action, not only form fields.
- Web must not expose server auth tokens to local storage or write secrets into the browser bundle.
- Use transactional outbox rather than 'DB commit then publish queue' which loses events on crashes.

## Execution modes
```
if FEATURE_MODE == BASELINE: execute v1 baseline proposal lifecycle only
if FEATURE_MODE == SHADOW: execute v1 baseline normally; evaluate advanced on immutable copy after commit and record difference
if FEATURE_MODE == PILOT and actor_enrolled and policy_gates_pass:
    propose advanced action to authorized human; execute only if valid and permitted;
    otherwise run baseline
```
- The initial feature mode must be BASELINE or SHADOW, never blanket PILOT.
- Circuit breaker: if calibrator unhealthy, telemetry missing, model drift high, override conflicts, timeouts, or risk gate ambiguous -> BASELINE.
- Never let untrusted shadow computations hold open baseline DB transactions or delay user actions.

## Security system diagram
```
Auth provider -> validated sessions -> FastAPI RBAC -> tenant scoped Postgres
                                              |-> object store (signed short TTL read)
                                              |-> integration adapter (email/calendar)
                                              |-> worker queue (outbox)
Private protected audit storage -------------> compliance analyst service only
Payment records ------------------------------> billing service only
```

## Defaults to document as tunable research parameters
- active card max platform 10, candidate selected max 1..10, employer per role max 1..10.
- 72h decision TTL, 2 reminders max, configurable (not validated optimum).
- waiting queue caps default 10 on each side, capped by load.
- max search pool in matching tunable per market; risk model scenario count bounded and versioned.
- shortlist `n` optimized as 0..min(policy_max,user/employer choice,available_pool); **not** universally 10.
- make role activation reject invalid salary, essential requirements, missing authorized owner, empty description.

## Failure strategies
Postgres unavailable -> return temporary failure, never decide in memory; queue unavailable -> outbox remains for retry; provider auth unavailable -> fail closed; verifier unavailable -> evidence remains pending; shadow algorithm timeout -> skip it and keep baseline; model calibration insufficient -> cannot_certify; employer authority revoked -> invalidate PACT proofs and pending actions; employer closes role -> expire cards/shortlists and notify all exposed parties.
