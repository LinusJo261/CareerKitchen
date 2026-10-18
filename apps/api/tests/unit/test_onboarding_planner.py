from copy import deepcopy

import pytest
from app.services.onboarding_planner import missing_fields, next_focus, normalize_skill_name, readiness


def complete_draft(**changes):
    draft = {
        "headline": "Backend engineer",
        "role_families": ["software_engineering"],
        "region": "Seattle",
        "employment_types": ["FULL_TIME"],
        "work_modes": ["REMOTE"],
        "currency": "USD",
        "compensation_period": "ANNUAL",
        "compensation_floor": None,
        "available_from": None,
        "available_until": None,
        "skills": [{"name": "Python", "level": 3, "evidence": "", "assessment_note": "Self-reported"}],
        "skipped_fields": ["compensation", "availability"],
    }
    return {**draft, **changes}


def test_detailed_draft_skips_known_questions_and_reaches_review():
    draft = complete_draft()
    assert readiness(draft)["ready"] is True
    assert missing_fields(draft) == []
    assert next_focus(draft) == {"kind": "review", "field": "review", "skill": None, "phase": None}


def test_empty_draft_starts_with_occupation_instead_of_a_fixed_step_counter():
    assert next_focus({})["field"] == "role_families"
    assert next_focus({"role_families": ["plumbing"]})["field"] == "headline"
    assert next_focus({"role_families": ["plumbing"], "headline": "Commercial plumber"})["field"] == "skills"


def test_skipped_required_field_stays_missing_but_is_not_reasked():
    draft = complete_draft(currency=None, skipped_fields=["currency", "compensation", "availability"])
    assert missing_fields(draft) == ["currency"]
    assert readiness(draft)["ready"] is False
    assert next_focus(draft)["kind"] == "review"


def test_named_skill_gets_practice_then_rubric_instead_of_an_invented_level():
    draft = complete_draft(skills=[{"name": "Python", "level": None, "evidence": ""}])
    assert next_focus(draft) == {
        "kind": "skill_probe",
        "field": "skills",
        "skill": "Python",
        "phase": "practice",
    }
    assert readiness(draft)["pending_skill_probes"] == ["Python"]
    draft["skills"][0]["evidence"] = "I built a Python CLI that reads CSV files and validates rows."
    assert next_focus(draft)["phase"] == "rubric"
    assert draft["skills"][0]["level"] is None
    draft["skills"][0]["level"] = 2
    assert next_focus(draft)["kind"] == "review"


def test_one_resolved_skill_advances_to_the_next_named_skill():
    draft = complete_draft(
        skills=[
            {"name": "Python", "level": 3, "evidence": "A described project"},
            {"name": "SQL", "level": None, "evidence": ""},
        ]
    )
    assert next_focus(draft)["skill"] == "SQL"


def test_skip_is_scoped_to_one_canonical_named_skill():
    draft = complete_draft(
        skills=[{"name": "  Data   Analysis ", "level": None}, {"name": "SQL", "level": None}],
        skipped_fields=["skill:DATA analysis", "compensation", "availability"],
    )
    assert normalize_skill_name(" Data   Analysis ") == "data analysis"
    assert readiness(draft)["pending_skill_probes"] == ["SQL"]
    assert next_focus(draft)["skill"] == "SQL"


def test_primary_probes_have_priority_over_secondary_skills_and_currency():
    skills = [{"name": f"Skill {index}", "level": 3} for index in range(8)]
    skills[4]["level"] = None
    skills[5]["level"] = None
    draft = complete_draft(skills=skills, currency=None)
    assert next_focus(draft)["skill"] == "Skill 4"
    draft["skills"][4]["level"] = 2
    assert next_focus(draft)["field"] == "currency"
    draft["currency"] = "USD"
    assert next_focus(draft)["skill"] == "Skill 5"


def test_optional_unknowns_can_be_skipped_without_inventing_preferences():
    draft = complete_draft(skipped_fields=[])
    assert readiness(draft)["ready"] is True
    assert next_focus(draft)["field"] == "compensation"
    draft["skipped_fields"].append("compensation")
    assert next_focus(draft)["field"] == "availability"
    draft["skipped_fields"].append("availability")
    assert next_focus(draft)["kind"] == "review"
    assert draft["compensation_floor"] is None
    assert draft["available_from"] is None


def test_correction_reopens_a_previously_complete_field():
    draft = complete_draft()
    assert next_focus(draft)["kind"] == "review"
    draft["role_families"] = []
    assert next_focus(draft)["field"] == "role_families"
    assert readiness(draft)["ready"] is False
    draft["role_families"] = ["technical_writing"]
    assert readiness(draft)["ready"] is True


def test_no_currency_or_pay_period_is_inferred_from_region_or_headline():
    draft = complete_draft(currency=None, compensation_period=None)
    assert missing_fields(draft) == ["currency", "compensation_period"]
    assert next_focus(draft)["field"] == "currency"
    assert draft["currency"] is None


@pytest.mark.parametrize("modes", [["ONSITE"], ["HYBRID"], ["REMOTE", "HYBRID"]])
def test_nonremote_modes_require_explicit_acceptable_locations(modes):
    draft = complete_draft(work_modes=modes, locations=[])
    assert missing_fields(draft) == ["locations"]
    assert next_focus(draft)["field"] == "locations"
    assert readiness(draft)["ready"] is False
    assert draft["region"] == "Seattle"
    draft["locations"] = ["Seattle"]
    assert readiness(draft)["ready"] is True


def test_skipping_nonremote_locations_prevents_loop_without_assuming_worldwide_acceptance():
    draft = complete_draft(
        work_modes=["ONSITE"], locations=[], skipped_fields=["locations", "compensation", "availability"]
    )
    assert next_focus(draft)["kind"] == "review"
    assert readiness(draft)["ready"] is False
    assert missing_fields(draft) == ["locations"]


def test_explicitly_broad_role_choices_remain_editable_without_a_fabricated_preference():
    draft = complete_draft(role_families=["software", "writing", "support", "design"])
    assert readiness(draft)["ready"] is True
    assert draft["role_families"] == ["software", "writing", "support", "design"]


def test_planning_never_mutates_or_annotates_the_unconfirmed_draft():
    draft = complete_draft(skills=[{"name": "Python", "level": None, "evidence": ""}])
    before = deepcopy(draft)
    for _ in range(2):
        readiness(draft)
        next_focus(draft)
    assert draft == before


@pytest.mark.parametrize("level", [None, 0, 6, True, "3"])
def test_only_explicit_valid_integer_levels_resolve_a_probe(level):
    draft = complete_draft(skills=[{"name": "Python", "level": level}])
    assert next_focus(draft)["kind"] == "skill_probe"
    assert readiness(draft)["ready"] is False


def test_skill_inventory_is_optional_when_explicitly_skipped():
    draft = complete_draft(skills=[], skipped_fields=["skills", "compensation", "availability"])
    assert next_focus(draft)["kind"] == "review"
    assert readiness(draft)["ready"] is True


def test_assessment_is_bounded_to_eight_named_skills():
    draft = complete_draft(skills=[{"name": str(index), "level": None} for index in range(9)])
    with pytest.raises(ValueError, match="eight"):
        next_focus(draft)
    with pytest.raises(ValueError, match="eight"):
        readiness(draft)
