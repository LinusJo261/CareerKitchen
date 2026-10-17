from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Cap = Annotated[int, Field(ge=1, le=10)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
EmploymentType = Literal["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY"]
WorkMode = Literal["REMOTE", "HYBRID", "ONSITE"]
PayPeriod = Literal["ANNUAL", "MONTHLY", "HOURLY"]
Role = Literal["RECRUITER", "HIRING_MANAGER", "ORG_ADMIN", "AUTHORIZED_SIGNATORY"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VersionInput(Input):
    expected_version: int = Field(ge=1)


class ExperienceInput(Input):
    title: str = Field(min_length=2, max_length=180)
    organization_label: str = Field(min_length=1, max_length=180)
    details: str = Field(default="", max_length=3000)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    disclose_organization: bool = False

    @model_validator(mode="after")
    def dates(self):
        from datetime import date

        start = date.fromisoformat(self.start_date)
        if self.end_date and date.fromisoformat(self.end_date) < start:
            raise ValueError("Experience end must follow start")
        return self


class EducationInput(Input):
    qualification: str = Field(min_length=2, max_length=180)
    institution: str = Field(min_length=2, max_length=180)
    details: str = Field(default="", max_length=2000)


class CandidateInput(Input):
    expected_version: int = Field(ge=0)
    headline: str = Field(min_length=3, max_length=180)
    summary: str = Field(default="", max_length=10000)
    region: str = Field(min_length=2, max_length=160)
    role_families: list[str] = Field(min_length=1, max_length=20)
    employment_types: list[EmploymentType] = Field(min_length=1, max_length=5)
    work_modes: list[WorkMode] = Field(min_length=1, max_length=3)
    locations: list[str] = Field(default_factory=list, max_length=50)
    compensation_floor: Money | None = None
    currency: str = Field(pattern="^[A-Z]{3}$")
    compensation_period: PayPeriod = "ANNUAL"
    experiences: list[ExperienceInput] = Field(default_factory=list, max_length=50)
    education: list[EducationInput] = Field(default_factory=list, max_length=30)
    cap: Cap = 10
    available_from: AwareDatetime | None = None
    available_until: AwareDatetime | None = None
    terms_accepted: Literal[True]
    privacy_accepted: Literal[True]
    profile_confirmed: Literal[True]

    @model_validator(mode="after")
    def valid_window(self):
        if self.available_from and self.available_until and self.available_from >= self.available_until:
            raise ValueError("Availability end must follow its start")
        if any(not x.strip() or len(x) > 120 for x in self.role_families + self.locations):
            raise ValueError("Role families and locations must be nonempty bounded labels")
        return self


class PreferencesInput(Input):
    expected_version: int = Field(ge=1)
    cap: Cap
    compensation_floor: Money | None = None
    currency: str = Field(pattern="^[A-Z]{3}$")
    compensation_period: PayPeriod = "ANNUAL"
    employment_types: list[EmploymentType] = Field(min_length=1, max_length=5)
    work_modes: list[WorkMode] = Field(min_length=1, max_length=3)
    locations: list[str] = Field(max_length=50)


class SkillInput(Input):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w .+#/-]+$")
    level: int = Field(ge=1, le=5)


class SkillEditInput(VersionInput):
    level: int = Field(ge=1, le=5)


class AvailabilityInput(VersionInput):
    available_from: AwareDatetime
    available_until: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.available_from >= self.available_until:
            raise ValueError("Availability end must follow start")
        return self


class MemberUpdateInput(VersionInput):
    role: Literal["RECRUITER", "HIRING_MANAGER"]


class AccountStatusInput(VersionInput):
    status: Literal["ACTIVE", "SUSPENDED"]
    reason: str = Field(min_length=10, max_length=1000)


class OrganizationInput(Input):
    legal_name: str = Field(min_length=3, max_length=200)
    display_name: str = Field(min_length=2, max_length=120)
    domain: str = Field(pattern=r"^[a-z0-9.-]+\.[a-z]{2,}$", max_length=200)


class OrganizationEditInput(VersionInput):
    display_name: str = Field(min_length=2, max_length=120)


class VerificationInput(VersionInput):
    source_reference: str = Field(min_length=10, max_length=1000)
    independent_check_completed: Literal[True]


class MemberGrantInput(Input):
    user_id: UUID
    role: Role
    source_reference: str = Field(min_length=10, max_length=1000)
    independent_authority_check_completed: Literal[True]
    expires_at: AwareDatetime | None = None


class InviteInput(Input):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    role: Literal["RECRUITER", "HIRING_MANAGER"]


class InviteAcceptInput(Input):
    token: str = Field(min_length=20, max_length=200)


class ACLInput(VersionInput):
    user_id: UUID
    can_review: bool = True
    can_edit: bool = False
    can_approve_policy: bool = False


class VacancyInput(Input):
    org_id: UUID
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=30, max_length=30000)
    role_family: str = Field(min_length=2, max_length=120)
    employment_type: EmploymentType
    work_mode: WorkMode
    location_region: str = Field(default="", max_length=160)
    pay_min: Money
    pay_max: Money
    currency: str = Field(pattern="^[A-Z]{3}$")
    compensation_period: PayPeriod = "ANNUAL"
    openings_total: int = Field(default=1, ge=1, le=100)
    cap: Cap = 10
    deadline_at: AwareDatetime | None = None
    start_from: AwareDatetime | None = None
    start_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_terms(self):
        if self.pay_min > self.pay_max:
            raise ValueError("pay_min must not exceed pay_max")
        if self.work_mode != "REMOTE" and not self.location_region:
            raise ValueError("Onsite and hybrid roles require a location")
        if self.start_from and self.start_until and self.start_from >= self.start_until:
            raise ValueError("Start window must be ordered")
        return self


class VacancyEditInput(VacancyInput):
    expected_version: int = Field(ge=1)


class RequirementInput(VersionInput):
    key: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_.+-]+$")
    description: str = Field(min_length=5, max_length=2000)
    kind: Literal["ESSENTIAL", "PREFERENCE", "AMBIGUOUS"]
    lawful_reason: str | None = Field(default=None, max_length=2000)
    human_reviewed: Literal[True]

    @model_validator(mode="after")
    def essential_reason(self):
        if self.kind == "ESSENTIAL" and (not self.lawful_reason or len(self.lawful_reason) < 10):
            raise ValueError("Essential requirements need a documented job-related reason")
        return self


