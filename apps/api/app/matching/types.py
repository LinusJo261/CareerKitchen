"""Immutable inputs shared by the routing and research algorithms.

These types deliberately have no arbitrary feature dictionary, ORM objects, private
salary floors, documents, protected attributes, or billing data.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps
from math import isfinite


def finite(value: float, name: str, minimum: float = 0.0) -> None:
    if not isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")


def probability(value: float, name: str) -> None:
    finite(value, name)
    if value > 1:
        raise ValueError(f"{name} must be <= 1")


def boolean(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")


def aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def cap(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise ValueError("selected active decision cap must be an integer in 1..10")


class Side(StrEnum):
    CANDIDATE = "CANDIDATE"
    EMPLOYER = "EMPLOYER"


class EstimateKind(StrEnum):
    NONPROBABILISTIC = "NONPROBABILISTIC"
    SUPPLIED_MODEL = "SUPPLIED_MODEL"


@dataclass(frozen=True, slots=True)
class SanitizedPairFeatures:
    candidate_id: str
    vacancy_id: str
    role_family: str
    feature_version: str
    as_of: datetime
    skill_alignment: float = 0.0
    work_mode_alignment: float = 0.0
    experience_alignment: float = 0.0
    evidence_alignment: float = 0.0
    availability_alignment: bool = True
    compensation_compatible: bool = True
    candidate_active: bool = True
    vacancy_active: bool = True
    essential_requirements_met: bool = True
    consent_for_recommendation: bool = True

    def __post_init__(self) -> None:
        if not all((self.candidate_id, self.vacancy_id, self.role_family, self.feature_version)):
            raise ValueError("IDs, role family and feature version are required")
        aware(self.as_of, "as_of")
        for name in ("skill_alignment", "work_mode_alignment", "experience_alignment", "evidence_alignment"):
            probability(getattr(self, name), name)
        for name in (
            "availability_alignment",
            "compensation_compatible",
            "candidate_active",
            "vacancy_active",
            "essential_requirements_met",
            "consent_for_recommendation",
        ):
            boolean(getattr(self, name), name)

    @property
    def pair(self) -> tuple[str, str]:
        return self.candidate_id, self.vacancy_id

    @property
    def digest(self) -> str:
        return stable_hash(self)


@dataclass(frozen=True, slots=True)
class Capacity:
    scope_id: str
    selected_maximum: int = 10
    active_count: int = 0
    waiting_count: int = 0
    waiting_maximum: int = 10

    def __post_init__(self) -> None:
        cap(self.selected_maximum)
        if not 0 <= self.active_count <= self.selected_maximum:
            raise ValueError("active count exceeds selected cap")
        if self.waiting_count < 0 or self.waiting_maximum < 0:
            raise ValueError("waiting counts must be nonnegative")

    @property
    def free(self) -> int:
        return self.selected_maximum - self.active_count


def stable_hash(value: object) -> str:
    def encode(item: object) -> object:
        if isinstance(item, datetime):
            return item.isoformat()
        if hasattr(item, "__dataclass_fields__"):
            return asdict(item)  # type: ignore[call-overload]
        raise TypeError(f"unsupported hash type: {type(item).__name__}")

    return sha256(
        dumps(value, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
