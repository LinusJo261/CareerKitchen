"""Strict PACT inputs: actual authority and verification are checked in the database."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VersionRequest(Input):
    expected_version: int = Field(ge=1)


class RoleTerms(VersionRequest):
    vacancy_id: UUID
    terms_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreatePolicy(Input):
    roles: list[RoleTerms] = Field(min_length=1, max_length=20)
    policy_text: str = Field(min_length=10, max_length=10000)
    stage: Literal["SCREENING", "INTERVIEW", "CONDITIONAL_OFFER"]
    expires_at: AwareDatetime

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, roles: list[RoleTerms]) -> list[RoleTerms]:
        if len({r.vacancy_id for r in roles}) != len(roles):
            raise ValueError("Each exact vacancy can appear once")
        return roles


class AuthorizePolicy(VersionRequest):
    scope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    affirm_human_authority: Literal[True]


class Revoke(VersionRequest):
    reason: str = Field(default="REVOKED_BY_OWNER", min_length=1, max_length=500)


class CreateClaim(VersionRequest):
    claim_type: Literal["SKILL", "PROJECT", "EMPLOYMENT", "EDUCATION", "LICENSE", "WORK_AUTHORIZATION"]
    requirement_keys: list[str] = Field(min_length=1, max_length=20)
    statement: str = Field(min_length=10, max_length=5000)
    job_related_purpose: str = Field(min_length=10, max_length=500)

    @field_validator("requirement_keys")
    @classmethod
    def keys(cls, keys: list[str]) -> list[str]:
        if any(not key or len(key) > 100 for key in keys):
            raise ValueError("Requirement keys must contain 1..100 characters")
        return sorted(set(keys))


class VerifyClaim(VersionRequest):
    decision: Literal["VERIFIED", "FAILED"]
    method: Literal["ISSUER_CONTACT", "SIGNED_CREDENTIAL", "INDEPENDENT_DOCUMENT_REVIEW"]
    issuer: str = Field(min_length=3, max_length=200)
    source_reference: str = Field(min_length=10, max_length=1000)
    expires_at: AwareDatetime
    affirm_independent_check: Literal[True]


class ConsentTerms(RoleTerms):
    candidate_expected_version: int = Field(ge=1)
    scope: Literal["PRELIMINARY_INTEREST", "CONDITIONAL_TERMS"]
    expires_at: AwareDatetime
    checkbox_confirmed: Literal[True]


class ConsentEvidence(RoleTerms):
    claim_id: UUID
    claim_expected_version: int = Field(ge=1)
    org_id: UUID
    kind: Literal["DISCLOSE_SUMMARY", "DISCLOSE_DOCUMENT"]
    consent_text: str = Field(min_length=10, max_length=2000)
    expires_at: AwareDatetime
    checkbox_confirmed: Literal[True]


class CheckReadiness(RoleTerms):
    candidate_id: UUID
    candidate_expected_version: int = Field(ge=1)


class CreateClarification(RoleTerms):
    requirement_id: UUID
    requirement_expected_version: int = Field(ge=1)
    proposed_kind: Literal["PREFERENCE"] = "PREFERENCE"
    proposed_text: str = Field(min_length=10, max_length=2000)
    reason: str = Field(min_length=10, max_length=1000)
    expires_at: AwareDatetime


class RespondClarification(VersionRequest):
    vacancy_id: UUID
    role_version: int = Field(ge=1)
    requirement_id: UUID
    approved: bool
    affirm_human_authority: Literal[True]


class Reserve(RoleTerms):
    candidate_expected_version: int = Field(ge=1)
    expires_at: AwareDatetime
    consent_text: str = Field(min_length=10, max_length=2000)
    checkbox_confirmed: Literal[True]
