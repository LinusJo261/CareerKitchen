"""Versioned cold-start compatibility; never a learned probability."""

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite, sqrt

from .attention import MarketPrices
from .score import DirectionScore
from .types import Side, aware, boolean, probability, stable_hash


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
        for name in ("candidate_id", "vacancy_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty ID")
        for name in ("candidate_version", "vacancy_version"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.as_of, str):
            raise ValueError("as_of must be a timezone-aware ISO datetime")
        try:
            snapshot_time = datetime.fromisoformat(self.as_of)
        except ValueError as exc:
            raise ValueError("as_of must be a timezone-aware ISO datetime") from exc
        aware(snapshot_time, "as_of")
        boolean(self.eligible, "eligible")
        for name in (
            "employer_skills",
            "candidate_role",
            "candidate_work_mode",
            "candidate_employment_type",
        ):
            value = getattr(self, name)
            if value is None and name == "employer_skills":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric, not boolean")
            probability(value, name)


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
    if any(
        not isfinite(value)
        for direction in directions
        for value in (
            direction.gross_value,
            direction.attention_cost,
            direction.congestion_cost,
            direction.net_surplus,
        )
    ):
        raise ValueError("reciprocal score arithmetic must remain finite")
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
