"""Eligibility and bounded sparse retrieval; no database or vector-store access."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from heapq import nsmallest

from .types import SanitizedPairFeatures, boolean


class EligibilityState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_HUMAN_CLARIFICATION = "NEEDS_HUMAN_CLARIFICATION"


@dataclass(frozen=True, slots=True)
class EligibilitySnapshot:
    candidate_active: bool = True
    vacancy_active: bool = True
    blocked: bool = False
    employment_type_compatible: bool = True
    compensation_compatible: bool = True
    work_mode_compatible: bool = True
    legal_requirement_met: bool = True
    essential_requirements_met: bool = True
    role_expired: bool = False
    unsafe_or_banned: bool = False
    cycle_unavailable: bool = False
    ambiguous_requirement: bool = False
    availability_compatible: bool = True
    consent_for_recommendation: bool = True

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            boolean(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class Eligibility:
    state: EligibilityState
    reasons: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return self.state == EligibilityState.ELIGIBLE


def hard_feasible(snapshot: EligibilitySnapshot) -> Eligibility:
    positive = (
        "candidate_active",
        "vacancy_active",
        "employment_type_compatible",
        "compensation_compatible",
        "work_mode_compatible",
        "legal_requirement_met",
        "essential_requirements_met",
        "availability_compatible",
        "consent_for_recommendation",
    )
    negative = ("blocked", "role_expired", "unsafe_or_banned", "cycle_unavailable")
    reasons = tuple(name.upper() for name in positive if not getattr(snapshot, name)) + tuple(
        name.upper() for name in negative if getattr(snapshot, name)
    )
    if reasons:
        return Eligibility(EligibilityState.INELIGIBLE, reasons)
    if snapshot.ambiguous_requirement:
        return Eligibility(EligibilityState.NEEDS_HUMAN_CLARIFICATION, ("AMBIGUOUS_REQUIREMENT",))
    return Eligibility(EligibilityState.ELIGIBLE, ())


def features_eligible(features: SanitizedPairFeatures) -> bool:
    return all(
        (
            features.candidate_active,
            features.vacancy_active,
            features.availability_alignment,
            features.compensation_compatible,
            features.essential_requirements_met,
            features.consent_for_recommendation,
        )
    )


def sparse_retrieve(
    pool: Iterable[SanitizedPairFeatures],
    limit: int = 200,
) -> tuple[SanitizedPairFeatures, ...]:
    """Bounded top-k from an already scoped/index-filtered stream; never forms a cross product.

    The repository must bound its query before calling this pure helper. Input pair
    duplication is rejected rather than silently choosing a conflicting snapshot.
    """
    if not 0 <= limit <= 10_000:
        raise ValueError("retrieval limit must be in 0..10000")
    seen: set[tuple[str, str]] = set()

    def eligible() -> Iterable[SanitizedPairFeatures]:
        for features in pool:
            if features.pair in seen:
                raise ValueError("duplicate pair feature snapshot")
            seen.add(features.pair)
            if features_eligible(features):
                yield features

    return tuple(
        nsmallest(
            limit,
            eligible(),
            key=lambda f: (
                -(f.skill_alignment + f.experience_alignment + f.work_mode_alignment),
                f.pair,
            ),
        )
    )
