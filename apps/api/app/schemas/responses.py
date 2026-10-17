"""Public response contracts. Fields intentionally exclude internal PII and storage keys."""

from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from app.schemas.core import CandidateOut

T = TypeVar("T")


class Meta(BaseModel):
    request_id: str | None = None
    server_time: datetime | None = None
    resource_version: int | None = None


class HealthOut(BaseModel):
    status: Literal["alive"]


class ReadyOut(BaseModel):
    status: Literal["ready"]
    queue: Literal["POSTGRES_OUTBOX"]


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta = Field(default_factory=Meta)


class Page(BaseModel):
    has_more: bool
    next_cursor: str | None


class PageEnvelope(Envelope[list[T]], Generic[T]):
    page: Page


class Capacity(BaseModel):
    used: int
    maximum: int


class StatusOut(BaseModel):
    status: str
    version: int | None = None
    notice: str | None = None


class MemberOut(BaseModel):
    id: UUID
    role: str
    version: int | None = None
    status: str | None = None
    org_id: UUID | None = None
    user_id: UUID | None = None


class IdentityOut(BaseModel):
    id: UUID
    email: str
    platform_roles: list[str]
    memberships: list[MemberOut]


class SkillOut(BaseModel):
    id: UUID
    name: str
    level: int
    verification_status: Literal["SELF_REPORTED"]
    skill_id: UUID | None = None
    version: int = 1


class ResumeOut(BaseModel):
    object_id: UUID
    size: int
    sha256: str
    parse_status: Literal["DRAFT_REQUIRES_CONFIRMATION", "MANUAL_ENTRY_REQUIRED"]
    suggested_summary: str
    candidate_version: int


class OrganizationOut(BaseModel):
    id: UUID
    version: int
    legal_name: str
    display_name: str
    domain: str
    verification_state: str
    active_role_capacity: int


class InvitationOut(BaseModel):
    id: UUID
    token: str
    expires_at: datetime
    delivery_status: Literal["MANUAL_DELIVERY_REQUIRED"]


class RequirementOut(BaseModel):
    id: UUID
    version: int
    key: str
    description: str
    kind: Literal["ESSENTIAL", "PREFERENCE", "AMBIGUOUS"]
    lawful_reason: str | None


class VacancyOut(BaseModel):
    id: UUID
    version: int
    org_id: UUID
    owner_user_id: UUID
    title: str
    description: str
    role_family: str
    employment_type: str
    work_mode: str
    location_region: str
    pay_min: Decimal
    pay_max: Decimal
    currency: str
    compensation_period: str
    openings_total: int
    openings_remaining: int
    cap: int
    state: str
    deadline_at: datetime | None
    start_from: datetime | None
    start_until: datetime | None
    terms_hash: str
    requirements: list[RequirementOut]


class ScopedVersionOut(BaseModel):
    id: UUID
    vacancy_version: int
    version: int | None = None


class CandidateSummary(BaseModel):
    id: UUID
    headline: str
    summary: str
    region: str
    compensation_aligned: bool
    skills: list[str]
    experiences: list[dict[str, JsonValue]] = Field(default_factory=list)
    education: list[dict[str, JsonValue]] = Field(default_factory=list)


class DecisionCardOut(BaseModel):
    id: UUID
    version: int
    pair_cycle_id: UUID
    cycle_version: int
    pair_state: str
    side: Literal["CANDIDATE", "EMPLOYER"]
    status: str
    expires_at: datetime
    decision_token: str | None
    vacancy: VacancyOut
    reason_codes: list[str]
    other_side_interested: bool
    candidate: CandidateSummary | None = None


class DecisionInbox(Envelope[list[DecisionCardOut]]):
    capacity: Capacity


class WaitingOut(BaseModel):
    pair_cycle_id: UUID
    state: str
    version: int
    vacancy_id: UUID | None = None


