# 07 — Background jobs, integrations, platform operations, monitoring and security

## Worker scheduler & durable events
```python
async def commit_mutation_with_event(tx,model_updates,events):
    apply model updates
    insert outbox records for events IN SAME DB TRANSACTION
    commit

async def poll_and_dispatch_outbox():
    while running:
        rows = SELECT outbox WHERE dispatched_at IS NULL ORDER BY created_at
               FOR UPDATE SKIP LOCKED LIMIT 100
        for row in rows:
            try publish_to_worker_queue(event_id,row.event_type,minimal_payload)
            except retryable_error: schedule backoff; keep row undispatched
            else: mark dispatched_at=now

async def consume_job(name,event_id):
    if inbox_consumptions.contains(name,event_id): return ACK
    begin db txn; check event version; process via idempotent service; insert consumption;
    commit; return ACK
    if retryable: backoff with jitter; bounded max attempts; dead letter;
    if poison: quarantine with audit, do not silently drop or create fake state
```

## Event handlers
```python
ON candidate.activated, candidate.profile_updated, vacancy.activated,
   vacancy.updated, decision.answered, decision.expired, match.created,
   claim.verified, consent.revoked, policy.clarification_resolved:
      enqueue_reconcile(affected_candidate_ids,affected_role_ids,market_cells)
      invalidate_cached_scored_edges_and_shadow_plans
      notify_authorized_parties_if_necessary

ON role.closed:
      expire pending decisions and waiting; release exclusive reservations,
      invalidate readiness and shortlists, notify authorized affected humans
ON claim.revoked OR consent.revoked:
      invalidate readiness, prohibit new disclosure, revoke ACL token at proxy,
      replan affected roles
ON policy.version_changed:
      require renewed consent and approval; no stale employer question answers
```

## Reconciliation worker
```python
async def reconcile(event):
    key = hash(market_cell,affected_ids,state_versions)
    deduplicate_or_coalesce(key, short-window)
    if backend_mode BASELINE/SHADOW:
        run baseline v1 propose+execute under proper locks
    if SHADOW:
        schedule sidecar computation after baseline commit on read-only principal
    if PILOT:
        run limited planner with timeout; present human-approved action when permitted
        fallback to baseline if any missing authority/timeout/uncalibrated model
```

## Expiry and notification jobs
```python
EVERY_5_MINUTES: expire ACTIVE cards with expiry passed; expire waiting queues;
                 expire consent grants/reservations/readiness proofs;
                 emit outbox for released attention slots
EVERY_HOUR: pending decision reminders at configured intervals (max 2), respecting optouts
DAILY: detect stale vacancies, account for role timeouts, monitor calibration and drift
WEEKLY: aggregate privacy-safe usage metrics; audit duplicate employer/role abuse
```

## Model/algorithm job controls
```python
async def research_model_update():
    use only permitted consent-aligned events, as-of features, chronological split
    separate models for candidate-first vs employer-first and stage conditional estimates
    train->calibrate->shadow->approve/rollback; no automatic production promotion
    require fairness review and model card; register artifact hash, version and provenance

async def detect_model_drift():
    monitor input distributions, offer accept rates, response latency, calendar-time shifts,
            cohort-specific calibration, nonresponse/censoring, applicant pool changes
    if alarm: disable external reliability certification, limit pilot, return baseline
```

## External adapters
```python
OIDCProvider.verify_session(token) -> actor_id + identity; enforce issuer/audience/signature
EmailProvider.send(template_key,recipient,variables_safe) -> provider_id
ObjectStore.put_private_scanned(content,mime,tenant,key_policy) -> opaque_ref
ObjectStore.temporary_read(ref,actor,purpose,ttl) -> short-lived URL/proxy token
AttestationVerifier.verify(claim,issuer) -> signed outcome (never accept candidate's own stamp)
CalendarProvider.create_event(owner_token,meeting) -> provider_event_id (opt-in only)
BillingProvider.webhook(signature,payload) -> subscription status (never ranking influence)
All integrations: timeout, circuit breaker, retry policy, limited PII, audit and key rotation.
```

