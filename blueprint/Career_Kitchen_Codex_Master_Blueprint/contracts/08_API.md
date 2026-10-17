# 08 — Complete REST/OpenAPI and event contract pseudocode

## Standard envelopes
```
Request headers:
  Authorization: Bearer OIDC_access_token OR secure BFF session
  Idempotency-Key: UUID/string required on write
  If-Match: "<expected object version>" on state-sensitive updates
  X-Request-ID: UUID optional (server sets if absent)

200/201 response:
  { data: RESOURCE, meta: { request_id, resource_version, server_time } }

202 response:
  { data: { operation_id, status:"QUEUED" }, meta:{ request_id } }

Error:
  { error: { code:"EXPIRED_DECISION|STALE_ROLE|FORBIDDEN|CAP_FULL|...",
             message:"safe user-facing description", fields?: [...], request_id: UUID } }

Pagination:
  GET ?limit=20&cursor=opaque_signed_cursor
  returns { data:[...], page:{ next_cursor,has_more } }
```

## Session and profile endpoints
| Method | Route | Allowed actor | Semantics |
|---|---|---|---|
| GET | `/v1/sessions/me` | signed in | server-verified identity, permissions, org membership |
| POST | `/v1/sessions/logout` | signed in | revoke session |
| GET | `/v1/candidates/me` | candidate | owner profile + state |
| PUT | `/v1/candidates/me` | candidate | versioned profile write |
| PUT | `/v1/candidates/me/preferences` | candidate | hard/soft, pay, cap 1..10 |
| POST | `/v1/candidates/me/activate` | candidate | valid profile to ACTIVE |
| POST | `/v1/candidates/me/pause` | candidate | pause and cancel pending cards |
| GET | `/v1/candidates/me/decisions` | candidate | active bounded decision cards |
| GET | `/v1/candidates/me/waiting` | candidate | already-interested pending other side |
| GET | `/v1/candidates/me/matches` | candidate | mutual matches only |
| GET | `/v1/candidates/me/history` | candidate | own past cycles |
| POST | `/v1/candidates/me/skills` | candidate | add unverified skill |
| POST | `/v1/candidates/me/resume` | candidate | private scanned upload |
| POST | `/v1/candidates/me/blocks` | candidate | hide org and future matches |
| DELETE | `/v1/candidates/me/blocks/{org_id}` | candidate | unblock |

## Organization / vacancy endpoints
| Method | Route | Allowed actor | Semantics |
|---|---|---|---|
| POST | `/v1/organizations` | signed in with approval | create PENDING_VERIFICATION |
| GET | `/v1/organizations/{org_id}` | tenant member | limited org details |
| POST | `/v1/organizations/{org_id}/verify` | verifier | review legal entity |
| POST | `/v1/organizations/{org_id}/members/invite` | org admin | email invite w/ role; cannot self-appoint signatory |
| PATCH | `/v1/organizations/{org_id}/members/{member_id}` | org admin | role/update review, privileged grants extra verification |
| DELETE | `/v1/organizations/{org_id}/members/{member_id}` | org admin | revoke permissions |
| POST | `/v1/vacancies` | recruiter | draft with full validated schema |
| GET | `/v1/vacancies/{id}` | allowed actor | safe scoped role detail |
| PATCH | `/v1/vacancies/{id}` | role editor | bump role version and invalidate PACT proofs |
| POST | `/v1/vacancies/{id}/activate` | permitted employer | verify org & fields |
| POST | `/v1/vacancies/{id}/pause` | permitted employer | no new allocation |
| POST | `/v1/vacancies/{id}/close` | permitted employer | invalidate pending decisions and shortlists |
| GET | `/v1/vacancies/{id}/decisions` | assigned employer | active candidate cards <=10 |
| GET | `/v1/vacancies/{id}/waiting` | assigned employer | candidate-first interest waiting |
| GET | `/v1/vacancies/{id}/pipeline` | assigned employer | mutual/interview/offer stages |
| GET | `/v1/vacancies/{id}/metrics` | assigned employer | tenant-scoped factual aggregated metrics |
| POST | `/v1/vacancies/{id}/requirements` | editor | human essential/preferred taxonomy |
| PATCH | `/v1/requirements/{id}` | editor | versioned requirement reclassification |