class BlockInput(Input):
    org_id: UUID


class IssueCardInput(Input):
    candidate_id: UUID
    vacancy_id: UUID
    role_version: int = Field(ge=1)
    first_mover: Literal["CANDIDATE", "EMPLOYER"]
    human_review_reason: str = Field(min_length=10, max_length=1000)


class DecisionAnswerInput(Input):
    expected_cycle_version: int = Field(ge=1)
    decision_token: str = Field(min_length=20, max_length=200)
    reason_code: Literal["COMPENSATION", "LOCATION", "ROLE", "TIMING", "OTHER"] | None = None


class MessageInput(VersionInput):
    body: str = Field(min_length=1, max_length=5000)
    attachment_id: UUID | None = None


class InterviewSlot(Input):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def positive_duration(self):
        seconds = (self.end_at - self.start_at).total_seconds()
        if not 900 <= seconds <= 14400:
            raise ValueError("Interview duration must be 15 minutes to 4 hours")
        return self


class InterviewInput(VersionInput):
    slots: list[InterviewSlot] = Field(min_length=2, max_length=5)
    timezone_label: str = Field(max_length=80)

    @field_validator("timezone_label")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value


class InterviewConfirmInput(VersionInput):
    slot_index: int = Field(ge=0, le=4)


class StageInput(VersionInput):
    stage: Literal["INTERVIEWING", "CLOSED_REJECTED"]
    source_reference: str = Field(min_length=5, max_length=1000)


class OfferInput(VersionInput):
    terms: str = Field(min_length=30, max_length=30000)
    expires_at: AwareDatetime
    start_at: AwareDatetime
    affirm_human_authority: Literal[True]


class StartInput(VersionInput):
    started_at: AwareDatetime
    source_reference: str = Field(min_length=10, max_length=1000)


class StartVerifyInput(VersionInput):
    corroboration_source: str = Field(min_length=10, max_length=1000)
    independently_checked: Literal[True]


class ReportInput(Input):
    entity_type: Literal["VACANCY", "MATCH", "MESSAGE", "OFFER"]
    entity_id: UUID
    reason: Literal[
        "FAKE_JOB",
        "SCAM",
        "HARASSMENT",
        "DISCRIMINATION",
        "MISLEADING_TERMS",
        "IMPERSONATION",
        "SPAM",
        "ACCOMMODATION",
        "CORRECTION",
        "OTHER",
    ]
    description: str = Field(min_length=10, max_length=5000)


class NotificationInput(VersionInput):
    email_opt_in: bool
    in_app_opt_in: bool
    quiet_hours: dict[str, str] = Field(default_factory=dict, max_length=3)


class ModerationInput(VersionInput):
    status: Literal["TRIAGED", "INVESTIGATING", "ACTIONED", "NO_ACTION", "CLOSED"]
    resolution: str = Field(min_length=10, max_length=1000)


class CandidateOut(BaseModel):
    id: UUID
    version: int
    headline: str
    summary: str
    region: str
    state: str
    cap: int
    role_families: list[str]
    employment_types: list[str]
    work_modes: list[str]
    locations: list[str]
    currency: str
    compensation_floor: str | None
    compensation_period: str
    experiences: list[ExperienceInput]
    education: list[EducationInput]
    terms_accepted: bool
    privacy_accepted: bool
    confirmed_at: datetime | None
    available_from: datetime | None
    available_until: datetime | None


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)


class ValidationField(BaseModel):
    field: str
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    fields: list[ValidationField] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