## Observability
- Structured event logs with request_id, trace_id, pseudonymized actor_id, org scope, model version, state version, error code, no private resume/claims/salary secret.
- Metrics: auth failures, 403 rate, API p95 latency, transaction conflict retry, outbox queue lag, decision capacity usage, expired cards, candidate/employer response times, state-machine invalid transitions, proof invalidations, shadow mutation count (=0), planned vs delivered shortlist, anti-overclaim checks, abuse reports.
- Traces from API -> DB commit -> outbox -> worker; transaction integrity dashboards.
- Alerts on duplicate successful active reservations, >10 active cards, cross-tenant access attempts, unauthorized policy changes, miscalibrated certified status, no idempotency logs, suspected leaked secrets.
- Alerts should trigger fallback or kill switch when model/authorization paths fail.

## Local developer environment
```bash
# PSEUDOCOMMANDS; implement scripts in repository
make bootstrap    # install uv/venv, pnpm dependencies, git hooks
make dev          # docker compose Postgres+Redis, FastAPI, Next.js, worker
make migrate      # alembic upgrade head
make seed-demo    # fictional market only, resettable
make test         # pytest + frontend unit + integration
make test-e2e     # Playwright with seeded app
make lint         # ruff, mypy/pyright, eslint, prettier
make contract     # openapi export + generated TS client
make replay       # seed and event replay deterministic equality test
```

## CI/CD & environments
```
on_pull_request:
  static format/lint/types -> unit tests -> DB migration up/down -> API contracts
  -> tenant/RBAC negative tests -> concurrency tests -> integration E2E
  -> dependency/secrets scan, SAST, basic accessibility smoke
  -> no external prod credentials

on_main_merge:
  build signed artifacts -> staging migrations/seed -> smoke+security -> deploy staged
  production deploy only with manual approval and rollback plan
```
- Environments: dev, preview, staging, production; never share prod DB with previews. Feature flags keyed to pilot consent and tenancy.
- Secrets from managed store; rotate keys; separate auth/session from signing PACT digests.
- Postgres automated backups, PITR and restore drills; object-store lifecycle and deletion workflows; versioned migrations.
- Deploy API and worker as persistent containerized services; Next.js optionally Vercel; worker must not rely on serverless timeout-based cron for critical DB reconciliation.
- Network policies: read-only matching planner creds, strict DB role separations, RLS where possible; no direct public admin/Redis access.
- Disaster: when queue lost, outbox replay; when risk service down, v1 continues; when consent revoked while media access exists, media proxy denies fresh requests; when offer stage corrupted, manual audit fix with versioned event.

## Privacy, legal and security checklist
- GDPR/CCPA-style rights as applicable: consent records, purpose limitation, export, deletion, retention, minor/age rules by jurisdiction, notices; counsel reviews actual jurisdiction.
- Employment AI: human oversight, bias validation, accessibility, reasonable accommodations and contest/appeal. Do not process disability info in matching scorer or issue pre-offer medical examinations. No citizenship status proxy ranking beyond legitimately required work eligibility.
- Opt-in collection only for external LinkedIn/Devpost/participant data; no unauthorized scraping or third-party terms violations. For hackathon imports, obtain meaningful participant consent and avoid publicly displaying private participants.
- Rate limits per IP/account/tenant/role, audit source IP as protected keyed digest where appropriate.
- Security reviews: CSRF, XSS, SQL injection, SSRF through imported URLs/resumes, object storage IDOR, tenant-scoped authorization, webhook signatures, prompt injection from resumes/descriptions, fake verified credentials, concurrency races, replay attack, MIME spoofing, file scans.
- Payment integration can only increase organization role capacity/admin tooling and cannot affect matching ranking.

## Expected runbook responses
```python
if 99_9_label_attempted_without_claim_approval:
    record security event; return CANNOT_CERTIFY; disable public label
if shadow_side_effect_count != 0:
    kill shadow mode; replay event audit; open severity-1 incident
if any candidate active decision count >10:
    disable affected allocation worker; repair counters from authoritative rows
if employer_tenant_data_breach suspected:
    revoke auth token/session; containment, audit log, legal notification as required
if recruitment stage incorrectly marks START_CONFIRMED:
    suspend metric publication; review corroboration, restore correct stage through
    an append-only correction event rather than mutating old audit silently
```
