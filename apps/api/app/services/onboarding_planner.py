"""Pure question policy for a candidate's editable, unconfirmed onboarding draft.

The priorities are versioned product choices, not learned confidence, a hiring
probability or an assessment certification. Only explicit draft fields influence
the policy; it never infers personal traits or preferences from unrelated data.
"""

from collections.abc import Mapping
from typing import Any, Literal, TypedDict, TypeGuard

POLICY_VERSION = "adaptive-profile-v1"
MAX_SKILLS = 8
PRIMARY_SKILLS = 5

# Resolve occupation and usable profile constraints before secondary refinements.
# Already supplied fields are removed, so a detailed answer can skip many turns.
FIELD_PRIORITIES = {
    "role_families": 100,
    "headline": 95,
    "employment_types": 85,
    "work_modes": 84,
    "region": 83,
    "locations": 82,
    "currency": 60,
    "compensation_period": 59,
}
REQUIRED_FIELDS = tuple(FIELD_PRIORITIES)
_LIST_FIELDS = frozenset({"role_families", "employment_types", "work_modes", "locations"})


class Focus(TypedDict):
    kind: Literal["field", "skill_probe", "review"]
    field: str
    skill: str | None
    phase: Literal["practice", "rubric"] | None


class Readiness(TypedDict):
    ready: bool
    missing_fields: list[str]
    pending_skill_probes: list[str]
    skipped_fields: list[str]


def normalize_skill_name(name: str) -> str:
    """A stable skip key, without semantic aliases or qualification inference."""
    return " ".join(name.casefold().split())


def _text(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _skipped(draft: Mapping[str, Any]) -> set[str]:
    values = draft.get("skipped_fields", ())
    if not isinstance(values, (list, tuple)):
        return set()
    return {normalize_skill_name(value) for value in values if _text(value)}


def _skills(draft: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = draft.get("skills", ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("skills must be a bounded list")
    if len(values) > MAX_SKILLS:
        raise ValueError("onboarding supports at most eight skills")
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping) or not _text(item.get("name")):
            raise ValueError("each skill needs an explicit name")
        name = normalize_skill_name(item["name"])
        if name not in seen:
            result.append(item)
            seen.add(name)
    return result


def _present(draft: Mapping[str, Any], field: str) -> bool:
    value = draft.get(field)
    if field in _LIST_FIELDS:
        return isinstance(value, (list, tuple)) and bool(value) and all(_text(item) for item in value)
    if not _text(value):
        return False
    if field == "headline":
        return len(value.strip()) >= 3
    if field == "region":
        return len(value.strip()) >= 2
    if field == "currency":
        return len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()
    if field == "compensation_period":
        return value in {"ANNUAL", "MONTHLY", "HOURLY"}
    return True


def missing_fields(draft: Mapping[str, Any]) -> list[str]:
    """Missing profile requirements, including requirements the person skipped.

    A skip controls future questions; it cannot fabricate a value or make an
    incomplete profile ready for confirmation. Enum/value validation belongs to
    the draft and final candidate schemas at the API boundary.
    """
    modes = draft.get("work_modes", ())
    needs_locations = isinstance(modes, (list, tuple)) and any(mode in {"HYBRID", "ONSITE"} for mode in modes)
    return [
        field
        for field in REQUIRED_FIELDS
        if (field != "locations" or needs_locations) and not _present(draft, field)
    ]


def _pending_skills(draft: Mapping[str, Any]) -> list[tuple[int, Mapping[str, Any]]]:
    skipped = _skipped(draft)
    return [
        (index, item)
        for index, item in enumerate(_skills(draft))
        if (type(item.get("level")) is not int or not 1 <= item["level"] <= 5)
        and "skill:" + normalize_skill_name(item["name"]) not in skipped
    ]


def readiness(draft: Mapping[str, Any]) -> Readiness:
    """Readiness for review, never proof that a claimed skill was verified.

    Explicit user levels are self-reports. Only the integration boundary can
    accept a new model suggestion after grounding it in a named practice answer
    and a previously disclosed rubric. Optional compensation and dates may stay
    unknown; a person may also skip an individual skill probe.
    """
    missing = missing_fields(draft)
    pending = [item["name"].strip() for _, item in _pending_skills(draft)]
    return {
        "ready": not missing and not pending,
        "missing_fields": missing,
        "pending_skill_probes": pending,
        "skipped_fields": sorted(_skipped(draft)),
    }


def next_focus(draft: Mapping[str, Any]) -> Focus:
    """Choose one highest-priority unresolved field or named skill probe.

    ``skill:<casefolded name with collapsed whitespace>`` skips that named
    assessment; a plain field name skips that field. ``compensation`` and
    ``availability`` skip the optional grouped questions. Every call recomputes
    from the current draft, so corrections can reopen a field without a fixed
    stage counter or a monotonic completion lock.
    """
    skipped = _skipped(draft)
    choices: list[tuple[int, int, Focus]] = []
    for order, field in enumerate(missing_fields(draft)):
        if field not in skipped:
            choices.append(
                (
                    FIELD_PRIORITIES[field],
                    -order,
                    {"kind": "field", "field": field, "skill": None, "phase": None},
                )
            )

    skills = _skills(draft)
    if not skills and "skills" not in skipped:
        choices.append((90, 0, {"kind": "field", "field": "skills", "skill": None, "phase": None}))
    for index, item in _pending_skills(draft):
        priority = 78 - index if index < PRIMARY_SKILLS else 50 - index
        choices.append(
            (
                priority,
                -index,
                {
                    "kind": "skill_probe",
                    "field": "skills",
                    "skill": item["name"].strip(),
                    "phase": "rubric" if _text(item.get("evidence")) else "practice",
                },
            )
        )
    if choices:
        return max(choices, key=lambda choice: (choice[0], choice[1]))[2]

    if draft.get("compensation_floor") is None and not {"compensation", "compensation_floor"} & skipped:
        return {"kind": "field", "field": "compensation", "skill": None, "phase": None}
    if not draft.get("available_from") and not draft.get("available_until") and "availability" not in skipped:
        return {"kind": "field", "field": "availability", "skill": None, "phase": None}
    return {"kind": "review", "field": "review", "skill": None, "phase": None}
