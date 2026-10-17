# 04 — Full backend workflow pseudocode (FastAPI + services)

## 0. Composition root and dependencies
```python
# app/main.py — PSEUDOCODE
settings = load_strict_settings()  # fail if secrets, DB URL, issuer audience absent
engine = create_postgres_engine(pool_size=CONFIG_POOL, ssl_enforced=IS_PROD)
Session = create_async_sessionmaker(engine)
app = FastAPI(title="Career Kitchen API", version="1.0")
app.add_middleware(request_id, secure_response_headers, cors_allowlist,
                   rate_limit, error_mapping, redacted_audit_logging)
include_router('/v1/sessions', sessions_router)
include_router('/v1/candidates', candidates_router)
include_router('/v1/organizations', orgs_router)
include_router('/v1/vacancies', vacancy_router)
include_router('/v1/requirements', requirements_router)
include_router('/v1/evidence', evidence_router)
include_router('/v1/consents', consent_router)
include_router('/v1/pact', pact_router)
include_router('/v1/decisions', decision_router)
include_router('/v1/matches', match_router)
include_router('/v1/shortlists', shortlist_router)
include_router('/v1/messages', message_router)
include_router('/v1/notifications', notification_router)
include_router('/v1/privacy', privacy_router)
include_router('/v1/analytics', analytics_router)
include_router('/v1/billing', billing_router)
include_router('/v1/admin', admin_router)
app.health = check_internal_process_liveness_only
app.ready = check_database_schema_version_and_broker_connection
```

## 1. Authentication and authorization
```python
async def current_actor(request):
    signed_session_or_bearer = extract_secure_token(request)
    claims = await OIDC_JWKS.verify(
        token=signed_session_or_bearer,
        issuer=SETTINGS.oidc_issuer,
        audience=SETTINGS.api_audience,
        lifetime_checks=True,
        allowed_algorithms=SETTINGS.allowed_oidc_algorithms
    )
    user = db.users.lookup(issuer=claims.iss, subject=claims.sub)
    REQUIRE(user is active and email verified if required)
    RETURN Actor(user.id, auth_time=claims.auth_time, auth_strength=claims.amr)

async def require_org_role(actor, org_id, allowed_roles):
    # NEVER trust org_id/role passed in body or JWT custom role without DB verification.
    member = db.org_members.find_active(actor.id, org_id)
    REQUIRE(member.role intersects allowed_roles)
    RETURN member

async def require_vacancy_permission(actor, vacancy_id, permission):
    vacancy = db.vacancies.get(vacancy_id)
    membership = require_org_role(actor,vacancy.org_id,roles_for(permission))
    REQUIRE(acl(candidate_role=membership,vacancy_id,permission))
    RETURN vacancy

async def require_candidate_ownership(actor, candidate_id):
    REQUIRE(candidate_profiles.get(candidate_id).user_id == actor.user_id)
    RETURN candidate

async def audited_signatory(actor, policy_scope):
    REQUIRE(recent_auth(actor) OR step_up_reauthentication())
    REQUIRE(active_signatory_membership(actor, policy_scope.org_id))
    REQUIRE(explicit_approval_rights(actor, every(policy_scope.vacancy_ids)))
    RETURN verified_actor

async def idempotent_mutation(actor, route, key, request, fn):
    REQUIRE(valid_idempotency_key(key))
    BEGIN DB TRANSACTION
      old = LOCK idempotency record for (actor,route,key)
      IF old exists:
          REQUIRE(old.request_hash == canonical_hash(request), else 409)
          RETURN old.stored_response
      result = await fn()
      store idempotency_record(status, request_hash, response)
      INSERT outbox events emitted by fn
    COMMIT
    RETURN result
```
Tokens never contain self-appointed recruiter/admin privileges. Protected attributes are stored outside the matching DB/read roles. Server Actions have the exact same authorization policy as REST; don't rely on Next.js page guard alone.

## 2. Candidate services
```python
async def upsert_candidate_profile(actor, input, expected_version):
    REQUIRE(verified_session(actor))
    VALIDATE schema: normalized role interests, hard/soft types, no malicious URLs,
           max_active_decisions between 1 and 10, plausible locations
    BEGIN TRANSACTION:
      profile = SELECT candidate_profile WHERE user_id=actor.id FOR UPDATE
      CHECK optimistic_version(profile, expected_version)
      update candidate-owned nonprivileged fields
      invalidate eligibility-snapshot hashes and stale model features
      if contract-affecting change: invalidate relevant readiness proofs
      append profile audit and emit candidate.profile_updated
    COMMIT
    return sanitized_profile_to_owner

async def upload_resume(actor, file):
    REQUIRE own profile and terms accepted
    REQUIRE size/type limit; validate file bytes, malware scan, strip active content
    store encrypted file; issue private object id
    parse in restricted sandbox with no URL-following/tool execution
    return proposed_structured_fields_pending_candidate_confirmation

async def activate_candidate(actor):
    BEGIN TX with candidate lock:
      require profile completeness, consent, not suspended, lawful user status
      state=ACTIVE; version++
      outbox candidate.activated

async def pause_candidate(actor):
    BEGIN TX with candidate lock:
      state=PAUSED
      cancel or suspend candidate-visible active cards per documented policy
      expire exclusive reserves if any with consent-aware notifications
      keep mutual matches unless explicit withdrawal
      emit candidate.paused, replan affected market

async def block_organization(actor, org_id):
    check ownership
    save unique block
    cancel non-mutual decisions/exposures for blocked org under lock
    disable new allocations to org
    don't disclose block reason to employer
```

