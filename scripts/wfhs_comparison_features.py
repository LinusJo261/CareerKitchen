"""Baseline-only feature variants for the offline WFHS model comparison.

The hours gap compares actual hours in the previous week with usual hours
expected by a manager. It is a workload proxy, not a candidate preference-fit
measure. None of these features establishes what was known before hiring.
"""

from __future__ import annotations

from math import isfinite
from numbers import Real

BASE_FEATURE_NAMES = (
    "control_over_work_hours",
    "family_supportive_supervisor",
    "decision_authority",
    "psychological_job_demands",
    "hours_worked_last_week",
    "hours_expected_by_manager",
)
ADDITIONAL_CONDITION_FEATURE_NAMES = (
    "work_to_family_conflict",
    "emotional_burnout",
    "work_family_climate",
)
CONTEXT_FEATURE_NAMES = BASE_FEATURE_NAMES + ADDITIONAL_CONDITION_FEATURE_NAMES + ("baseline_satisfaction",)
INTERACTION_FEATURE_NAMES = (
    "hours_gap",
    "absolute_hours_gap",
    "demands_by_low_control",
    "demands_by_low_support",
)
VARIANTS = ("baseline", "interactions")
EXPANDED_VARIANTS = ("expanded", "baseline_with_satisfaction", "expanded_with_satisfaction")
SATISFACTION_ONLY_VARIANTS = ("satisfaction_only",)


def feature_names(variant: str) -> list[str]:
    """Return the fixed ordered output contract for a deliberate feature ablation."""
    if (
        not isinstance(variant, str)
        or variant not in VARIANTS + EXPANDED_VARIANTS + SATISFACTION_ONLY_VARIANTS
    ):
        raise ValueError("Choose a documented WFHS feature variant")
    if variant == "satisfaction_only":
        return ["baseline_satisfaction"]
    names: tuple[str, ...] = BASE_FEATURE_NAMES
    if variant == "interactions":
        names += INTERACTION_FEATURE_NAMES
    elif variant in ("expanded", "expanded_with_satisfaction"):
        names += ADDITIONAL_CONDITION_FEATURE_NAMES
    if variant in ("baseline_with_satisfaction", "expanded_with_satisfaction"):
        names += ("baseline_satisfaction",)
    return list(names)


def feature_bounds(name: str) -> tuple[int, int]:
    """Use the same survey/derived domains during input and artifact validation."""
    if name == "hours_gap":
        return -168, 168
    if name in BASE_FEATURE_NAMES[-2:] or name == "absolute_hours_gap":
        return 0, 168
    if name in INTERACTION_FEATURE_NAMES:
        return 0, 1
    if name == "emotional_burnout":
        return 1, 7
    if name in CONTEXT_FEATURE_NAMES:
        return 1, 5
    raise ValueError("Unknown WFHS feature name")


def feature_variant(features: dict[str, float | None], variant: str) -> dict[str, float | None]:
    """Validate baseline inputs and select a fixed, independent feature mapping.

    Missing operands leave the corresponding interaction unknown. Validation
    accepts the legacy six fields or the complete ten-field baseline context.
    Expanded variants require the latter. Even unused context fields are checked;
    IDs, follow-up labels, source-column aliases, and partial contexts are rejected.
    Baseline satisfaction is an explicit existing-employee experiment, never a
    prehire or future satisfaction measurement.
    """
    selected_names = feature_names(variant)
    if not isinstance(features, dict) or set(features) not in (
        set(BASE_FEATURE_NAMES),
        set(CONTEXT_FEATURE_NAMES),
    ):
        raise ValueError("Use exactly the six legacy or ten context WFHS baseline features")
    if variant in EXPANDED_VARIANTS + SATISFACTION_ONLY_VARIANTS and set(features) != set(
        CONTEXT_FEATURE_NAMES
    ):
        raise ValueError("Expanded feature variants require the complete ten-field baseline context")
    supplied_names = (
        CONTEXT_FEATURE_NAMES if set(features) == set(CONTEXT_FEATURE_NAMES) else BASE_FEATURE_NAMES
    )

    validated: dict[str, float | None] = {}
    for name in supplied_names:
        value = features[name]
        if value is None:
            validated[name] = None
            continue
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be a finite real number or null")
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite real number or null") from exc
        low, high = feature_bounds(name)
        if not isfinite(number) or not low <= number <= high:
            raise ValueError(f"{name} must be between {low} and {high}, or null")
        validated[name] = number

    if variant != "interactions":
        return {name: validated[name] for name in selected_names}

    result = {name: validated[name] for name in BASE_FEATURE_NAMES}
    worked, expected = result["hours_worked_last_week"], result["hours_expected_by_manager"]
    gap = None if worked is None or expected is None else worked - expected
    result["hours_gap"] = gap
    result["absolute_hours_gap"] = None if gap is None else abs(gap)
    demands, control = result["psychological_job_demands"], result["control_over_work_hours"]
    result["demands_by_low_control"] = (
        None if demands is None or control is None else ((demands - 1) / 4) * ((5 - control) / 4)
    )
    support = result["family_supportive_supervisor"]
    result["demands_by_low_support"] = (
        None if demands is None or support is None else ((demands - 1) / 4) * ((5 - support) / 4)
    )
    return result
