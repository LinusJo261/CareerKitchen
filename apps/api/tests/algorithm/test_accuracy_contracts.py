"""Adversarial evidence-contract checks, using explicitly fictional observations."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import exp, isfinite

import pytest
from app.matching.attention import MarketPrices
from app.matching.calibration import Observation, probability_metrics
from app.matching.learning import FEATURE_NAMES, POPULATION, TARGET, artifact_hash, validate_artifact
from app.matching.reciprocal import ReciprocalFeatures, score_reciprocal

NOW = datetime(2026, 10, 18, tzinfo=UTC)
FEATURES = ReciprocalFeatures("fictional-c", "fictional-v", 1, 1, NOW.isoformat(), 1, 1, 1, 1, True)
OBSERVATION = Observation(NOW, NOW - timedelta(days=1), "PRE_INTRODUCTION", 0.8, True, "OFFER_ACCEPTANCE")


@pytest.mark.parametrize("invalid", [0, 1, 2, -1, "false", None])
def test_outcome_cannot_be_truthy_or_nonbinary(invalid):
    with pytest.raises(ValueError, match="boolean"):
        replace(OBSERVATION, outcome=invalid)


@pytest.mark.parametrize("invalid", [0, 1, "yes", None])
def test_verification_flag_must_be_an_explicit_boolean(invalid):
    with pytest.raises(ValueError, match="boolean"):
        replace(OBSERVATION, independently_verified_start=invalid)


@pytest.mark.parametrize("invalid", [True, False, "0.8", None, float("inf"), float("nan"), -0.1, 1.1])
def test_prediction_must_be_a_finite_numeric_probability(invalid):
    with pytest.raises(ValueError):
        replace(OBSERVATION, predicted_probability=invalid)


def test_metrics_do_not_mix_offer_acceptance_with_verified_start():
    verified = replace(OBSERVATION, target="VERIFIED_START", independently_verified_start=True)
    with pytest.raises(ValueError, match="single observation target"):
        probability_metrics((OBSERVATION, verified))
    with pytest.raises(ValueError, match="unsupported"):
        replace(OBSERVATION, target="UNDECLARED")


@pytest.mark.parametrize("invalid", [None, 1, [], {}])
def test_observation_target_must_be_a_supported_string(invalid):
    with pytest.raises(ValueError, match="unsupported"):
        replace(OBSERVATION, target=invalid)


def test_valid_binary_metrics_are_bounded_and_nonnegative_at_probability_endpoints():
    records = tuple(
        replace(OBSERVATION, predicted_probability=probability, outcome=outcome)
        for probability, outcome in ((0, True), (1, False), (0, False), (1, True))
    )
    metrics = probability_metrics(records)
    assert metrics["count"] == 4
    assert metrics["brier"] == 0.5
    assert metrics["log_loss"] > 0
    assert all(isfinite(value) for value in metrics.values())


@pytest.mark.parametrize("field", ["candidate_id", "vacancy_id"])
@pytest.mark.parametrize("invalid", ["", "   ", 1, None])
def test_scoring_snapshot_requires_nonempty_string_ids(field, invalid):
    with pytest.raises(ValueError, match="nonempty ID"):
        replace(FEATURES, **{field: invalid})


@pytest.mark.parametrize("field", ["candidate_version", "vacancy_version"])
@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, "1", None])
def test_scoring_snapshot_requires_positive_integer_versions(field, invalid):
    with pytest.raises(ValueError, match="positive integer"):
        replace(FEATURES, **{field: invalid})


@pytest.mark.parametrize("invalid", ["not-time", "2026-10-18", "2026-10-18T12:00:00", "", None, NOW])
def test_scoring_snapshot_requires_a_timezone_aware_iso_time(invalid):
    with pytest.raises(ValueError):
        replace(FEATURES, as_of=invalid)


@pytest.mark.parametrize(
    "field", ["employer_skills", "candidate_role", "candidate_work_mode", "candidate_employment_type"]
)
@pytest.mark.parametrize("invalid", [True, "1", float("inf"), float("nan"), -0.1, 1.1])
def test_fit_inputs_reject_coercion_and_invalid_numbers(field, invalid):
    with pytest.raises(ValueError):
        replace(FEATURES, **{field: invalid})


@pytest.mark.parametrize("field", ["candidate_role", "candidate_work_mode", "candidate_employment_type"])
def test_required_candidate_compatibilities_cannot_be_missing(field):
    with pytest.raises(ValueError):
        replace(FEATURES, **{field: None})


def test_optional_employer_skills_remain_unknown_and_valid_snapshots_replay():
    features = replace(FEATURES, employer_skills=None, as_of="2026-10-18T00:00:00Z")
    score = score_reciprocal(features, MarketPrices())
    assert score["features"]["employer_skills"] is None
    assert score == score_reciprocal(features, MarketPrices())


def test_finite_individual_prices_cannot_produce_nonfinite_score_trace():
    with pytest.raises(ValueError, match="arithmetic must remain finite"):
        score_reciprocal(FEATURES, MarketPrices(mu_candidate=1e308, job_congestion=1e308))


def fictional_artifact():
    artifact = {
        "schema_version": 2,
        "artifact_kind": "reciprocal_logistic_challenger",
        "target": TARGET,
        "estimation_population": POPULATION,
        "feature_version": "reciprocal-structured-v1",
        "feature_names": list(FEATURE_NAMES),
        "transforms": [{"imputation_median": 0.5, "center": 0.5, "scale": 0.5} for _ in range(4)],
        "coefficients": [1, 0] * 4,
        "intercept": 0,
        "calibration": {"kind": "identity", "slope": 1, "intercept": 0},
        "decision_threshold": 0.5,
        "horizon_days": 14,
        "fictional_data": True,
        "source": {
            "kind": "fictional_fixture",
            "dataset": "fictional-contract-test",
            "source_version": "fictional-v1",
            "exported_at": "2026-10-17T00:00:00Z",
        },
        "provenance": {name: "0" * 64 for name in ("input_sha256", "manifest_sha256", "test_cohort_sha256")},
        "evidence": {"eligible_for_review": False, "reasons": ["FICTIONAL_FIXTURE"]},
    }
    artifact["model_id"] = artifact_hash(artifact)
    return artifact


def rehash_artifact(artifact):
    result = deepcopy(artifact)
    result["model_id"] = artifact_hash(result)
    return result


def test_independent_runtime_formula_replays_numeric_logistic_fixture():
    model = validate_artifact(fictional_artifact(), require_eligible=False)
    assert model.predict(FEATURES) == pytest.approx(1 / (1 + exp(-4)))
    assert model.predict(replace(FEATURES, employer_skills=None)) == pytest.approx(1 / (1 + exp(-3)))


def test_fictional_models_cannot_pass_activation_validation_even_with_rehashed_evidence():
    artifact = fictional_artifact()
    artifact["evidence"] = {"eligible_for_review": True, "reasons": []}
    with pytest.raises(ValueError, match="observed-outcome"):
        validate_artifact(rehash_artifact(artifact))


def test_model_integrity_is_checked_before_inference():
    artifact = fictional_artifact()
    artifact["intercept"] = 1
    with pytest.raises(ValueError, match="integrity"):
        validate_artifact(artifact, require_eligible=False)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema_version", True),
        ("target", "VERIFIED_START"),
        ("estimation_population", "all_eligible_pairs"),
        ("feature_version", "unknown"),
        ("feature_names", list(reversed(FEATURE_NAMES))),
        ("coefficients", [1] * 4),
        ("coefficients", [True] * 8),
        ("intercept", 1001),
        ("decision_threshold", -0.1),
        ("horizon_days", True),
        ("horizon_days", 0),
        ("horizon_days", 366),
        ("fictional_data", 1),
    ],
)
def test_rehashed_incompatible_or_malformed_artifacts_still_fail(field, invalid):
    artifact = fictional_artifact()
    artifact[field] = invalid
    with pytest.raises(ValueError):
        validate_artifact(rehash_artifact(artifact), require_eligible=False)


def test_unknown_artifact_fields_are_rejected_even_with_valid_hash():
    artifact = fictional_artifact()
    artifact["python_code"] = "fictional executable payload must never be accepted"
    with pytest.raises(ValueError, match="schema"):
        validate_artifact(rehash_artifact(artifact), require_eligible=False)


@pytest.mark.parametrize("field", ["imputation_median", "center", "scale"])
def test_preprocessing_bounds_cannot_be_bypassed_by_valid_integrity_hash(field):
    artifact = fictional_artifact()
    artifact["transforms"][0][field] = -1
    with pytest.raises(ValueError, match="bounds"):
        validate_artifact(rehash_artifact(artifact), require_eligible=False)


def test_identity_calibration_cannot_secretly_change_probability():
    artifact = fictional_artifact()
    artifact["calibration"]["slope"] = 2
    with pytest.raises(ValueError, match="identity"):
        validate_artifact(rehash_artifact(artifact), require_eligible=False)


def test_malformed_calibration_kind_raises_contract_error():
    artifact = fictional_artifact()
    artifact["calibration"]["kind"] = {}
    with pytest.raises(ValueError):
        validate_artifact(rehash_artifact(artifact), require_eligible=False)


@pytest.mark.parametrize(("field", "invalid"), [("kind", {}), ("dataset", None), ("source_version", " ")])
def test_source_provenance_is_validated_even_for_offline_fictional_inference(field, invalid):
    artifact = fictional_artifact()
    artifact["source"][field] = invalid
    with pytest.raises(ValueError):
        validate_artifact(rehash_artifact(artifact), require_eligible=False)


def test_runtime_model_cannot_score_ineligible_or_pretraining_snapshot():
    model = validate_artifact(fictional_artifact(), require_eligible=False)
    with pytest.raises(ValueError, match="eligibility"):
        model.predict(replace(FEATURES, eligible=False))
    with pytest.raises(ValueError, match="unavailable"):
        model.predict(replace(FEATURES, as_of="2026-10-16T00:00:00Z"))


def test_runtime_rejects_missing_all_features_or_extra_undeclared_inputs():
    model = validate_artifact(fictional_artifact(), require_eligible=False)
    with pytest.raises(ValueError, match="unknown"):
        model.predict_values(dict.fromkeys(FEATURE_NAMES))
    values = dict.fromkeys(FEATURE_NAMES, 1)
    values["private_salary_floor"] = 0
    with pytest.raises(ValueError, match="exactly"):
        model.predict_values(values)