class PairHistoryOut(BaseModel):
    id: UUID
    state: str
    vacancy_id: UUID
    version: int
    closed_at: datetime | None


class CandidateName(BaseModel):
    id: UUID
    headline: str


class VacancyName(BaseModel):
    id: UUID
    title: str
    org_id: UUID


class StageEventOut(BaseModel):
    id: UUID
    stage: str
    occurred_at: datetime


class OfferOut(BaseModel):
    id: UUID
    version: int | None = None
    status: str
    terms: str
    expires_at: datetime
    start_at: datetime
    cycle_version: int | None = None


class InterviewOut(BaseModel):
    id: UUID
    start_at: datetime
    end_at: datetime
    status: str | None = None


class MatchOut(BaseModel):
    id: UUID
    version: int
    pair_cycle_id: UUID
    cycle_version: int
    state: str
    status: str
    candidate: CandidateName
    vacancy: VacancyName
    timeline: list[StageEventOut]
    offers: list[OfferOut]
    interviews: list[InterviewOut]


class MetricsOut(BaseModel):
    vacancy_id: UUID
    n_delivered: int
    candidate_attempts: int
    active_employer_decisions: int
    states: dict[str, int]
    filled_openings: int
    certification_state: Literal["CANNOT_CERTIFY"]


class IssuedDecisionOut(BaseModel):
    decision_id: UUID
    pair_cycle_id: UUID


class ReconcileItem(BaseModel):
    decision_id: UUID
    candidate_id: UUID
    vacancy_id: UUID
    side: Literal["CANDIDATE", "EMPLOYER"]


class ReconcileOut(BaseModel):
    issued: list[ReconcileItem]


class AttachmentOut(BaseModel):
    id: UUID
    size: int
    sha256: str


class DecisionAnswerOut(BaseModel):
    pair_cycle_id: UUID
    pair_state: str
    card_status: str
    cycle_version: int
    match_id: UUID | None
    next_action: Literal["OPEN_MATCH", "WAITING", "NONE"]


class MessageOut(BaseModel):
    id: UUID
    body: str
    sender_user_id: UUID
    created_at: datetime
    match_version: int | None = None
    attachment_id: UUID | None = None


class InterviewSlotOut(BaseModel):
    start_at: datetime
    end_at: datetime


class InterviewProposalOut(BaseModel):
    id: UUID
    version: int
    slots: list[InterviewSlotOut]
    timezone_label: str
    status: str
    initiator_id: UUID | None = None


class PairStateOut(BaseModel):
    state: str
    cycle_version: int


class OfferAnswerOut(BaseModel):
    id: UUID
    version: int
    status: str
    pair_state: str
    notice: str


class StartOut(BaseModel):
    id: UUID
    verification_state: str
    version: int | None = None
    pair_state: str | None = None


class NotificationOut(BaseModel):
    id: UUID
    version: int
    kind: str
    entity_id: UUID
    created_at: datetime
    read_at: datetime | None


class NotificationReadOut(BaseModel):
    id: UUID
    version: int
    read_at: datetime


class NotificationPreferencesOut(BaseModel):
    version: int
    email_opt_in: bool
    in_app_opt_in: bool
    quiet_hours: dict[str, str] = Field(default_factory=dict)


class OperationOut(BaseModel):
    operation_id: UUID
    status: str
    notice: str | None = None
    mode: Literal["SHADOW"] | None = None


class ExportOut(BaseModel):
    operation_id: UUID
    status: str
    export: dict[str, JsonValue] | None


class ReportOut(BaseModel):
    id: UUID
    status: str
    version: int | None = None


class ReportDetailOut(ReportOut):
    reason: str
    description: str
    entity_type: str
    entity_id: UUID


class ShadowRunOut(BaseModel):
    id: UUID
    snapshot_hash: str
    baseline_hash: str
    proposal_hash: str
    diagnostics: dict[str, JsonValue]
    side_effect_count: Literal[0]


