"""Synthetic parameter fixtures check inference, never matching accuracy."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import exp

import pytest
from app.matching.attention import MarketPrices
from app.matching.learning import POPULATION, LearnedModel, apply_learned_score
from app.matching.reciprocal import ReciprocalFeatures, score_reciprocal

NOW = datetime(2026, 10, 18, tzinfo=UTC)
FEATURES = ReciprocalFeatures("fictional-c", "fictional-v", 1, 1, NOW.isoformat(), 0.75, 1, 1, 1, True)


def fixture_model(**changes):
    model = LearnedModel(
        "a" * 64,
        ((0.5, 0.5, 0.5),) * 4,
        (2, -1, 0, 0, 0, 0, 0, 0),
        -0.5,
        1,
        0,
        14,
        NOW - timedelta(days=1),
        True,
    )
    return replace(model, **changes)


def test_learned_utility_preserves_attention_prices_and_cold_start_evidence_without_mutation():
    prices = MarketPrices(mu_candidate=0.15, mu_employer=0.05, job_congestion=0.07, candidate_congestion=0.03)
    original = score_reciprocal(FEATURES, prices)
    frozen = deepcopy(original)
    model = fixture_model()
    scored = apply_learned_score(original, FEATURES, model, "unused")
    utility = model.predict(FEATURES)
    assert original == frozen
    assert scored["deterministic_relevance"] == original["relevance"]
    assert scored["relevance"] == utility
    assert scored["features"] == original["features"]
    assert scored["feature_hash"] == original["feature_hash"]
    assert scored["prices"] == original["prices"]
    assert scored["first_mover"] == "EMPLOYER"
    assert scored["model_version"] == "ml-v2:" + model.model_id
    assert scored["estimate_kind"] == "CONDITIONAL_OBSERVED_RESOLUTION_RANKING"
    assert scored["learning"]["estimation_population"] == POPULATION
    for direction in ("candidate_first", "employer_first"):
        assert scored[direction]["attention_cost"] == original[direction]["attention_cost"]
        assert scored[direction]["congestion_cost"] == original[direction]["congestion_cost"]
        assert scored[direction]["net_surplus"] == pytest.approx(
            utility - original[direction]["attention_cost"] - original[direction]["congestion_cost"]
        )
    assert scored["net_surplus"] == scored["employer_first"]["net_surplus"]


def test_missing_registry_model_preserves_deterministic_scoring_and_explains_fallback():
    original = score_reciprocal(FEATURES, MarketPrices())
    result = apply_learned_score(original, FEATURES, None, "NO_QUALIFIED_OBSERVED_MODEL")
    assert result.pop("learning") == {"active": False, "reason_code": "NO_QUALIFIED_OBSERVED_MODEL"}
    assert result == original


@pytest.mark.parametrize(
    "features",
    [replace(FEATURES, eligible=False), replace(FEATURES, as_of=(NOW - timedelta(days=2)).isoformat())],
)
def test_invalid_or_historically_unavailable_model_inputs_fall_back(features):
    original = score_reciprocal(FEATURES, MarketPrices())
    result = apply_learned_score(original, features, fixture_model(), "unused")
    assert result.pop("learning") == {"active": False, "reason_code": "INVALID_INPUT_DETERMINISTIC_FALLBACK"}
    assert result == original


def test_missing_optional_skill_uses_training_median_and_explicit_missing_indicator():
    model = fixture_model()
    features = replace(FEATURES, employer_skills=None)
    assert model.predict(features) == pytest.approx(1 / (1 + exp(1.5)))
    assert model.predict(features) != model.predict(replace(features, employer_skills=0.5))


@pytest.mark.parametrize("intercept,expected", [(-1000, 0), (1000, 1)])
def test_extreme_valid_logits_are_finite_and_bounded(intercept, expected):
    model = fixture_model(intercept=intercept, coefficients=(0,) * 8)
    assert model.predict(FEATURES) == expected
    result = apply_learned_score(score_reciprocal(FEATURES, MarketPrices()), FEATURES, model, "unused")
    assert result["relevance"] == expected


@pytest.mark.parametrize("invalid", [True, "0.5", float("nan"), float("inf"), -0.1, 1.1])
def test_prediction_rejects_invalid_values_even_when_called_without_snapshot_builder(invalid):
    values = {
        "employer_skills": invalid,
        "candidate_role": 1,
        "candidate_work_mode": 1,
        "candidate_employment_type": 1,
    }
    with pytest.raises(ValueError):
        fixture_model().predict_values(values)


def test_all_unknown_prediction_abstains_instead_of_returning_training_prevalence():
    with pytest.raises(ValueError, match="all model inputs unknown"):
        fixture_model().predict_values(
            dict.fromkeys(
                ("employer_skills", "candidate_role", "candidate_work_mode", "candidate_employment_type")
            )
        )
