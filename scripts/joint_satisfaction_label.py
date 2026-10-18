"""Explicit policies for paired, directly reported ordinal satisfaction ratings.

The caller must establish that both ratings describe the same employee/job and
follow-up period. A joint score is a policy index on a 0–100 scale, never a
probability or evidence that ordinal category gaps are equal satisfaction gaps.
"""

from __future__ import annotations

from math import isfinite
from numbers import Real


def _rating(value: int | float | None, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be an integer ordinal rating from 0 through 4, or null")
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite ordinal rating") from exc
    if not isfinite(normalized) or not normalized.is_integer() or not 0 <= normalized <= 4:
        raise ValueError(f"{name} must be an integer ordinal rating from 0 through 4")
    return int(normalized)


def joint_satisfaction(
    employee_rating: int | float | None,
    manager_rating: int | float | None,
    *,
    aggregation: str = "minimum",
) -> dict:
    """Combine two observed ratings without substituting for either respondent.

    ``minimum`` takes the lower ordinal rating; a high rating from one party
    cannot compensate for dissatisfaction from the other. This policy is not
    learned or a validated measure of joint welfare. Missing either rating leaves
    the joint label and score unknown. Other policies are not supported.
    """
    if not isinstance(aggregation, str) or aggregation != "minimum":
        raise ValueError("aggregation must be 'minimum'")
    employee = _rating(employee_rating, "employee_rating")
    manager = _rating(manager_rating, "manager_rating")
    if employee is None and manager is None:
        status = "MISSING_BOTH"
    elif employee is None:
        status = "MISSING_EMPLOYEE"
    elif manager is None:
        status = "MISSING_MANAGER"
    else:
        status = "OBSERVED_PAIRED"
    rating: float | None = None
    if employee is not None and manager is not None:
        rating = float(min(employee, manager))
    return {
        "employee_rating": employee,
        "manager_rating": manager,
        "joint_rating": rating,
        "joint_score": None if rating is None else 100 * rating / 4,
        "status": status,
        "aggregation": aggregation,
    }