class ShortlistOut(BaseModel):
    vacancy_id: UUID
    mode: Literal["BASELINE", "SHADOW"]
    delivered_candidate_ids: list[UUID]
    certification_state: Literal["CANNOT_CERTIFY"]
    reason: str


class BillingOut(BaseModel):
    active_role_capacity: int
    payment_provider_status: Literal["NOT_CONFIGURED"]
    ranking_influence: Literal["NONE"]


class RoleScopeOut(BaseModel):
    version: int
    terms_hash: str
    requirements_hash: str


class PolicyOut(BaseModel):
    id: UUID
    version: int
    org_id: UUID
    policy_text: str
    stage: Literal["SCREENING", "INTERVIEW", "CONDITIONAL_OFFER"]
    scope: dict[str, RoleScopeOut]
    scope_hash: str
    state: str
    expires_at: datetime
    authorization_id: UUID | None = None


class ClaimOut(BaseModel):
    id: UUID
    version: int
    candidate_id: UUID
    claim_type: str
    requirement_keys: list[str]
    statement_hash: str
    status: str
    verified_at: datetime | None
    expires_at: datetime | None
    has_document: bool


class EvidenceGrantOut(BaseModel):
    id: UUID
    version: int
    claim_id: UUID
    vacancy_id: UUID
    org_id: UUID
    role_version: int
    kind: Literal["DISCLOSE_SUMMARY", "DISCLOSE_DOCUMENT"]
    expires_at: datetime
    revoked_at: datetime | None


class TermConsentOut(BaseModel):
    id: UUID
    version: int
    vacancy_id: UUID
    role_version: int
    terms_hash: str
    scope: Literal["PRELIMINARY_INTEREST", "CONDITIONAL_TERMS"]
    expires_at: datetime
    revoked_at: datetime | None


class ConsentLedgerOut(BaseModel):
    terms: list[TermConsentOut]
    evidence: list[EvidenceGrantOut]


class ReadinessOut(BaseModel):
    status: Literal["READY", "NOT_READY", "STALE"]
    proof_id: UUID | None
    version: int | None
    expires_at: datetime | None
    public_reason_codes: list[str]
    notice: str
    certification_state: Literal["CANNOT_CERTIFY"]


class ClarificationOut(BaseModel):
    id: UUID
    version: int
    vacancy_id: UUID
    requirement_id: UUID
    role_version: int
    proposed_kind: Literal["PREFERENCE"]
    proposed_text: str
    status: str
    expires_at: datetime


class ReservationOut(BaseModel):
    id: UUID
    version: int
    candidate_id: UUID
    vacancy_id: UUID
    role_version: int
    status: str
    expires_at: datetime


