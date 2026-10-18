"""Fixed feature math and consent boundaries are not predictive accuracy."""

from datetime import UTC, datetime
from math import log
from unittest.mock import patch

import pytest
from app.db.models import Candidate, Vacancy
from app.matching.text_alignment import EXTRACTOR_ID, MAX_CHARACTERS, professional_text_alignment
from app.services.clearing import compatibility_features


def test_fixed_alignment_matches_independent_two_document_tfidf():
    value, identity = professional_text_alignment("Python SQL", "", "Python Rust", "")
    unique_idf = 1 + log(3 / 2)
    assert value == pytest.approx(1 / (1 + unique_idf**2))
    assert identity == EXTRACTOR_ID


def test_unknown_redacted_oversized_and_disjoint_inputs_are_distinct():
    assert professional_text_alignment("", "", "Python", "") == (None, None)
    assert professional_text_alignment("a@example.invalid", "", "Python", "") == (None, None)
    assert professional_text_alignment("a" * MAX_CHARACTERS, "", "Python", "") == (None, None)
    assert professional_text_alignment("Python", "", "Rust", "") == (0, EXTRACTOR_ID)
    assert professional_text_alignment("Python", "", "PYTHON", "") == (1, EXTRACTOR_ID)


def test_feature_identity_contains_no_participant_text_and_contact_strings_are_redacted():
    first = professional_text_alignment("Python me@example.invalid", "", "Python", "")
    second = professional_text_alignment("Python", "", "Python", "")
    assert first == second
    assert first[1] == EXTRACTOR_ID


def test_punctuation_runs_with_no_email_do_not_create_spurious_contact_matches():
    # Legal-sized adversarial text previously triggered quadratic rescanning
    # inside the email local-part character class at every word boundary.
    value, identity = professional_text_alignment("a-" * 9900, "", "Python", "")
    assert value == 0
    assert identity == EXTRACTOR_ID


def test_native_feature_helper_skips_professional_text_without_explicit_learning_permission():
    candidate = Candidate(
        id="c",
        version=1,
        headline="Python",
        role_families=["ENGINEERING"],
        work_modes=["REMOTE"],
        employment_types=["FULL_TIME"],
    )
    vacancy = Vacancy(
        id="v",
        version=1,
        title="Python",
        description="",
        role_family="ENGINEERING",
        work_mode="REMOTE",
        employment_type="FULL_TIME",
    )
    with patch("app.services.clearing.professional_text_alignment") as extract:
        features = compatibility_features(candidate, vacancy, (), (), datetime.now(UTC))
        extract.assert_not_called()
    assert features.text_relevance is None
    assert features.text_relevance_model_id is None
    features = compatibility_features(
        candidate, vacancy, (), (), datetime.now(UTC), text_learning_enabled=True
    )
    assert features.text_relevance == 1
    assert features.text_relevance_model_id == EXTRACTOR_ID
