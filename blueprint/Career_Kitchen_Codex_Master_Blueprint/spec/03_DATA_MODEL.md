# 03 — Full relational model, event states and migrations (SQL-oriented pseudocode)

The following is **schema pseudocode**, not vendor-valid migration SQL. Codex: translate to actual SQLAlchemy ORM + Alembic migrations with UUID PKs, FK constraints, restrictive delete policy, enum validation and intended indexes. Index names and foreign key cascade behavior must be verified against Postgres.

## Global conventions
```
COMMON_COLUMNS: id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
                version INT NOT NULL DEFAULT 1
SOFT_DELETE: deleted_at TIMESTAMPTZ NULL (where justified)
REF_ID: UUID NOT NULL REFERENCES ...
IMMUTABLE_AUDIT: append-only; disallow UPDATE/DELETE from API role
TENANCY: org_id carried where relevant; enforce via service and DB row-level security if feasible
ENCRYPTED: use app-level envelope encryption or provider-managed encrypted store for sensitive private fields
UTC: server clock only; never trust client timestamps for expiry/revocation
```

## Identity/tenancy
```
users(id, oidc_issuer, oidc_subject UNIQUE_WITH_ISSUER, verified_email, display_name,
      account_status, created_at, deleted_at, last_login_at)
user_consents(id,user_id,policy_key,policy_version,scope,granted_at,revoked_at,source_request_id)
organizations(id,legal_name,display_name,verified_domain,verification_state,
              verification_source,verified_at,tenant_status,created_by,version)
org_members(id,org_id,user_id,role ENUM[RECRUITER,HIRING_MANAGER,ORG_ADMIN,AUTHORIZED_SIGNATORY],
            membership_status,invited_by,approved_by,created_at,expires_at,
            UNIQUE(org_id,user_id,role))
vacancy_acl(id,vacancy_id,user_id,can_review,can_edit,can_approve_policy,assigned_by)
identity_sessions(id,user_id,session_hash,issuer,auth_time,revoked_at,expires_at) # optional if OIDC sessions offloaded
service_principals(id,service_name,permitted_scopes,revoked_at)
```

## Candidate data
```
candidate_profiles(id,user_id UNIQUE,headline,summary,primary_region,country,
                   current_state ENUM[DRAFT,ACTIVE,PAUSED,DEACTIVATED],
                   visibility_scope,available_from,available_until,
                   max_active_decisions SMALLINT CHECK 1<=value<=10,
                   resume_object_ref NULL,profile_confirmed_at,version,deleted_at)
candidate_preferences(id,candidate_id,role_families JSONB,hard_constraints JSONB,
                      soft_preferences JSONB,remote_policy,acceptable_locations JSONB,
                      compensation_floor_encrypted,desired_currency,
                      employment_types JSONB,notification_settings JSONB,updated_at,version)
candidate_experiences(id,candidate_id,organization_label,title,start_date,end_date,
                      details,confirmed_by_candidate,public_visibility)
candidate_skills(id,candidate_id,skill_taxonomy_id,assertion_level,
                 self_reported,years_experience,visibility,version)
skills_taxonomy(id,canonical_name,aliases JSONB,category,ontology_version)
candidate_blocks(id,candidate_id,org_id,reason_private,created_at,
                 UNIQUE(candidate_id,org_id))
candidate_availability(id,candidate_id,valid_start,valid_end,state,source,version)
profile_change_audit(id,candidate_id,changed_field,old_hash,new_hash,actor_id,time)
```
Do not add sensitive attributes as ranking features. Store required protected-class audit data (if lawfully collected) only in separate restricted schema/services and only for purpose-limited compliance analysis.

## Employer and role definitions
```
vacancies(id,org_id,owner_user_id,title,description,role_family,seniority,
          employment_type,work_mode,location_region,pay_min,pay_max,currency,
          openings_total,openings_remaining,deadline_at,desired_start_window JSONB,
          vacancy_state ENUM[DRAFT,ACTIVE,PAUSED,CLOSED,FILLED],
          verified_employer_at,published_at,closed_at,
          max_active_employer_decisions INT CHECK 1<=value<=10,version)
vacancy_requirements(id,vacancy_id,key,description,requirement_type ENUM[ESSENTIAL,PREFERENCE,AMBIGUOUS],
                     validation_method,lawful_reason,verified_by_user_id,version,retired_at)
vacancy_skill_requirements(id,vacancy_id,skill_id,required_level,preferred_weight,
                           requirement_id,version)
vacancy_owner_assignments(id,vacancy_id,user_id,role,created_at)
vacancy_status_events(id,vacancy_id,from_state,to_state,actor_id,reason,time,role_version)
```
Changing any contract-relevant vacancy field must increment version and invalidate readiness/authorization proofs until renewed. Employer can't quietly relabel `ESSENTIAL` as `PREFERENCE` without explicit approval and audit.

