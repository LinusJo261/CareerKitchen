"""Strict, dependency-free inference for versioned observed-outcome models.

Models estimate explicit resolution among historically issued introductions.
They do not certify hiring, infer consent, or change hard eligibility.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from json import dumps
from math import exp, isfinite

from .reciprocal import ReciprocalFeatures

FEATURE_NAMES = ("employer_skills", "candidate_role", "candidate_work_mode", "candidate_employment_type")
TARGET = "mutual_opt_in_within_horizon"
POPULATION = "eligible_issued_introductions_with_explicit_resolution_within_horizon"


def artifact_hash(artifact: dict) -> str:
    return sha256(
        dumps(
            {k: v for k, v in artifact.items() if k != "model_id"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _number(value: object, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("model numbers must be finite")
    if not lower <= value <= upper:
        raise ValueError("model number outside declared bounds")
    return float(value)


@dataclass(frozen=True, slots=True)
class LearnedModel:
    model_id: str
    transforms: tuple[tuple[float, float, float], ...]
    coefficients: tuple[float, ...]
    intercept: float
    calibration_slope: float
    calibration_intercept: float
    horizon_days: int
    exported_at: datetime
    fictional_data: bool

    def predict_values(self, values: dict) -> float:
        if set(values) != set(FEATURE_NAMES):
            raise ValueError("model input must contain exactly the four declared features")
        logit = self.intercept
        known = False
        for index, name in enumerate(FEATURE_NAMES):
            median, center, scale = self.transforms[index]
            missing = values[name] is None
            value = median if missing else _number(values[name], 0, 1)
            known = known or not missing
            logit += self.coefficients[2 * index] * (value - center) / scale
            logit += self.coefficients[2 * index + 1] * int(missing)
        if not known:
            raise ValueError("all model inputs unknown")
        logit = self.calibration_slope * logit + self.calibration_intercept
        # Stable sigmoid in both tails, without loading numerical/model libraries.
        if logit >= 0:
            return 1 / (1 + exp(-logit))
        tail = exp(logit)
        return tail / (1 + tail)

    def predict(self, features: ReciprocalFeatures) -> float:
        if not features.eligible:
            raise ValueError("hard eligibility must pass before learned scoring")
        as_of = datetime.fromisoformat(features.as_of.replace("Z", "+00:00"))
        if as_of < self.exported_at:
            raise ValueError("model unavailable at feature observation time")
        return self.predict_values({name: getattr(features, name) for name in FEATURE_NAMES})


def apply_learned_score(
    trace: dict, features: ReciprocalFeatures, model: LearnedModel | None, fallback_reason: str
) -> dict:
    """Use a qualified conditional estimate as ranking utility, retaining cold start evidence.

    Attention costs and hard gates are unchanged. The prediction concerns the
    explicit-resolution historical population, not hiring or unexposed pairs.
    """
    result = dict(trace)
    if model is None:
        result["learning"] = {"active": False, "reason_code": fallback_reason}
        return result
    try:
        utility = model.predict(features)
    except (ValueError, TypeError, OverflowError):
        result["learning"] = {"active": False, "reason_code": "INVALID_INPUT_DETERMINISTIC_FALLBACK"}
        return result
    result["deterministic_relevance"] = trace["relevance"]
    result["relevance"] = utility
    for direction in ("candidate_first", "employer_first"):
        original = trace[direction]
        result[direction] = {
            **original,
            "gross_value": utility,
            "net_surplus": utility - original["attention_cost"] - original["congestion_cost"],
        }
    best = max((result["candidate_first"], result["employer_first"]), key=lambda item: item["net_surplus"])
    result.update(
        model_version=f"ml-v2:{model.model_id}",
        estimate_kind="CONDITIONAL_OBSERVED_RESOLUTION_RANKING",
        weights_version=model.model_id,
        net_surplus=best["net_surplus"],
        first_mover=str(best["side"]),
        learning={
            "active": True,
            "model_id": model.model_id,
            "target": TARGET,
            "estimation_population": POPULATION,
            "horizon_days": model.horizon_days,
        },
    )
    result["reason_codes"] = [*trace["reason_codes"], "QUALIFIED_OBSERVED_OUTCOME_RANKING"]
    return result


def validate_artifact(artifact: dict, *, require_eligible: bool = True) -> LearnedModel:
    """Validate bounded JSON parameters, provenance and deployment evidence.

    The registry additionally verifies the matching evaluation report. A hash is
    an integrity check, not independent proof of outcome provenance or reliability.
    """
    expected = {
        "schema_version",
        "artifact_kind",
        "target",
        "estimation_population",
        "feature_version",
        "feature_names",
        "transforms",
        "coefficients",
        "intercept",
        "calibration",
        "decision_threshold",
        "horizon_days",
        "fictional_data",
        "source",
        "provenance",
        "evidence",
        "model_id",
    }
    if not isinstance(artifact, dict) or set(artifact) != expected:
        raise ValueError("invalid learned model schema")
    if type(artifact["schema_version"]) is not int or artifact["schema_version"] != 2:
        raise ValueError("unsupported learned model schema version")
    if (
        artifact["artifact_kind"] != "reciprocal_logistic_challenger"
        or artifact["target"] != TARGET
        or artifact["estimation_population"] != POPULATION
        or artifact["feature_version"] != "reciprocal-structured-v1"
        or artifact["feature_names"] != list(FEATURE_NAMES)
    ):
        raise ValueError("model target or features do not match routing contract")
    if not isinstance(artifact["model_id"], str) or artifact_hash(artifact) != artifact["model_id"]:
        raise ValueError("model integrity hash mismatch")
    if type(artifact["fictional_data"]) is not bool:
        raise ValueError("fictional_data must be explicit boolean")
    source, evidence, provenance = artifact["source"], artifact["evidence"], artifact["provenance"]
    if not isinstance(source, dict) or not isinstance(evidence, dict) or not isinstance(provenance, dict):
        raise ValueError("model source, evidence and provenance required")
    if set(source) != {"kind", "dataset", "source_version", "exported_at"}:
        raise ValueError("invalid model source schema")
    if any(not isinstance(source[key], str) or not source[key].strip() for key in source):
        raise ValueError("model source values must be nonempty strings")
    if source["kind"] not in {"fictional_fixture", "observed_introduction_outcomes"}:
        raise ValueError("unsupported model outcome source")
    if artifact["fictional_data"] != (source["kind"] == "fictional_fixture"):
        raise ValueError("fictional model provenance mismatch")
    if require_eligible and (
        artifact["fictional_data"]
        or source.get("kind") != "observed_introduction_outcomes"
        or evidence.get("eligible_for_review") is not True
        or evidence.get("reasons") != []
    ):
        raise ValueError("model has not passed observed-outcome evaluation gates")
    for key in ("input_sha256", "manifest_sha256", "test_cohort_sha256"):
        value = provenance.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid model source fingerprint")
    exported = datetime.fromisoformat(str(source.get("exported_at", "")).replace("Z", "+00:00"))
    if exported.tzinfo is None or exported.utcoffset() is None:
        raise ValueError("model export timestamp must include timezone")
    horizon = artifact["horizon_days"]
    if type(horizon) is not int or not 1 <= horizon <= 365:
        raise ValueError("invalid model outcome horizon")
    raw_transforms, raw_weights = artifact["transforms"], artifact["coefficients"]
    if not isinstance(raw_transforms, list) or len(raw_transforms) != 4:
        raise ValueError("four feature transforms required")
    transforms = []
    for value in raw_transforms:
        if not isinstance(value, dict) or set(value) != {"imputation_median", "center", "scale"}:
            raise ValueError("invalid model feature transform")
        transforms.append(
            (
                _number(value["imputation_median"], 0, 1),
                _number(value["center"], 0, 1),
                _number(value["scale"], 0.000001, 1),
            )
        )
    if not isinstance(raw_weights, list) or len(raw_weights) != 8:
        raise ValueError("eight model coefficients required")
    calibration = artifact["calibration"]
    if not isinstance(calibration, dict) or set(calibration) != {"kind", "slope", "intercept"}:
        raise ValueError("invalid model calibration")
    if not isinstance(calibration["kind"], str) or calibration["kind"] not in {"identity", "platt"}:
        raise ValueError("unsupported model calibration")
    slope = _number(calibration["slope"], 0.000001, 1000)
    calibration_intercept = _number(calibration["intercept"], -1000, 1000)
    if calibration["kind"] == "identity" and (slope != 1 or calibration_intercept != 0):
        raise ValueError("identity calibration must preserve logits")
    _number(artifact["decision_threshold"], 0, 1)
    return LearnedModel(
        artifact["model_id"],
        tuple(transforms),
        tuple(_number(w, -1000, 1000) for w in raw_weights),
        _number(artifact["intercept"], -1000, 1000),
        slope,
        calibration_intercept,
        horizon,
        exported,
        artifact["fictional_data"],
    )
