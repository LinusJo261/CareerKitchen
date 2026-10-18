"""Human-confirmed profile changes, separate from AI-generated suggestions."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.matching.reciprocal import normalize_skill
from app.schemas.core import CandidateInput, CandidateOut, Input
from app.schemas.responses import SkillOut


class ConfirmedOnboardingSkill(Input):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w .+#/-]+$")
    level: int = Field(ge=1, le=5, strict=True)

    @field_validator("name")
    @classmethod
    def canonical_name(cls, value: str) -> str:
        return normalize_skill(value)


class OnboardingConfirmationIn(Input):
    profile: CandidateInput
    skills: list[ConfirmedOnboardingSkill] = Field(max_length=8)
    skills_confirmed: Literal[True]

    @field_validator("skills_confirmed", mode="before")
    @classmethod
    def explicit_skill_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit confirmation of the self-reported skill levels is required")
        return value

    @field_validator("profile", mode="before")
    @classmethod
    def explicit_profile_confirmation(cls, value: object) -> object:
        if isinstance(value, dict) and any(
            value.get(name) is not True
            for name in ("terms_accepted", "privacy_accepted", "profile_confirmed")
        ):
            raise ValueError("Confirm terms, privacy and the reviewed profile explicitly")
        return value

    @field_validator("skills")
    @classmethod
    def distinct_skills(cls, values: list[ConfirmedOnboardingSkill]) -> list[ConfirmedOnboardingSkill]:
        if len({skill.name for skill in values}) != len(values):
            raise ValueError("Confirm each canonical skill once")
        return values

    @model_validator(mode="after")
    def explicit_onsite_locations(self) -> "OnboardingConfirmationIn":
        if (
            any(mode in {"ONSITE", "HYBRID"} for mode in self.profile.work_modes)
            and not self.profile.locations
        ):
            raise ValueError("Choose acceptable locations for onsite or hybrid work")
        return self


class OnboardingConfirmationOut(BaseModel):
    candidate: CandidateOut
    skills: list[SkillOut]
    version: int
