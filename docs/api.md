# REST API contract

The authoritative contract is [openapi.json](openapi.json), exported from the
running FastAPI route and Pydantic definitions. `/docs`, `/redoc`, and
`/openapi.json` expose the same contract when the API runs. TypeScript types are
generated from it rather than maintained as a second hand-written interface.

## Requests and responses

- Base paths begin with `/v1`. Identifiers are UUIDs; timestamps are aware RFC3339
  values in UTC. Monetary response values are exact decimal strings with explicit
  currency and compensation period; never compare annual and hourly pay directly.
- Every business route requires `Authorization: Bearer <Supabase access token>`.
  Health is public. Hosted readiness uses a separate private readiness credential.
- Every POST/PUT/PATCH/DELETE requires `Idempotency-Key` with 8–128 characters from
  `A-Za-z0-9_.:-`. Reuse the key only for an exact retry by the same actor on the
  same method/path. A changed payload or If-Match value with the same key returns
  409. Successful replies are persisted with the transaction and replayed with
  `Idempotency-Replayed: true`; the configured retention is seven days.
- Version-sensitive request bodies include their current `expected_version`, or
  `expected_cycle_version` for decision answers. Optional `If-Match: "<version>"`
  must agree with that body value; it does not replace a required schema field.
  Candidate profile creation uses version zero. Initial notification preferences
  use version one. Refresh and obtain renewed user confirmation after stale state.
- JSON responses contain `data` and `meta` with correlation ID/server time and an
  optional `resource_version` derived from the returned resource/cycle. Lists
  using cursor pagination also contain `page.has_more` and `page.next_cursor`.
  Cursor limit is 1–100; cursors are signed, actor/scoped, and expire after an hour.
  Decision inboxes contain `capacity.used` and `capacity.maximum` instead of an
  unbounded list. Binary downloads are attachment responses with no-store headers.
- Uploads use `multipart/form-data` and the documented `file` field. The backend
  validates bytes and size, stores encrypted private objects, and authorizes every
  download. PDF/DOCX acceptance requires a maintained scanner. Uploaded text is
  untrusted data, never executable instructions or independently verified evidence.

Errors use `{ "error": { "code", "message", "request_id", "fields"? } }`.
Validation fields contain safe `field` and `type` entries; private input values are
not echoed. The client preserves HTTP status and error code for UI handling.

| HTTP | Meaning | Frontend handling |
|---|---|---|
| 401 | Missing/invalid/revoked session | Reauthenticate through Supabase |
| 403 | Ownership, membership, authority, consent, or recent-auth check failed | Show permitted action; do not bypass using client roles |
| 404 | Resource absent or private object unavailable | Refresh the scoped resource |
| 409 | Capacity/state/idempotency/transaction conflict; experimental pilot disabled | Refresh and preserve user intent; no automatic transition retries |
| 412 | Stale expected version, terms, or conflicting If-Match | Reload current terms/version and reconfirm a changed action |
| 413/415 | Excessive size or unsupported upload type | Correct the upload |
| 422 | Schema, expiry, cursor, or idempotency-key validation failed | Display safe field/code feedback |
| 429 | Persisted account write-rate limit | Back off; do not loop automatically |
| 503 | Database/provider/storage/scanner/encryption unavailable | Preserve the pending operation for a later exact retry |

## Permission and lifecycle rules

Candidate routes operate on the authenticated owner's profile. Company routes
require active PostgreSQL membership; vacancy operations additionally check the
assigned vacancy ACL. Employer registration creates pending verification and
pending authority, never self-approved admin/signatory privileges. Verification,
support, operations, and research roles are provisioned through approved server
administration and cannot be supplied in a request body or JWT metadata.

Policy authorization requires an independently approved signatory, exact vacancy
IDs/versions/hashes, and recent authentication. Evidence verification requires an
independent verifier. Each disclosure consent identifies the exact claim,
recipient organization, vacancy, role version, permission kind, and expiry.
Revocation blocks fresh access and invalidates readiness immediately. A readiness
proof is revalidated on use and never means an offer or hire.

Interested decisions require the current cycle version and opaque one-use card
token. Mutual match/chat requires both valid Interested decisions in the same
cycle. Message writes use match version; interview confirmation uses proposal
version; stages and new offers use pair-cycle version; offer answers use offer
version. Requirements use vacancy version. PACT role inputs use vacancy version
and exact terms hash; their separate claim/candidate versions must also be current.
The generated request schemas expose each exact field.

