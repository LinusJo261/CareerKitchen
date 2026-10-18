"""Versioned cold-start compatibility; never a learned probability."""

from dataclasses import asdict, dataclass
from math import sqrt

from .attention import MarketPrices
from .score import DirectionScore
from .types import Side, boolean, probability, stable_hash


def normalize_skill(value: str) -> str:
    return " ".join(value.casefold().split())


def skill_coverage(
    confirmed_skills: tuple[tuple[str, tuple[str, ...]], ...],
    preferred: tuple[str, ...],
) -> float | None:
    """Aliases come only from the curated taxonomy, never inferred from resumes.

    No preferences means not applicable, not zero ability. Unmatched preferences
    remain unmatched; free-text requirements are not silently discarded.
    """
    wanted = {normalize_skill(key) for key in preferred}
    if not wanted:
        return None
    known = {normalize_skill(value) for name, aliases in confirmed_skills for value in (name, *aliases)}
    return len(wanted & known) / len(wanted)


@dataclass(frozen=True)
class ReciprocalFeatures:
    candidate_id: str
    vacancy_id: str
    candidate_version: int
    vacancy_version: int
    as_of: str
    employer_skills: float | None
    candidate_role: float
    candidate_work_mode: float
    candidate_employment_type: float
    eligible: bool

    def __post_init__(self) -> None:
        boolean(self.eligible, "eligible")
        for value in (
            self.employer_skills,
            self.candidate_role,
            self.candidate_work_mode,
            self.candidate_employment_type,
        ):
            if value is not None:
                probability(value, "compatibility")


def score_reciprocal(features: ReciprocalFeatures, prices: MarketPrices) -> dict:
    if not features.eligible:
        raise ValueError("hard eligibility must be checked before scoring")
    # Role compatibility supplies the employer's eligibility baseline. Optional
    # skills participate only when specified; unsupported experience/evidence
    # targets are unknown and are never guessed from prose or private documents.
    employer_values = [features.candidate_role]
    if features.employer_skills is not None:
        employer_values.append(features.employer_skills)
    employer = sum(employer_values) / len(employer_values)
    candidate = (
        features.candidate_role + features.candidate_work_mode + features.candidate_employment_type
    ) / 3
    relevance = sqrt(employer * candidate)
    directions = [
        DirectionScore(
            Side.CANDIDATE,
            relevance,
            prices.mu_candidate,
            prices.job_congestion,
            relevance - prices.mu_candidate - prices.job_congestion,
        ),
        DirectionScore(
            Side.EMPLOYER,
            relevance,
            prices.mu_employer,
            prices.candidate_congestion,
            relevance - prices.mu_employer - prices.candidate_congestion,
        ),
    ]
    best = max(directions, key=lambda direction: direction.net_surplus)
    return {
        "model_version": "reciprocal-compatibility-v1",
        "feature_version": "reciprocal-structured-v1",
        "estimate_kind": "NONPROBABILISTIC",
        "feature_hash": stable_hash(features),
        "features": asdict(features),
        "unknown_features": ["experience_alignment", "evidence_alignment"],
        "weights_version": "equal-applicable-v1",
        "employer_fit": employer,
        "candidate_fit": candidate,
        "relevance": relevance,
        "reason_codes": ["RECIPROCAL_COMPATIBILITY", "STATED_ACCEPTABLE_PREFERENCES"],
        "candidate_first": asdict(directions[0]),
        "employer_first": asdict(directions[1]),
        "prices": asdict(prices),
        "first_mover": best.side.value,
        "net_surplus": best.net_surplus,
    }
