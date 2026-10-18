"""Portable relevance contracts; fictional examples are not hiring validation."""

import copy
import json
import math

import pytest
from app.matching.text_relevance import (
    FEATURE_NAMES,
    MAX_TEXT_CHARACTERS,
    PortableTextRanker,
    TextFeatureIndex,
    _tokens,
    artifact_digest,
)


def model():
    count = len(FEATURE_NAMES)
    return PortableTextRanker((0.0,) * count, (1.0,) * count, (1.0,) * count, 1.0, "a" * 64, 10, 20, 200)


def test_matching_text_has_stronger_features_and_bounded_finite_values():
    index = TextFeatureIndex(["Python database engineering", "Welding industrial safety"])
    rows = index.features("Python database engineering")
    assert len(rows) == 2
    assert all(len(row) == len(FEATURE_NAMES) for row in rows)
    assert all(0 <= value <= 1 and math.isfinite(value) for row in rows for value in row)
    assert rows[0][1] == pytest.approx(1.0)
    assert rows[0][3:6] == pytest.approx((1.0, 1.0, 1.0))
    assert rows[1][1:8] == pytest.approx((0.0,) * 7)
    assert model().score_features(rows)[0] > model().score_features(rows)[1]


def test_missing_query_terms_reduce_coverage_without_changing_fitted_idf():
    index = TextFeatureIndex(["Python", "Welding"])
    original = dict(index.word_idf)
    before = index.features("Python")[0]
    after = index.features("Python nonexistent")[0]
    assert before[4] == 1.0 and after[4] == 0.5
    assert after[6] < before[6]
    assert index.word_idf == original


def test_contacts_do_not_supply_similarity_evidence_and_cpp_is_preserved():
    left = TextFeatureIndex(["C++ engineer alice@example.org https://example.org alice", "C# engineer"])
    right = TextFeatureIndex(["C++ engineer bob@example.net https://example.net alice", "C# engineer"])
    assert left.features("C++ engineer") == right.features("C++ engineer")
    assert left.features("C++ engineer")[0][3] > left.features("C++ engineer")[1][3]


def test_contact_filter_preserves_punctuation_runs_without_restarting_inside_them():
    # These contain no email address. A word-boundary email prefix repeatedly
    # rescanned their suffixes; this regression has no timing-dependent assertion.
    assert _tokens("a-" * 4096) == ["a"] * 4096
    assert _tokens("a+" * 4096) == ["a+"] * 4096
    assert _tokens("a." * 4096) == ["a." * 4095 + "a"]
    assert _tokens("C++ engineer a.+-person@example.org; Python") == ["c++", "engineer", "python"]


def test_index_order_only_permutates_outputs():
    documents = ["python data engineering", "welding safety", "accounting finance"]
    forward = TextFeatureIndex(documents).features("data python")
    reversed_rows = TextFeatureIndex(list(reversed(documents))).features("data python")
    for left, right in zip(forward, reversed(reversed_rows), strict=True):
        assert left == pytest.approx(right)


def test_json_round_trip_has_integrity_and_explicit_nonproduction_target():
    trained = model()
    payload = trained.to_dict()
    loaded = PortableTextRanker.from_dict(json.loads(json.dumps(payload)))
    assert loaded == trained
    assert payload["target"] == "PUBLIC_HUMAN_ORDINAL_RELEVANCE"
    assert payload["production_eligible"] is False
    assert payload["scope"] == "OFFLINE_RESEARCH_ONLY"
    assert loaded.score("Python", ["Python", "Welding"]) == trained.score("Python", ["Python", "Welding"])
    assert not any(
        key in payload for key in ("resumes", "queries", "vocabulary", "candidate_id", "organization_id")
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "checksum",
        "extra",
        "target",
        "production",
        "nan",
        "infinity",
        "boolean",
        "length",
        "scale",
        "coefficient",
    ],
)
def test_untrusted_json_artifacts_fail_closed(mutation):
    payload = copy.deepcopy(model().to_dict())
    if mutation == "checksum":
        payload["coefficients"][0] = 2.0
    elif mutation == "extra":
        payload["resume"] = "private text"
    elif mutation == "target":
        payload["target"] = "OBSERVED_MUTUAL_INTEREST"
    elif mutation == "production":
        payload["production_eligible"] = True
    elif mutation in {"nan", "infinity", "boolean"}:
        payload["coefficients"][0] = {"nan": float("nan"), "infinity": float("inf"), "boolean": True}[
            mutation
        ]
    elif mutation == "length":
        payload["coefficients"] = [1.0]
    elif mutation == "scale":
        payload["scales"][0] = 0.0
    else:
        payload["coefficients"][0] = 1e10
    if mutation not in {"checksum", "nan", "infinity"}:
        payload["model_sha256"] = artifact_digest(payload)
    with pytest.raises(ValueError):
        PortableTextRanker.from_dict(payload)


@pytest.mark.parametrize(
    "documents", [[], [""], [" "], ["a" * (MAX_TEXT_CHARACTERS + 1)], "one string", [None]]
)
def test_untrusted_text_inputs_are_bounded(documents):
    with pytest.raises(ValueError):
        TextFeatureIndex(documents)


def test_feature_values_cannot_bypass_numeric_contract():
    for value in (True, -1.0, 1.1, float("nan"), float("inf")):
        row = [0.0] * len(FEATURE_NAMES)
        row[0] = value
        with pytest.raises(ValueError):
            model().score_features([row])