## 3. Employer/role services
```python
async def create_organization(actor,data):
    require approved account and rate-limit
    validate domain and legal label (domain ALONE not proof of hiring authority)
    create organization PENDING_VERIFICATION; membership initial admin pending review
    emit organization.created

async def verify_organization(admin_or_operator,org_id,evidence):
    require permitted verifier and actual evidence; verify domain/entity through provider
    review suspicious duplicates; update status and audit
    emit organization.verified only after completed verification

async def create_vacancy(actor, input):
    require recruiter/org_admin in valid org and active role capacity
    check salary range valid, currency, country, owner, requirements and role structure
    reject discriminatory hard filtering and unlawful text; request human revision
    create DRAFT vacancy with immutable version snapshot

async def activate_vacancy(actor,vacancy_id,expected_version):
    require_vacancy_permission(actor,vacancy_id,'activate')
    BEGIN TRANSACTION with role lock:
      check version, verified org, complete role, at least one opening,
            essential requirements human-reviewed, salary limits and role owner
      vacancy.state=ACTIVE; publish version; outbox vacancy.activated

async def edit_vacancy(actor,id,patch,expected_version):
    require permission and validated patch
    BEGIN TX role lock:
      UPDATE with version check; if hiring-terms changed: bump role_version
      invalidate all PACT policy authorization scope/role-version dependencies,
          consents/readiness based on changed terms, and pending shadow plans
      cancel/reissue existing affected decision cards where role details materially changed,
          subject to user notification and no silently changed contract
      emit vacancy.updated and replan

async def close_vacancy(actor,id,reason):
    BEGIN TX role lock:
      state=CLOSED or FILLED; close all open card cycles with CLOSED_JOB_CLOSED
      expire waiting/pending reservations; invalidate shadow plans
      preserve audit history and already-mutual process dispositions
      outbox vacancy.closed
```

## 4. Requirement taxonomy and policy clarifications
```python
async def define_requirement(actor, vacancy, request):
    require employer role owner and human review
    classify: ESSENTIAL vs PREFERENCE vs AMBIGUOUS
    ESSENTIAL must include job-related reason; never infer legal necessity via LLM
    PREFERENCE cannot be a hidden hard exclusion
    AMBIGUOUS prevents automated rejection until clarified
    persist classification, version and reviewer

async def request_clarification(system_proposal, actor):
    REQUIRE action is a suggestion; actor is authenticated signatory
    verify precise requirement, role version, employer and expiry
    prohibit changing legal/operational essentials
    create REQUESTED clarification; never apply a positive answer before response

async def respond_clarification(signatory, request_id, answer, exact_scope):
    REQUIRE signatory has authority over EVERY enumerated role
    BEGIN TRANSACTION lock roles + policy:
      REQUIRE pending & not expired & same role versions and requirement type
      if approved: record exact replacement requirement and policy scope per version
      if denied: mark DENIED, do not change feasibility
      invalidate affected snapshots and recalculate only after commit
      emit policy.clarification_resolved
```