## Reciprocal clearing and decisions
```
pair_cycles(id,candidate_id,vacancy_id,cycle_number,first_mover ENUM[CANDIDATE,EMPLOYER],
            pair_state ENUM[ELIGIBLE,CANDIDATE_DECISION_REQUIRED,EMPLOYER_DECISION_REQUIRED,
                            CANDIDATE_INTEREST_SENT,EMPLOYER_INTEREST_SENT,
                            WAITING_CANDIDATE_SLOT,WAITING_EMPLOYER_SLOT,MUTUAL_MATCH,
                            INTERVIEWING,OFFERED,OFFER_ACCEPTED,START_CONFIRMED,
                            CLOSED_CANDIDATE_PASS,CLOSED_EMPLOYER_PASS,CLOSED_EXPIRED,
                            CLOSED_WITHDRAWN,CLOSED_JOB_CLOSED,CLOSED_FILLED_ELSEWHERE,
                            CLOSED_REJECTED,CLOSED_ADMIN],
            candidate_interested_at,employer_interested_at,
            closed_at,close_reason,model_version,created_at,version,
            UNIQUE(candidate_id,vacancy_id,cycle_number))
decision_cards(id,pair_cycle_id,decision_side ENUM[CANDIDATE,EMPLOYER],
               recipient_user_id,recipient_scope_id,issued_at,expires_at,
               status ENUM[ACTIVE,INTERESTED,PASSED,EXPIRED,CANCELLED],
               token_hash,expected_cycle_version,answered_at,version,
               UNIQUE(pair_cycle_id,decision_side,issued_at))
waiting_items(id,pair_cycle_id,waiting_side,priority_score,expires_at,state,created_at)
mutual_matches(id,pair_cycle_id UNIQUE,mutual_at,privacy_mode,status,created_at)
exposure_events(id,pair_cycle_id,candidate_id,vacancy_id,recipient_side,
                recipient_user_id,delivered_at,snapshot_hash,model_version,
                score_trace_hash,decision_card_id,source_policy,visibility_scope,
                idempotency_key UNIQUE)
score_snapshots(id,pair_cycle_id,model_version,feature_snapshot_hash,reason_codes JSONB,
                confidence_note,direction,price_snapshot JSONB,
                expected_surplus,created_at)
market_cells(id,occupation,region,seniority,employment_type,parent_cell_id)
market_prices(id,market_cell_id,side,price,update_window,gradient_sum_sq,model_version)
congestion_prices(id,actor_or_role_id,side,price,window,version)
allocation_replay(id,trigger_event_id,input_state_hash,proposal_hash,execution_hash,
                  model_version,config_version,time,side_effect_count)
```
**Important:** a `soft_shortlist_proposal` is not an active `decision_card` and must not create user-facing exposure; stored alternatives are internal planner outputs only.