Accepted offers and independently verified employment starts are separate records.
Research diagnostics remain read-only and `CANNOT_CERTIFY`; advanced live plan
approval is disabled. The shadow replay route accepts explicitly synthetic inputs
and cannot mutate live market state. No live calendar/payment/email success is
claimed when an integration is unconfigured.

## Endpoint inventory

Generated from the running OpenAPI contract; request/response names resolve under
`components.schemas` in `openapi.json`. JSON success responses are validated by
Pydantic before commit; an invalid response rolls back the transaction.

<!-- BEGIN GENERATED ENDPOINT INVENTORY -->

111 operations across 98 paths.

| Method | Path | Request schema | Success schema |
|---|---|---|---|
| GET | `/v1/admin/reports` | — | 200: Envelope_list_ReportDetailOut__ |
| POST | `/v1/admin/reports/{report_id}/resolve` | ModerationInput | 200: Envelope_ReportOut_ |
| POST | `/v1/admin/users/{user_id}/status` | AccountStatusInput | 200: Envelope_StatusOut_ |
| GET | `/v1/candidates/me` | — | 200: Envelope_CandidateOut_ |
| PUT | `/v1/candidates/me` | CandidateInput | 200: Envelope_CandidateOut_ |
| POST | `/v1/candidates/me/activate` | VersionInput | 200: Envelope_CandidateOut_ |
| PUT | `/v1/candidates/me/availability` | AvailabilityInput | 200: Envelope_CandidateOut_ |
| POST | `/v1/candidates/me/blocks` | BlockInput | 200: Envelope_StatusOut_ |
| DELETE | `/v1/candidates/me/blocks/{org_id}` | — | 200: Envelope_StatusOut_ |
| GET | `/v1/candidates/me/decisions` | — | 200: DecisionInbox |
| GET | `/v1/candidates/me/history` | — | 200: PageEnvelope_PairHistoryOut_ |
| GET | `/v1/candidates/me/matches` | — | 200: Envelope_list_MatchOut__ |
| GET | `/v1/candidates/me/pact/policies` | — | 200: Envelope_list_PolicyOut__ |
| POST | `/v1/candidates/me/pause` | VersionInput | 200: Envelope_CandidateOut_ |
| PUT | `/v1/candidates/me/preferences` | PreferencesInput | 200: Envelope_CandidateOut_ |
| GET | `/v1/candidates/me/resume` | — | 200: binary attachment |
| POST | `/v1/candidates/me/resume` | Body_upload_resume_v1_candidates_me_resume_post | 200: Envelope_ResumeOut_ |
| GET | `/v1/candidates/me/skills` | — | 200: Envelope_list_SkillOut__ |
| POST | `/v1/candidates/me/skills` | SkillInput | 200: Envelope_SkillOut_ |
| DELETE | `/v1/candidates/me/skills/{skill_id}` | VersionInput | 200: Envelope_StatusOut_ |
| PATCH | `/v1/candidates/me/skills/{skill_id}` | SkillEditInput | 200: Envelope_SkillOut_ |
| GET | `/v1/candidates/me/waiting` | — | 200: Envelope_list_WaitingOut__ |
| POST | `/v1/consents/evidence` | ConsentEvidence | 201: Envelope_EvidenceGrantOut_ |
| GET | `/v1/consents/me` | — | 200: Envelope_ConsentLedgerOut_ |
| POST | `/v1/consents/terms` | ConsentTerms | 201: Envelope_TermConsentOut_ |
| POST | `/v1/consents/{consent_id}/revoke` | Revoke | 200: Envelope_Union_EvidenceGrantOut__TermConsentOut__ |
| GET | `/v1/decisions/{decision_id}` | — | 200: Envelope_DecisionCardOut_ |
| POST | `/v1/decisions/{decision_id}/interested` | DecisionAnswerInput | 200: Envelope_DecisionAnswerOut_ |
| POST | `/v1/decisions/{decision_id}/pass` | DecisionAnswerInput | 200: Envelope_DecisionAnswerOut_ |
| POST | `/v1/evidence/claims` | CreateClaim | 201: Envelope_ClaimOut_ |
| GET | `/v1/evidence/claims/me` | — | 200: Envelope_list_ClaimOut__ |
| GET | `/v1/evidence/claims/{claim_id}` | — | 200: Envelope_ClaimOut_ |
| GET | `/v1/evidence/claims/{claim_id}/document` | — | 200: binary attachment |
| POST | `/v1/evidence/claims/{claim_id}/document` | Body_attach_document_v1_evidence_claims__claim_id__document_post | 201: Envelope_ClaimOut_ |
| POST | `/v1/evidence/claims/{claim_id}/revoke` | Revoke | 200: Envelope_ClaimOut_ |
| POST | `/v1/evidence/claims/{claim_id}/verify` | VerifyClaim | 200: Envelope_ClaimOut_ |
| GET | `/v1/health` | — | 200: Envelope_HealthOut_ |
| POST | `/v1/internal/decisions/issue` | IssueCardInput | 200: Envelope_IssuedDecisionOut_ |
| POST | `/v1/internal/reconcile` | — | 200: Envelope_ReconcileOut_ |
| POST | `/v1/internal/shadow/replay` | ReplayInput | 200: Envelope_ReplayOutput_ |
| GET | `/v1/internal/shadow/runs` | — | 200: Envelope_list_ShadowRunOut__ |
| GET | `/v1/internal/shadow/runs/{run_id}` | — | 200: Envelope_ShadowRunOut_ |
| GET | `/v1/matches/{match_id}` | — | 200: Envelope_MatchOut_ |
| POST | `/v1/matches/{match_id}/attachments` | Body_upload_attachment_v1_matches__match_id__attachments_post | 200: Envelope_AttachmentOut_ |
| GET | `/v1/matches/{match_id}/attachments/{attachment_id}` | — | 200: binary attachment |
| GET | `/v1/matches/{match_id}/interviews/proposals` | — | 200: Envelope_list_InterviewProposalOut__ |
| POST | `/v1/matches/{match_id}/interviews/proposals` | InterviewInput | 200: Envelope_InterviewProposalOut_ |
| POST | `/v1/matches/{match_id}/interviews/{proposal_id}/confirm` | InterviewConfirmInput | 200: Envelope_InterviewOut_ |
| GET | `/v1/matches/{match_id}/messages` | — | 200: PageEnvelope_MessageOut_ |
| POST | `/v1/matches/{match_id}/messages` | MessageInput | 200: Envelope_MessageOut_ |
| POST | `/v1/matches/{match_id}/offers` | OfferInput | 200: Envelope_OfferOut_ |
| POST | `/v1/matches/{match_id}/stages` | StageInput | 200: Envelope_PairStateOut_ |
| POST | `/v1/matches/{match_id}/starts/dispute` | VersionInput | 200: Envelope_StatusOut_ |
| POST | `/v1/matches/{match_id}/starts/report` | StartInput | 200: Envelope_StartOut_ |
| POST | `/v1/matches/{match_id}/starts/verify` | StartVerifyInput | 200: Envelope_StartOut_ |
| POST | `/v1/matches/{match_id}/withdraw` | VersionInput | 200: Envelope_PairStateOut_ |
| GET | `/v1/notifications` | — | 200: PageEnvelope_NotificationOut_ |
| GET | `/v1/notifications/preferences` | — | 200: Envelope_NotificationPreferencesOut_ |
| PUT | `/v1/notifications/preferences` | NotificationInput | 200: Envelope_NotificationPreferencesOut_ |
| POST | `/v1/notifications/{notification_id}/read` | VersionInput | 200: Envelope_NotificationReadOut_ |
| GET | `/v1/offers/{offer_id}` | — | 200: Envelope_OfferOut_ |
| POST | `/v1/offers/{offer_id}/accept` | VersionInput | 200: Envelope_OfferAnswerOut_ |
| POST | `/v1/offers/{offer_id}/decline` | VersionInput | 200: Envelope_OfferAnswerOut_ |
| GET | `/v1/organizations` | — | 200: Envelope_list_OrganizationOut__ |
| POST | `/v1/organizations` | OrganizationInput | 200: Envelope_OrganizationOut_ |
| POST | `/v1/organizations/invitations/accept` | InviteAcceptInput | 200: Envelope_MemberOut_ |
| GET | `/v1/organizations/{org_id}` | — | 200: Envelope_OrganizationOut_ |
| PATCH | `/v1/organizations/{org_id}` | OrganizationEditInput | 200: Envelope_OrganizationOut_ |
| GET | `/v1/organizations/{org_id}/billing` | — | 200: Envelope_BillingOut_ |
| GET | `/v1/organizations/{org_id}/members` | — | 200: Envelope_list_MemberOut__ |
| POST | `/v1/organizations/{org_id}/members/approve` | MemberGrantInput | 200: Envelope_MemberOut_ |
| POST | `/v1/organizations/{org_id}/members/invite` | InviteInput | 200: Envelope_InvitationOut_ |
| DELETE | `/v1/organizations/{org_id}/members/{member_id}` | VersionInput | 200: Envelope_StatusOut_ |
| PATCH | `/v1/organizations/{org_id}/members/{member_id}` | MemberUpdateInput | 200: Envelope_MemberOut_ |
| GET | `/v1/organizations/{org_id}/pact/policies` | — | 200: Envelope_list_PolicyOut__ |
| GET | `/v1/organizations/{org_id}/vacancies` | — | 200: Envelope_list_VacancyOut__ |
| POST | `/v1/organizations/{org_id}/verify` | VerificationInput | 200: Envelope_OrganizationOut_ |
| POST | `/v1/pact/clarifications` | CreateClarification | 201: Envelope_ClarificationOut_ |
| POST | `/v1/pact/clarifications/{clarification_id}/respond` | RespondClarification | 200: Envelope_ClarificationOut_ |
| POST | `/v1/pact/policies` | CreatePolicy | 201: Envelope_PolicyOut_ |
| GET | `/v1/pact/policies/{policy_id}` | — | 200: Envelope_PolicyOut_ |
| POST | `/v1/pact/policies/{policy_id}/authorize` | AuthorizePolicy | 200: Envelope_PolicyOut_ |
| POST | `/v1/pact/policies/{policy_id}/revoke` | Revoke | 200: Envelope_PolicyOut_ |
| POST | `/v1/pact/readiness/check` | CheckReadiness | 200: Envelope_ReadinessOut_ |
| GET | `/v1/pact/readiness/{proof_id}` | — | 200: Envelope_ReadinessOut_ |
| POST | `/v1/pact/reservations` | Reserve | 201: Envelope_ReservationOut_ |
| POST | `/v1/pact/reservations/{reservation_id}/release` | Revoke | 200: Envelope_ReservationOut_ |
| POST | `/v1/privacy/delete` | — | 202: Envelope_OperationOut_ |
| GET | `/v1/privacy/export` | — | 200: Envelope_ExportOut_ |
| POST | `/v1/privacy/export` | — | 202: Envelope_OperationOut_ |
| GET | `/v1/ready` | — | 200: Envelope_ReadyOut_ |
| POST | `/v1/reports` | ReportInput | 200: Envelope_ReportOut_ |
| PATCH | `/v1/requirements/{requirement_id}` | RequirementInput | 200: Envelope_ScopedVersionOut_ |
| POST | `/v1/sessions/logout` | — | 200: Envelope_StatusOut_ |
| GET | `/v1/sessions/me` | — | 200: Envelope_IdentityOut_ |
| POST | `/v1/vacancies` | VacancyInput | 200: Envelope_VacancyOut_ |
| GET | `/v1/vacancies/{vacancy_id}` | — | 200: Envelope_VacancyOut_ |
| PATCH | `/v1/vacancies/{vacancy_id}` | VacancyEditInput | 200: Envelope_VacancyOut_ |
| PUT | `/v1/vacancies/{vacancy_id}/acl` | ACLInput | 200: Envelope_ScopedVersionOut_ |
| POST | `/v1/vacancies/{vacancy_id}/activate` | VersionInput | 200: Envelope_VacancyOut_ |
| POST | `/v1/vacancies/{vacancy_id}/close` | VersionInput | 200: Envelope_VacancyOut_ |
| GET | `/v1/vacancies/{vacancy_id}/decisions` | — | 200: DecisionInbox |
| GET | `/v1/vacancies/{vacancy_id}/metrics` | — | 200: Envelope_MetricsOut_ |
| GET | `/v1/vacancies/{vacancy_id}/pact/clarifications` | — | 200: Envelope_list_ClarificationOut__ |
| POST | `/v1/vacancies/{vacancy_id}/pause` | VersionInput | 200: Envelope_VacancyOut_ |
| GET | `/v1/vacancies/{vacancy_id}/pipeline` | — | 200: Envelope_list_MatchOut__ |
| POST | `/v1/vacancies/{vacancy_id}/requirements` | RequirementInput | 200: Envelope_ScopedVersionOut_ |
| POST | `/v1/vacancies/{vacancy_id}/shortlist/approve` | VersionInput | disabled (409) |
| POST | `/v1/vacancies/{vacancy_id}/shortlist/replan` | VersionInput | 202: Envelope_OperationOut_ |
| GET | `/v1/vacancies/{vacancy_id}/shortlist/status` | — | 200: Envelope_ShortlistOut_ |
| GET | `/v1/vacancies/{vacancy_id}/waiting` | — | 200: Envelope_list_WaitingOut__ |