# Consumed by router decorators; FastAPI validates every successful JSON response.
RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "me": Envelope[IdentityOut],
    "logout": Envelope[StatusOut],
    "get_candidate": Envelope[CandidateOut],
    "put_candidate": Envelope[CandidateOut],
    "put_preferences": Envelope[CandidateOut],
    "activate_candidate": Envelope[CandidateOut],
    "pause_candidate": Envelope[CandidateOut],
    "add_skill": Envelope[SkillOut],
    "list_skills": Envelope[list[SkillOut]],
    "upload_resume": Envelope[ResumeOut],
    "block": Envelope[StatusOut],
    "unblock": Envelope[StatusOut],
    "candidate_decisions": DecisionInbox,
    "candidate_waiting": Envelope[list[WaitingOut]],
    "candidate_matches": Envelope[list[MatchOut]],
    "candidate_history": PageEnvelope[PairHistoryOut],
    "create_org": Envelope[OrganizationOut],
    "list_orgs": Envelope[list[OrganizationOut]],
    "get_org": Envelope[OrganizationOut],
    "verify_org": Envelope[OrganizationOut],
    "approve_member": Envelope[MemberOut],
    "list_members": Envelope[list[MemberOut]],
    "invite": Envelope[InvitationOut],
    "accept_invitation": Envelope[MemberOut],
    "revoke_member": Envelope[StatusOut],
    "create_vacancy": Envelope[VacancyOut],
    "list_vacancies": Envelope[list[VacancyOut]],
    "get_vacancy": Envelope[VacancyOut],
    "edit_vacancy": Envelope[VacancyOut],
    "activate_vacancy": Envelope[VacancyOut],
    "pause_vacancy": Envelope[VacancyOut],
    "close_vacancy": Envelope[VacancyOut],
    "set_acl": Envelope[ScopedVersionOut],
    "add_requirement": Envelope[ScopedVersionOut],
    "edit_requirement": Envelope[ScopedVersionOut],
    "vacancy_decisions": DecisionInbox,
    "vacancy_waiting": Envelope[list[WaitingOut]],
    "pipeline": Envelope[list[MatchOut]],
    "metrics": Envelope[MetricsOut],
    "issue_card": Envelope[IssuedDecisionOut],
    "reconcile": Envelope[ReconcileOut],
    "decision": Envelope[DecisionCardOut],
    "interested": Envelope[DecisionAnswerOut],
    "pass_decision": Envelope[DecisionAnswerOut],
    "match": Envelope[MatchOut],
    "messages": PageEnvelope[MessageOut],
    "send_message": Envelope[MessageOut],
    "propose_interview": Envelope[InterviewProposalOut],
    "interview_proposals": Envelope[list[InterviewProposalOut]],
    "confirm_interview": Envelope[InterviewOut],
    "stage": Envelope[PairStateOut],
    "withdraw": Envelope[PairStateOut],
    "offer": Envelope[OfferOut],
    "get_offer": Envelope[OfferOut],
    "accept_offer": Envelope[OfferAnswerOut],
    "decline_offer": Envelope[OfferAnswerOut],
    "report_start": Envelope[StartOut],
    "verify_start": Envelope[StartOut],
    "dispute_start": Envelope[StatusOut],
    "notifications": PageEnvelope[NotificationOut],
    "read_notification": Envelope[NotificationReadOut],
    "notification_preferences": Envelope[NotificationPreferencesOut],
    "request_export": Envelope[OperationOut],
    "get_export": Envelope[ExportOut],
    "request_deletion": Envelope[OperationOut],
    "report": Envelope[ReportOut],
    "reports": Envelope[list[ReportDetailOut]],
    "resolve_report": Envelope[ReportOut],
    "shadow_runs": Envelope[list[ShadowRunOut]],
    "shortlist_status": Envelope[ShortlistOut],
    "replan": Envelope[OperationOut],
    "billing": Envelope[BillingOut],
    "create_policy": Envelope[PolicyOut],
    "read_policy": Envelope[PolicyOut],
    "authorize_policy": Envelope[PolicyOut],
    "revoke_policy": Envelope[PolicyOut],
    "create_clarification": Envelope[ClarificationOut],
    "respond_clarification": Envelope[ClarificationOut],
    "create_claim": Envelope[ClaimOut],
    "list_claims": Envelope[list[ClaimOut]],
    "disclosed_claim": Envelope[ClaimOut],
    "attach_document": Envelope[ClaimOut],
    "verify_claim": Envelope[ClaimOut],
    "revoke_claim": Envelope[ClaimOut],
    "consent_terms": Envelope[TermConsentOut],
    "consent_evidence": Envelope[EvidenceGrantOut],
    "consent_ledger": Envelope[ConsentLedgerOut],
    "revoke_consent": Envelope[EvidenceGrantOut | TermConsentOut],
    "check_readiness": Envelope[ReadinessOut],
    "live_readiness": Envelope[ReadinessOut],
    "reserve": Envelope[ReservationOut],
    "release_reservation": Envelope[ReservationOut],
}
