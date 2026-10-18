"""Candidate onboarding accepts bounded profile details and safe professional links."""

import pytest
from app.schemas.core import CandidateInput, ProfessionalLinks
from pydantic import ValidationError


@pytest.mark.parametrize(
    "field,value",
    [
        ("linkedin", "https://linkedin.com/in/fictional-candidate"),
        ("linkedin", "https://www.linkedin.com/in/fictional-candidate/"),
        ("portfolio", "https://portfolio.example.invalid/work?project=fictional#overview"),
    ],
)
def test_professional_links_accept_https_profiles(field, value):
    result = ProfessionalLinks(**{field: value})
    assert getattr(result, field) == value


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,fictional",
        "http://www.linkedin.com/in/fictional-candidate",
        "//www.linkedin.com/in/fictional-candidate",
        "/in/fictional-candidate",
        "https:///in/fictional-candidate",
        "https://user:password@www.linkedin.com/in/fictional-candidate",
        "https://user@www.linkedin.com/in/fictional-candidate",
        "https://www.linkedin.com/in/fictional candidate",
        "https://www.linkedin.com/in/fictional\ncandidate",
        "https://www.linkedin.com:invalid/in/fictional-candidate",
        "https://www.linkedin.com:65536/in/fictional-candidate",
        "https://www.linkedin.com:0/in/fictional-candidate",
    ],
)
@pytest.mark.parametrize("field", ["linkedin", "portfolio"])
def test_professional_links_reject_unsafe_schemes_credentials_and_malformed_addresses(field, value):
    with pytest.raises(ValidationError):
        ProfessionalLinks(**{field: value})


@pytest.mark.parametrize(
    "value",
    [
        "https://portfolio.example.invalid/in/fictional-candidate",
        "https://linkedin.com.attacker.invalid/in/fictional-candidate",
        "https://www.linkedin.com.attacker.invalid/in/fictional-candidate",
        "https://linkedin.com@attacker.invalid/in/fictional-candidate",
        "https://attacker.invalid/www.linkedin.com/in/fictional-candidate",
    ],
)
def test_linkedin_link_is_pinned_to_linkedin_host(value):
    with pytest.raises(ValidationError):
        ProfessionalLinks(linkedin=value)


def test_professional_links_are_optional_bounded_and_do_not_accept_arbitrary_fields():
    assert ProfessionalLinks().model_dump(exclude_none=True) == {}
    assert ProfessionalLinks(linkedin="", portfolio=" ").model_dump(exclude_none=True) == {}
    with pytest.raises(ValidationError):
        ProfessionalLinks(portfolio="https://portfolio.example.invalid/" + "a" * 2048)
    with pytest.raises(ValidationError):
        ProfessionalLinks(provider_role="admin")


def test_display_name_is_bounded_and_omission_is_distinct_from_intentional_clearing():
    required = {
        "expected_version": 0,
        "headline": "Fictional test candidate",
        "region": "Seattle",
        "role_families": ["ENGINEERING"],
        "employment_types": ["FULL_TIME"],
        "work_modes": ["REMOTE"],
        "currency": "USD",
        "terms_accepted": True,
        "privacy_accepted": True,
        "profile_confirmed": True,
    }
    omitted = CandidateInput(**required)
    assert "display_name" not in omitted.model_fields_set
    assert "professional_links" not in omitted.model_fields_set
    cleared = CandidateInput(**required, display_name="", professional_links={})
    assert {"display_name", "professional_links"} <= cleared.model_fields_set
    assert CandidateInput(**required, display_name="x" * 120).display_name == "x" * 120
    with pytest.raises(ValidationError):
        CandidateInput(**required, display_name="x" * 121)