## PACT authorizations and evidence
```
pact_policy_versions(id,org_id,policy_key,version_number,terms_hash,scope_kind,
                     allowed_vacancy_ids JSONB,policy_text,requirements_hash,
                     authorized_decision_stage ENUM[SCREENING,INTERVIEW,CONDITIONAL_OFFER],
                     valid_from,valid_until,status)
pact_policy_authorizations(id,policy_version_id,signatory_user_id,
                           authenticated_actor_role_snapshot,scope_hash,
                           approved_at,revoked_at,revocation_reason,
                           request_id,idempotency_key UNIQUE)
evidence_claims(id,candidate_id,claim_type,statement_hash,private_object_ref,
                verification_method,issuer_id,verifier_actor_id,verified_at,
                expires_at,revoked_at,review_status ENUM[PENDING,VERIFIED,FAILED,REVOKED],
                last_verified_role_policy_version NULL,version)
evidence_access_grants(id,claim_id,candidate_id,org_id,vacancy_id,role_version,
                       grant_kind ENUM[DISCLOSE_SUMMARY,DISCLOSE_DOCUMENT],
                       granted_at,expires_at,revoked_at,consent_text_hash,version)
candidate_term_consents(id,candidate_id,vacancy_id,role_version,terms_hash,
                        acknowledgment_scope ENUM[PRELIMINARY_INTEREST,CONDITIONAL_TERMS],
                        accepted_at,revoked_at,expires_at,version)
readiness_proofs(id,candidate_id,vacancy_id,role_version,policy_authorization_id,
                 terms_hash,evidence_claim_hash,consent_hash,issued_at,expires_at,
                 state ENUM[READY,INVALIDATED,EXPIRED],proof_digest,
                 invalidated_reason NULL,model_version NULL)
policy_clarification_requests(id,org_id,vacancy_id,requirement_id,
                              proposed_text,reason_for_request,requested_by,
                              status ENUM[DRAFT,REQUESTED,APPROVED,DENIED,EXPIRED],
                              scope_exact_ids JSONB,role_versions JSONB,
                              responded_by NULL,response_at NULL,expires_at,version)
```
A policy cannot be generalized to another role without an explicit scope and version; a candidate grant expires/revokes independently of evidence validity.

## Portfolio, WITNESS and experimentation
```
shortlist_plans(id,vacancy_id,role_version,generated_at,expires_at,
                planner_policy,plan_mode ENUM[SHADOW,PILOT],
                scenario_model_version,model_risk_estimate NULL,
                robustness_level,certification_state ENUM[CANNOT_CERTIFY,RESEARCH_ONLY,VALIDATED],
                certification_reason,plan_state ENUM[PROPOSED,APPROVED,STALE,REJECTED,EXPIRED],
                state_hash,planner_runtime_ms)
shortlist_plan_members(id,plan_id,candidate_id,sequence_number,readiness_proof_id NULL,
                       candidate_consent_status,soft_reserve_state,attempted_at,
                       exposure_event_id NULL,UNIQUE(plan_id,candidate_id))
exclusive_reservations(id,candidate_id,vacancy_id,plan_id,consented_at,starts_at,expires_at,
                       status ENUM[ACTIVE,RELEASED,EXPIRED,COMMITTED],version,
                       CONSTRAINT active_one_reservation_per_candidate UNIQUE_PARTIAL(candidate_id WHERE status IN ('ACTIVE','COMMITTED')))
witness_plans(id,vacancy_id,state_hash,base_allocation_hash,
              prospective_gain_model,prospective_costs JSONB,status,generated_at)
witness_prerequisites(id,witness_plan_id,kind,exact_requirement_id NULL,
                      required_evidence_claim_id NULL,approval_scope JSONB,
                      must_follow_prerequisite_id NULL,status)
shadow_runs(id,baseline_event_id,market_snapshot_hash,baseline_proposal_hash,
            advanced_proposal_hash,diagnostic_metrics JSONB,shadow_errors JSONB,
            model_versions JSONB,started_at,finished_at,side_effect_count DEFAULT 0)
risk_model_versions(id,artifact_hash,training_cutoff,calibration_cutoff,
                    external_validation_status,risk_assumptions JSONB,
                    signed_approval_id,active_from,active_until)
risk_calibrations(id,model_version,cohort_key,deadline_definition,
                  sample_size,failure_count,lower_confidence_bound,upper_bound_nonhire,
                  detection_of_drift,approved_at,approved_by)
```
Global R99 can score candidates using model-only scenarios, but MUST NOT put a `VALIDATED` status without meeting separately audited external gates.

## Hiring funnel, messaging, scheduling
```
match_messages(id,mutual_match_id,sender_user_id,body_sanitized,
               attachment_ref NULL,created_at,edited_at NULL,deleted_at NULL,
               abuse_flag,version)
message_receipts(id,message_id,recipient_user_id,read_at)
interview_proposals(id,mutual_match_id,initiator_id,time_options_utc JSONB,
                    timezone_label,status,created_at)
interview_events(id,mutual_match_id,start_at,end_at,meeting_location,
                 participants JSONB,status,confirmed_by,created_at)
process_stage_events(id,pair_cycle_id,stage,actor_id,occurred_at,recorded_at,
                     notes_private,source_system,source_reference_hash,
                     verified_by NULL,idempotency_key UNIQUE)
employment_offers(id,pair_cycle_id,issued_by_user_id,issued_at,status,
                  salary_terms_cipher,terms_document_ref,start_date,expires_at,
                  candidate_ack_at NULL,withdrawn_at NULL,version)
verified_employment_starts(id,pair_cycle_id,started_at,reported_by,
                           corroboration_method,verified_by,
                           verified_at,source_reference_hash,disputed_at NULL,
                           verification_state,version)
```
This last table must be verified against independent evidence, not employer self-report alone if reporting 99.9% publicly. Candidates must have a contest/correction path.