## 5. Evidence, PACT and consent services
```python
async def initiate_evidence_claim(candidate_actor, claim):
    REQUIRE own candidate and job-related legitimate purpose
    submit evidence file using private store; set PENDING
    forbid public/unscoped resume export
    emit evidence.pending

async def verify_evidence(verifier_actor,claim_id,decision,source):
    require independent verifer role; no self-verification
    BEGIN TRANSACTION lock claim:
      verify issuer, source integrity, authenticity, relevance and expiry
      status = VERIFIED or FAILED; record verifier/time/claim hash
      emit evidence.changed; invalidate readiness dependent on claim
    COMMIT

async def consent_to_disclosure(candidate_actor, claim_id, vacancy_id, grant_kind, version, ttl):
    REQUIRE own claim, active vacancy, explicit displayed company, role & specific claim
    REQUIRE claim VERIFIED, grant_kind permitted, ttl bounded, terms_hash matches current role
    BEGIN TX:
      store evidence_access_grant with exact org and vacancy IDs, role version, expiry
      audit consent language hash
      emit candidate.consent_granted

async def revoke_disclosure(candidate_actor,grant_id):
    BEGIN TX lock grant:
      set revoked_at=NOW
      invalidate dependent readiness proofs and unexecuted share actions
      revoke object-store signed URLs at access proxy or short TTL
      emit candidate.consent_revoked
    COMMIT

async def authorize_pact_policy(signatory, role_ids, policy_spec):
    validate exact role IDs, same org, versions, lawful stage, terms/hashes
    REQUIRE step-up auth and signatory policy permission for all roles
    BEGIN TX roles sorted lock:
      write immutable versioned authorization with exact scope, expiry and revocation handle
      record what is authorized (screen/interview/conditional offer), NOT automatic hire
      emit pact.policy_authorized

async def acknowledge_terms(candidate_actor,vacancy_id,displayed_terms,ack_kind):
    require own candidate; check role active, employer verified
    compare displayed terms digest == canonical current role terms
    show private comp floor only to candidate; employer receives alignment bit
    write revocable consent by exact vacancy/role version/terms hash

async def compute_current_readiness(candidate_id,vacancy_id,actor_context):
    # Pure server-side read with fresh transaction snapshot, NOT stored proof alone.
    role=read_active_role(vacancy_id)
    policy=read_active_policy_for_exact_role_version(role)
    CHECK actual signatory authorization & not revoked & not expired
    candidate=read_active_candidate(candidate_id)
    terms_consent=read_current_candidate_terms_consent(candidate,role,terms_hash)
    grants=read_current_disclosure_grants(candidate,role)
    claims=read_current_verified_and_unexpired_evidence(candidate)
    CHECK every essential requirement met by legitimate evidence OR explicitly lawful equivalent;
          any flexible equivalence must be expressly employer-approved
    CHECK compensation, location, schedule and hard candidate constraints
    IF any condition fails: RETURN NOT_READY(reason_codes, opaque_safe_to_viewer)
    else RETURN ReadinessProof(candidate_id,role_version,terms_hash,policy_id,
                               evidence_hash,consent_hash,expiry=min(all expiries))

async def require_live_readiness(proof_id):
    proof=readiness_proofs.get(proof_id)
    recompute_current_readiness(proof.candidate,proof.vacancy)
    REQUIRE all hashes/versions/expiries match; otherwise mark proof STALE
    # Valid proof means prerequisites complete, NEVER hired or offered.
```

## 6. Atomic pair decision engine (the most critical backend service)
```python
async def issue_first_mover_card(proposal, idempotency_key):
    # proposals produced by match engine are untrusted suggestions until transaction validation
    BEGIN TX:
      # always acquire locks in stable sorted order to avoid deadlock
      LOCK vacancy row; LOCK candidate counter row; LOCK candidate-vacancy cycle
      CHECK source policy currently enabled and user/admin permission
      CHECK candidate ACTIVE, vacancy ACTIVE, role versions unchanged,
            hard feasibility NOW true, not blocked, no current conflicting cycle/cooldown
      chosen_side=proposal.first_mover
      CHECK chosen_side decision_count < min(platform10,selected_user_cap)
      CHECK waiting queue bounds and per-role available headcount
      INSERT pair cycle state=SIDE_DECISION_REQUIRED
      INSERT active decision_card(expiry, token_hash, actor, cycle_version)
      INSERT immutable exposure event from actual disclosed recipient (delivered_at)
      INSERT outbox decision.issued
    COMMIT

async def answer_decision(actor, decision_id, action, expected_version, idem_key):
    return idempotent_mutation(actor,'answer_decision',idem_key, request,fn):
      BEGIN TX:
        card=SELECT decision FOR UPDATE
        cycle=SELECT pair_cycle FOR UPDATE
        lock candidate counter + vacancy counter in canonical order
        CHECK card.ACTIVE, not expired, belongs to actor or actor's permitted vacancy
        CHECK cycle.version==expected_version and card belongs to current cycle
        CHECK vacancy active and candidate active and role version still valid
        CHECK action in ['INTERESTED','PASS']
        SET card = INTERESTED or PASSED; answered_at=server_now; bump_version
        IF action == PASS: close cycle w/ correct side terminal state
        ELSE:
          IF other_side_already_interested:
              REQUIRE other side's prior valid decision recorded on same cycle
              cycle=MUTUAL_MATCH
              create mutual_match once; no employer/candidate messaging before this event
          ELSE:
              cycle=SIDE_INTEREST_SENT
              IF other_side_has_card_capacity: issue other side decision atomically
              ELSE: create WAITING_OTHER_SLOT if waiting cap allows
        UPDATE actor capacity counts from authoritative decision states
        INSERT outbox decision.answered; if mutual, match.created
      COMMIT
      RETURN immutable response with updated state/version

async def expire_due_decisions(now):
    for card in batched due ACTIVE cards:
      BEGIN TX with card+cycle locks:
        if still ACTIVE and expires_at<=db_now:
          set EXPIRED, close or move to explicit cooldown policy, emit card.expired
      COMMIT

async def release_waiting_item(waiting_id):
    lock pair and side; revalidate consent/role/availability/cooldown,
    check capacity under lock; issue second-side card, remove waiting,
    else retain until expiry, or close if invalid

async def create_new_pair_cycle(old_pair):
    REQUIRE old cycle terminal and cooldown expired or meaningful approved state change
    no resurrection of declined cycle; create cycle_number +1 with new UUID
```
All idempotency checks must be durable, not `if already seen in Redis`.

