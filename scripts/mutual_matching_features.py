"""Pure, offline pair features from caller-confirmed structured information.

This module never reads profiles, resumes, outcomes or databases. Callers must
resolve skill aliases through a curated taxonomy and confirm which experience
periods are relevant before passing them here. Alignment values describe stated
preferences; they are not this introduction's eventual Interested decisions.
"""

from __future__ import annotations

from datetime import date
from math import isfinite
from numbers import Real

FEATURE_NAMES = (
    "required_skill_coverage",
    "preferred_skill_coverage",
    "relevant_experience_years",
    "experience_requirement_coverage",
    "employer_role_preference_alignment",
    "candidate_role_preference_alignment",
    "candidate_work_mode_preference_alignment",
    "candidate_employment_type_preference_alignment",
    "candidate_compensation_preference_alignment",
    "candidate_schedule_preference_alignment",
)
PREFERENCE_ALIGNMENT_NAMES = FEATURE_NAMES[4:]


def _number(value: object, name: str, *, bounded: bool) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a number or null")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not isfinite(result) or result < 0 or (bounded and result > 1):
        raise ValueError(f"{name} must be finite and within its permitted range")
    return result


def validate_features(values: dict) -> dict[str, float | None]:
    """Require every declared feature, using null for unknown/not applicable.

    Only experience years may exceed one. The strict allowlist keeps identity,
    outcome and free-text fields out of this experiment's predictive matrix.
    """
    if not isinstance(values, dict) or set(values) != set(FEATURE_NAMES):
        raise ValueError("Features must contain exactly the ten declared feature names")
    return {
        name: _number(values[name], name, bounded=name != "relevant_experience_years")
        for name in FEATURE_NAMES
    }


def _skills(values: tuple[str, ...] | None, name: str) -> set[str] | None:
    if values is None:
        return None
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be a tuple of canonical skill names or null")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} contains an empty or invalid skill name")
    return {" ".join(value.casefold().split()) for value in values}


def _coverage(known: set[str] | None, wanted: set[str] | None) -> float | None:
    if known is None or not wanted:
        return None
    return len(known & wanted) / len(wanted)


def _experience_years(
    periods: tuple[tuple[date, date | None], ...] | None,
    as_of: date,
) -> float | None:
    if periods is None:
        return None
    if not isinstance(periods, tuple):
        raise ValueError("Relevant experience periods must be a tuple or null")
    intervals = []
    for period in periods:
        if not isinstance(period, tuple) or len(period) != 2:
            raise ValueError("Each experience period must contain a start and optional end")
        start, end = period
        if type(start) is not date or (end is not None and type(end) is not date):
            raise ValueError("Experience periods must use dates, not timestamps or text")
        if start > as_of:
            raise ValueError("Experience cannot start after the feature cutoff")
        if end is not None and end < start:
            raise ValueError("Experience cannot end before it starts")
        intervals.append((start, min(end, as_of) if end is not None else as_of))
    merged: list[tuple[date, date]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    # Date intervals measure elapsed time, without inventing extra inclusive days.
    return sum((end - start).days for start, end in merged) / 365.25


def build_features(
    *,
    confirmed_skills: tuple[str, ...] | None,
    required_skills: tuple[str, ...] | None,
    preferred_skills: tuple[str, ...] | None,
    relevant_experience_periods: tuple[tuple[date, date | None], ...] | None,
    minimum_experience_years: float | None,
    as_of: date,
    preference_alignments: dict[str, float | None],
) -> dict[str, float | None]:
    """Build features without guessing interest, relevance or essential eligibility.

    Unknown experience is null; a confirmed empty history is zero. Required skill
    coverage is descriptive only and never overrides the backend's evidence and
    eligibility checks. Pay/schedule preferences must be supplied by the caller,
    using information available before exposure and compatible units.
    """
    if type(as_of) is not date:
        raise ValueError("Feature cutoff must be a date")
    if not isinstance(preference_alignments, dict) or set(preference_alignments) != set(
        PREFERENCE_ALIGNMENT_NAMES
    ):
        raise ValueError("Supply exactly the six declared preference alignments")
    known = _skills(confirmed_skills, "confirmed_skills")
    required = _skills(required_skills, "required_skills")
    preferred = _skills(preferred_skills, "preferred_skills")
    years = _experience_years(relevant_experience_periods, as_of)
    minimum = _number(minimum_experience_years, "minimum_experience_years", bounded=False)
    return validate_features(
        {
            "required_skill_coverage": _coverage(known, required),
            "preferred_skill_coverage": _coverage(known, preferred),
            "relevant_experience_years": years,
            "experience_requirement_coverage": (
                min(1.0, years / minimum) if years is not None and minimum else None
            ),
            **preference_alignments,
        }
    )