## Platform operations, analytics, privacy, billing
```
outbox_events(id,aggregate_type,aggregate_id,event_type,event_payload_minimized,
              event_version,idempotency_key,created_at,dispatched_at NULL,
              delivery_attempts,dead_letter_at NULL)
inbox_consumptions(id,consumer_name,event_id,processed_at,UNIQUE(consumer_name,event_id))
job_failures(id,job_key,worker_name,payload_hash,error_type,attempts,created_at)
idempotency_records(id,actor_id,route,client_key,request_hash,response_json,
                    status,created_at,expires_at,UNIQUE(actor_id,route,client_key))
audit_events(id,actor_type,actor_id,tenant_scope,action,entity_type,entity_id,
             before_hash,after_hash,request_id,source_ip_hmac,event_time,
             integrity_hash,correlation_id)
notification_outbox(id,recipient_user_id,type,template_key,referenced_entity_id,
                    scheduled_at,sent_at,status,delivery_provider_id)
notification_preferences(id,user_id,channel,event_type,opt_in,quiet_hours JSONB)
abuse_reports(id,reporter_user_id,reported_entity_type,reported_entity_id,
              reason,description,status,reviewer_id,created_at)
privacy_requests(id,user_id,request_type ENUM[EXPORT,DELETE,RECTIFY],requested_at,
                 verified_at,completed_at,status,reason,retention_exemptions JSONB)
organization_plans(id,org_id,plan_id,active_role_capacity,status)
billing_subscriptions(id,org_id,provider_customer_id,provider_subscription_id,status)
product_events(id,user_id_hash,org_id_hash,event_name,aggregation_tags JSONB,created_at)
prospective_pilot_enrollments(id,org_id,vacancy_id,enrolled_at,study_cohort,
                              policy_arm,deadline_at,completion_state,
                              exposed_candidates_count,verified_start_id NULL,
                              eligibility_rule_version,pre_registered_at)
compliance_audit.*             # separate database schema and access principal
```

## Essential indexes and database guards
```
CREATE INDEX pair_cycles(candidate_id,vacancy_id,created_at DESC);
CREATE INDEX decision_cards(recipient_user_id,status,expires_at) WHERE status='ACTIVE';
CREATE INDEX decision_cards(pair_cycle_id,status);
CREATE INDEX vacancies(org_id,vacancy_state,role_family,location_region);
CREATE INDEX shortlisted_members(plan_id,sequence_number);
CREATE INDEX outbox_events(created_at) WHERE dispatched_at IS NULL;
CREATE INDEX PACT role_version and scope indexes;
CREATE UNIQUE INDEX active_exclusive_candidate on exclusive_reservations(candidate_id)
  WHERE status IN ('ACTIVE','COMMITTED');
CREATE UNIQUE INDEX active-cycle-per-pair on pair_cycles(candidate_id,vacancy_id)
  WHERE closed_at IS NULL;
CREATE UNIQUE INDEX provider_issuer_subject on users(oidc_issuer,oidc_subject);
```
Do **not** rely on a `CHECK (count(active_cards)<=10)` (a row check can't express that). Enforce with candidate-scoped and vacancy-scoped row/advisory locks plus a count in the same transaction, backed by concurrent tests. Do not use a global SERIALIZABLE transaction around heavy optimizer computation.

## Migration order and rollback
1. Users/orgs/members/RBAC.
2. Candidate profiles/preferences/skills, vacancies/requirements.
3. Pair cycles/active decisions/waiting/exposures and outbox.
4. Mutual matches/messages/interviews/offers/verified starts.
5. PACT versioned authorizations/evidence/consents/readiness.
6. Shadow plans, scenario-risk research tables and analytics.
7. Billing, consent records, export/deletion and audits.

Add migrations then backfill in small chunks, integrity-check, then enable constraints. `down` migration only for schemas not carrying production data; data-bearing migrations need a documented archival/roll-forward recovery strategy. Seed demo only in non-production.