## PACT / evidence / consent endpoints
| Method | Route | Allowed actor | Semantics |
|---|---|---|---|
| POST | `/v1/pact/policies` | verified signatory | create exact-role/version policy with terms hash |
| GET | `/v1/pact/policies/{id}` | scoped member | read employer policy with PII redacted |
| POST | `/v1/pact/policies/{id}/authorize` | signatory + reauth | actually authorize stage/scope |
| POST | `/v1/pact/policies/{id}/revoke` | signatory | invalidate dependency graph |
| POST | `/v1/pact/clarifications` | signatory/admin | request human approval of optional requirement change |
| POST | `/v1/pact/clarifications/{id}/respond` | signatory | approve/deny exact scope/role versions |
| POST | `/v1/evidence/claims` | candidate | upload candidate-controlled attestation request |
| GET | `/v1/evidence/claims/me` | candidate | own claim details |
| POST | `/v1/evidence/claims/{id}/verify` | independent verifier | verify/deny supported evidence |
| POST | `/v1/evidence/claims/{id}/revoke` | candidate/verifier | mark revoked and invalidate readiness |
| POST | `/v1/consents/terms` | candidate | accept exact role-version/terms hash |
| POST | `/v1/consents/evidence` | candidate | explicit vacancy+recipient+claim scope |
| GET | `/v1/consents/me` | candidate | consent ledger |
| POST | `/v1/consents/{id}/revoke` | owner | revoke immediately |
| POST | `/v1/pact/readiness/check` | scoped evaluator | fresh readiness status, NOT offer/hire |
| GET | `/v1/pact/readiness/{id}` | scoped actor | revalidate live proof before returning |

## Decisions and matching lifecycle endpoints
| Method | Route | Allowed actor | Semantics |
|---|---|---|---|
| GET | `/v1/decisions/{id}` | exact recipient | view card |
| POST | `/v1/decisions/{id}/interested` | exact recipient | atomic, one-use interested |
| POST | `/v1/decisions/{id}/pass` | exact recipient | atomic, one-use pass |
| GET | `/v1/matches/{id}` | one of participants | mutual match only |
| GET | `/v1/matches/{id}/messages` | participants after mutual | paginated sanitized messages |
| POST | `/v1/matches/{id}/messages` | participants after mutual | send message/attachment |
| POST | `/v1/matches/{id}/interviews/proposals` | matched actors | propose multiple time windows |
| POST | `/v1/matches/{id}/interviews/{proposal_id}/confirm` | matched actors | confirm available slot |
| POST | `/v1/matches/{id}/stages` | authorized actors | append process-stage evidence |
| POST | `/v1/matches/{id}/withdraw` | own participant | withdraw and preserve appeal path |
| POST | `/v1/matches/{id}/offers` | authorized employer | actual written offer |
| POST | `/v1/offers/{id}/accept` | candidate | offer accepted, NOT job started |
| POST | `/v1/offers/{id}/decline` | candidate | record voluntary outcome |
| POST | `/v1/matches/{id}/starts/report` | candidate or employer | submit evidence (pending verification) |
| POST | `/v1/matches/{id}/starts/verify` | independent verifier | corroborate start |

## R99, shadow and research endpoints (RBAC + mode flags)
| Method | Route | Allowed actor | Semantics |
|---|---|---|---|
| GET | `/v1/vacancies/{id}/shortlist/status` | assigned pilot employer | approved delivered list only, no other tenants |
| POST | `/v1/vacancies/{id}/shortlist/replan` | pilot owner | queue analysis, no automatic exposure |
| POST | `/v1/vacancies/{id}/shortlist/approve` | approved pilot signatory | approved plan; executor rechecks live state |
| GET | `/v1/internal/shadow/runs` | research admin only | diagnostics redacted; no candidate raw PII |
| GET | `/v1/internal/shadow/runs/{id}` | research admin | baseline-vs-alternative, input hash |
| POST | `/v1/internal/shadow/replay` | research admin | reproducible offline replay, no live mutation |
| GET | `/v1/internal/reliability/model/{id}` | research admin | calibration and assumptions |
| GET | `/v1/internal/reliability/cohorts` | auditor | pre-registered denominators/outcomes |
| POST | `/v1/internal/feature-flags/pilot` | approved operations/governance | scoped rollout, dual approval |