## 7. Messaging, process stages, offers and verified starts
```python
async def send_message(actor,match_id,body):
    match=load_match(match_id)
    REQUIRE mutual status and actor belongs to match (or authorized role member)
    sanitize and length-limit; scan attachments; rate-limit; persist and outbox notify

async def propose_interview(actor,match_id,slots):
    require mutual; validate future slots + timezone + overlap; persist candidates proposal

async def confirm_interview(actor,proposal_id,slot):
    lock proposal; authorized participant; verify slot available; idempotent confirm;
    if consented calendar integration: create provider calendar event; recover on failure

async def record_stage_event(actor,cycle_id,stage,source):
    validate transition from previous stage; no direct jump from ELIGIBLE to HIRED
    employer and candidate permissions according to stage; immutable history
    emit stage.changed; update fallback model training queue (non-leaky)

async def issue_offer(authorizing_employer,match_id,terms):
    REQUIRE mutual, active authorized vacancy with openings, role-approved terms,
            valid employer signatory for OFFER stage and explicit candidate-facing terms
    CREATE offered state; send candidate notification; not a hire

async def accept_offer(candidate_actor,offer_id):
    REQUIRE candidate owns associated match and offer not expired
    record OFFER_ACCEPTED (still not verified start)

async def verify_employment_start(verifier,cycle_id,start_evidence):
    REQUIRE corroboration scheme and contest rights, actual started_at, audit trail
    DO NOT infer from candidate click or offer acceptance
    if verified: increment filled openings once in transactional role lock;
                 close remaining vacancies only when capacity exhausted
    emit verified_start.confirmed

async def withdraw(actor,cycle_id,reason):
    validate actor belongs, close permitted stage, notify only necessary participants,
    release exclusive reserves; never punish candidate rank for withdrawal
```

## 8. Notifications, activity, audit, analytics, billing, privacy
```python
async def request_notifications(actor,channel): save consent with frequency/quiet hours
async def enqueue_notification(event):
    recipients=derive_recipients_by_authorization(event)
    for recipient: if current ACL/opt-in allows, create notification_outbox
async def send_notification(worker,item):
    check event still current, prefer safe template, exponential retry & rate limit
    redact all candidate private evidence from email body; never expose competitor data

async def candidate_metrics(actor): aggregate only actor's own cards, stages, response deadlines
async def employer_metrics(actor,org): tenant-scoped role throughput, response time, offers, verified starts
async def compliance_metrics(auditor,cohort): purpose-limited separate audit schema, small-cell suppression

async def billing_plan_change(actor,org,new_plan):
    require org admin, gateway checkout idempotency, webhook signature verification
    update role capacity only; DO NOT pass plan/revenue to ranker or prices

async def export_personal_data(actor):
    verify subject, export only owned records, minimize third party identity,
    signed expiring link; include stage outcomes/corrections allowed by policy

async def request_deletion(actor):
    require verified authentication, apply lawful retention plan;
    delete/anonymize optional profile data, revoke grants and sessions,
    preserve minimal legally required audit events with access restrictions

async def report_abuse(actor,entity,reason):
    check visibility, create confidential case, throttle and human-review with appeal

async def audit_mutation(tx,action,entity,from_hash,to_hash):
    insert immutable row with authorized actor, tenant, correlation, reason, time
    # do not log raw resume, sensitive attributes, private floors, offer docs
```

## 9. Router pattern (repeat for every endpoint in API contract)
```python
@router.post('/vacancies/{vacancy_id}/activate', response_model=VacancyOut)
async def activate(vacancy_id:UUID,
                   payload:ActivateRequest,
                   actor:Actor=Depends(current_actor),
                   session=Depends(db_session),
                   idempotency_key=Header(required=True)):
    await require_vacancy_permission(actor,vacancy_id,'activate')
    return await idempotent_mutation(actor,endpoint_key,idempotency_key,payload,
            lambda: VacancyService(session).activate(vacancy_id,payload.expected_version))
```
Do not assume this is production-valid Python; Codex must implement robust actual dependency wiring and transaction closure.
