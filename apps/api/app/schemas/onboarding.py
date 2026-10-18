"""Explicitly consented, bounded candidate drafts; no consent or authority fields."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.schemas.core import EmploymentType, PayPeriod, WorkMode
from app.schemas.navigation import NavigationTurn

Label = Annotated[str, Field(min_length=1, max_length=120)]
DraftField = Literal[
    "headline",
    "region",
    "role_families",
    "employment_types",
    "work_modes",
    "locations",
    "compensation_floor",
    "currency",
    "compensation_period",
    "skills",
    "summary",
    "available_from",
    "available_until",
    "compensation",
    "availability",
    "review",
]


class DraftSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w .+#/-]+$")
    level: int | None = Field(default=None, ge=1, le=5)
    evidence: str = Field(default="", max_length=2000)
    assessment_note: str = Field(default="", max_length=2000)


class OnboardingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    headline: str | None = Field(default=None, min_length=3, max_length=180)
    region: str | None = Field(default=None, min_length=2, max_length=160)
    role_families: list[Label] = Field(default_factory=list, max_length=20)
    employment_types: list[EmploymentType] = Field(default_factory=list, max_length=5)
    work_modes: list[WorkMode] = Field(default_factory=list, max_length=3)
    locations: list[Label] = Field(default_factory=list, max_length=50)
    compensation_floor: str | None = Field(
        default=None, pattern=r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?$", max_length=15
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    compensation_period: PayPeriod | None = None
    skills: list[DraftSkill] = Field(default_factory=list, max_length=8)
    summary: str = Field(default="", max_length=10000)
    # ISO strings deliberately keep the browser and confirmation contract identical.
    available_from: str | None = Field(default=None, max_length=40)
    available_until: str | None = Field(default=None, max_length=40)
    skipped_fields: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=30
    )

    @field_validator("available_from", "available_until")
    @classmethod
    def aware_iso(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "T" not in value:
            raise ValueError("Availability must be a timezone-aware ISO timestamp")
        return TypeAdapter(AwareDatetime).validate_python(value).isoformat()

    @model_validator(mode="after")
    def ordered_and_unique(self) -> "OnboardingDraft":
        if self.available_from and self.available_until:
            if datetime.fromisoformat(self.available_from) >= datetime.fromisoformat(self.available_until):
                raise ValueError("Availability end must follow its start")
        names = [" ".join(skill.name.split()).casefold() for skill in self.skills]
        if len(set(names)) != len(names):
            raise ValueError("Draft skill names must be unique")
        for field in ("role_families", "employment_types", "work_modes", "locations", "skipped_fields"):
            items = getattr(self, field)
            if len({item.casefold() for item in items}) != len(items):
                raise ValueError("Draft lists must contain unique values")
        return self


class OnboardingChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=2000)
    consent_to_gemini: Literal[True]
    history: list[NavigationTurn] = Field(default_factory=list, max_length=20)
    draft: OnboardingDraft = Field(default_factory=OnboardingDraft)

    @field_validator("consent_to_gemini", mode="before")
    @classmethod
    def explicit_consent(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit consent is required")
        return value

    @model_validator(mode="after")
    def completed_bounded_history(self) -> "OnboardingChatIn":
        if len(self.history) % 2 or any(
            turn.role != ("user" if index % 2 == 0 else "assistant")
            for index, turn in enumerate(self.history)
        ):
            raise ValueError("History must contain completed user/assistant pairs")
        if len(self.message) + sum(len(turn.content) for turn in self.history) > 24000:
            raise ValueError("Conversation context exceeds the limit")
        return self


class OnboardingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    field: DraftField
    kind: Literal["preference", "skill_probe", "clarification", "review"]
    prompt: str = Field(min_length=1, max_length=1800)
    skill: str | None = Field(default=None, min_length=1, max_length=100)
    choices: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=6
    )

    @model_validator(mode="after")
    def named_probe(self) -> "OnboardingQuestion":
        if self.kind == "skill_probe" and (self.field != "skills" or not self.skill):
            raise ValueError("A skill probe must name one draft skill")
        return self


class OnboardingChatOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reply: str = Field(min_length=1, max_length=4000)
    question: OnboardingQuestion
    draft: OnboardingDraft
    missing_fields: list[DraftField]
    ready_for_review: bool
    version: Literal[1] = 1