## Other endpoints
| Method | Route | Allowed actor | Semantics |
|---|---|---|---|
| GET | `/v1/notifications` | signed in | own notification inbox |
| PUT | `/v1/notifications/preferences` | owner | opt-ins/quiet hours |
| GET | `/v1/privacy/export` | owner | request private export job |
| POST | `/v1/privacy/delete` | owner | verified deletion request + audit |
| POST | `/v1/reports` | signed in | report abuse, no public details |
| GET | `/v1/organization/billing` | admin | billing details separate from scoring |
| POST | `/v1/organization/billing/checkout` | admin | checkout provider no algorithm coupling |
| POST | `/v1/webhooks/payments` | verified gateway signature | update subscription |
| GET | `/v1/health` | ops | liveness only |
| GET | `/v1/ready` | ops | readiness; private infrastructure auth where appropriate |

## Minimum payload contracts
```json
# Pseudotype; not actual JSON (comments indicate semantics)
DecisionAnswerRequest = {
  "expected_cycle_version": 7,
  "decision_token": "opaque_token_from_card",
  "reason_code": null // optional on Pass; private
}
DecisionAnswerResponse = {
  "pair_cycle_id": "UUID", "pair_state": "WAITING_EMPLOYER_SLOT|MUTUAL_MATCH|...",
  "card_status": "INTERESTED", "cycle_version": 8,
  "next_action": "NONE|WAITING|OPEN_MATCH"
}
PACTAuthorizationRequest = {
  "policy_version_id": "UUID", "exact_vacancy_ids": ["UUID"],
  "exact_role_versions": {"vacancy-uuid": 4},
  "decision_stage": "SCREENING|INTERVIEW|CONDITIONAL_OFFER",
  "terms_hash": "sha256:...", "expires_at": "RFC3339",
  "affirm_human_authority": true
}
EvidenceConsentRequest = {
  "claim_id": "UUID", "vacancy_id": "UUID", "org_id": "UUID",
  "role_version": 4, "grant_kind": "DISCLOSE_SUMMARY|DISCLOSE_DOCUMENT",
  "expires_at": "RFC3339", "checkbox_confirmed": true
}
ReadinessResponse = {
  "status": "READY|NOT_READY|STALE", "proof_id": "UUID|null",
  "expires_at": "RFC3339|null", "public_reason_codes": ["..."],
  "notice": "Ready means prerequisites verified, not an employment offer or hire"
}
ShortlistResearchPlan = {
  "vacancy_id": "UUID", "role_version": 4,
  "ordered_candidate_ids": ["UUID"], "delivered_candidate_ids": [],
  "plan_mode": "SHADOW", "modeled_nonhire_risk": 0.17,
  "certification_state": "CANNOT_CERTIFY",
  "certification_reason": "NO_PROSPECTIVE_VERIFIED_STARTS",
  "model_version": "research-v0", "state_hash": "sha256:...",
  "expires_at": "RFC3339", "proposed_witness_actions": []
}
```

## Application-generated events
```
auth.session_revoked
candidate.created candidate.updated candidate.activated candidate.paused
candidate.preferences_changed candidate.evidence_pending candidate.evidence_changed
candidate.consent_granted candidate.consent_revoked candidate.org_blocked
organization.created organization.verified organization.member_added
vacancy.created vacancy.activated vacancy.updated vacancy.paused vacancy.closed
pact.policy_authorized pact.policy_revoked pact.clarification_requested pact.clarification_resolved
pact.readiness_issued pact.readiness_invalidated
decision.issued decision.interested decision.passed decision.expired
pair.waiting pair.mutual pair.closed
message.sent interview.proposed interview.confirmed
process.stage_changed offer.issued offer.accepted offer.declined
employment_start.reported employment_start.verified employment_start.disputed
shortlist.proposed shortlist.approved shortlist.exposure_delivered shortlist.stale
shadow.completed shadow.failed model.drift_detected
privacy.export_requested privacy.delete_requested report.abuse_submitted
```

## Event payload minimalism
Each event: `event_id`, `kind`, `aggregate_id`, `actor_id_hash`, `market_cell_id`, `new_version`, `occurred_at`, `trace_id`. Fetch needed private data in permitted service after RBAC; do not put raw resume, salary floor, evidence bytes or medical fields in public event bus.
