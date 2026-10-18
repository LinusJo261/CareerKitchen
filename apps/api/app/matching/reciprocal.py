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


def skill_overlap(
    confirmed_skills: tuple[tuple[str, tuple[str, ...]], ...],
    preferred: tuple[str, ...],
) -> tuple[float | None, float | None]:
    """Precision and Jaccard over confirmed concepts and stated preferences.

    Synonyms of one confirmed concept count once. An ambiguous alias cannot
    silently assert multiple skills. Unknown preference text remains unmatched
    in the union; no preferences means not applicable, as in skill_coverage.
    """
    wanted = {normalize_skill(value) for value in preferred}
    if not wanted:
        return None, None
    concepts: dict[str, set[str]] = {}
    for name, aliases in confirmed_skills:
        canonical = normalize_skill(name)
        concepts.setdefault(canonical, set()).update(normalize_skill(value) for value in (name, *aliases))
    index: dict[str, set[str]] = {}
    for canonical, concept_aliases in concepts.items():
        for alias in concept_aliases:
            index.setdefault(alias, set()).add(canonical)
    wanted_concepts = set()
    for value in wanted:
        if value in concepts:
            wanted_concepts.add(("confirmed", value))
            continue
        matches = index.get(value, set())
        wanted_concepts.add(("confirmed", next(iter(matches))) if len(matches) == 1 else ("unmatched", value))
    known = {("confirmed", canonical) for canonical in concepts}
    overlap = len(known & wanted_concepts)
    return overlap / len(known) if known else 0.0, overlap / len(known | wanted_concepts)


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
    skill_precision: float | None = None
    skill_jaccard: float | None = None
    text_relevance: float | None = None
    text_relevance_model_id: str | None = None

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
            "skill_precision",
            "skill_jaccard",
            "text_relevance",
        ):
            value = getattr(self, name)
            if value is None and name in {
                "employer_skills",
                "skill_precision",
                "skill_jaccard",
                "text_relevance",
            }:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric, not boolean")
            probability(value, name)
        if (self.text_relevance is None) != (self.text_relevance_model_id is None):
            raise ValueError("text relevance and its immutable model identity must be supplied together")
        if self.text_relevance_model_id is not None and (
            not isinstance(self.text_relevance_model_id, str)
            or len(self.text_relevance_model_id) != 64
            or any(value not in "0123456789abcdef" for value in self.text_relevance_model_id)
        ):
            raise ValueError("text relevance model identity must be a SHA256 digest")


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
