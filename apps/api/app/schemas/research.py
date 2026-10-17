"""Bounded offline synthetic replay input, separate from live recommendation data."""

from typing import Literal

from pydantic import Field

from app.schemas.core import Input
from app.schemas.responses import Envelope


class SyntheticProbability(Input):
    candidate_id: str = Field(pattern=r"^synthetic-[A-Za-z0-9_-]{1,60}$")
    success: float = Field(ge=0, le=1, allow_inf_nan=False)


class SyntheticScenario(Input):
    scenario_id: str = Field(min_length=1, max_length=80)
    weight: float = Field(ge=0, le=1, allow_inf_nan=False)
    candidates: list[SyntheticProbability] = Field(max_length=100)
    job_wide_failure: float = Field(ge=0, le=1, allow_inf_nan=False)
    assumption_version: str = Field(min_length=1, max_length=80)


class SyntheticModel(Input):
    version: str = Field(min_length=1, max_length=80)
    scenarios: list[SyntheticScenario] = Field(min_length=1, max_length=20)
    conditional_independence_asserted: bool


class SyntheticVacancy(Input):
    vacancy_id: str = Field(pattern=r"^synthetic-[A-Za-z0-9_-]{1,60}$")
    role_version: int = Field(ge=1)
    shortlist_limit: int = Field(ge=0, le=10)
    models: list[SyntheticModel] = Field(default_factory=list, max_length=5)


class SyntheticEdge(Input):
    candidate_id: str = Field(pattern=r"^synthetic-[A-Za-z0-9_-]{1,60}$")
    vacancy_id: str = Field(pattern=r"^synthetic-[A-Za-z0-9_-]{1,60}$")
    routing_value: float = Field(ge=0, le=100, allow_inf_nan=False)
    attention_cost: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    delay_cost: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)


class ReplayInput(Input):
    fictional_only: Literal[True]
    state_version: str = Field(min_length=1, max_length=80)
    vacancies: list[SyntheticVacancy] = Field(min_length=1, max_length=20)
    edges: list[SyntheticEdge] = Field(max_length=500)


class ReplayOutput(Input):
    run_id: str
    snapshot_hash: str
    mode: Literal["SHADOW"]
    certification_state: Literal["CANNOT_CERTIFY"]
    side_effect_count: Literal[0]
    reasons: list[str]


ReplayEnvelope = Envelope[ReplayOutput]
