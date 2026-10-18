"""Small deterministic evaluation helpers; no synthetic benchmark success claims."""

from dataclasses import dataclass
from datetime import datetime
from math import log

from .types import aware, boolean, probability

OBSERVATION_TARGETS = frozenset({"OFFER_ACCEPTANCE", "VERIFIED_START"})


@dataclass(frozen=True, slots=True)
class Observation:
    observed_at: datetime
    feature_as_of: datetime
    earliest_stage: str
    predicted_probability: float
    outcome: bool
    target: str
    independently_verified_start: bool = False

    def __post_init__(self) -> None:
        for name in ("observed_at", "feature_as_of"):
            if not isinstance(getattr(self, name), datetime):
                raise ValueError(f"{name} must be a timezone-aware datetime")
        aware(self.observed_at, "observed_at")
        aware(self.feature_as_of, "feature_as_of")
        boolean(self.outcome, "outcome")
        boolean(self.independently_verified_start, "independently_verified_start")
        if not isinstance(self.target, str) or self.target not in OBSERVATION_TARGETS:
            raise ValueError("unsupported observation target")
        if not isinstance(self.earliest_stage, str) or not self.earliest_stage.strip():
            raise ValueError("earliest stage is required")
        if isinstance(self.predicted_probability, bool) or not isinstance(
            self.predicted_probability, (int, float)
        ):
            raise ValueError("predicted_probability must be numeric, not boolean")
        probability(self.predicted_probability, "predicted_probability")
        if self.feature_as_of > self.observed_at:
            raise ValueError("future feature leakage")
        if self.target == "VERIFIED_START" and self.outcome and not self.independently_verified_start:
            raise ValueError("offer acceptance is not a verified employment start")


def temporal_split(records: tuple[Observation, ...], train_end: datetime, calibration_end: datetime):
    aware(train_end, "train_end")
    aware(calibration_end, "calibration_end")
    if train_end >= calibration_end:
        raise ValueError("strictly ordered temporal cutoffs required")
    usable = tuple(
        sorted(
            (item for item in records if item.earliest_stage == "PRE_INTRODUCTION"),
            key=lambda item: item.observed_at,
        )
    )
    return (
        tuple(item for item in usable if item.observed_at < train_end),
        tuple(item for item in usable if train_end <= item.observed_at < calibration_end),
        tuple(item for item in usable if item.observed_at >= calibration_end),
    )


def probability_metrics(records: tuple[Observation, ...]) -> dict[str, float | int]:
    if not records:
        return {"count": 0}
    if len({item.target for item in records}) != 1:
        raise ValueError("probability metrics require a single observation target")
    brier = sum((item.predicted_probability - int(item.outcome)) ** 2 for item in records) / len(records)
    epsilon = 1e-15
    loss = sum(
        -(
            int(item.outcome) * log(max(epsilon, item.predicted_probability))
            + (1 - int(item.outcome)) * log(max(epsilon, 1 - item.predicted_probability))
        )
        for item in records
    ) / len(records)
    return {"count": len(records), "brier": brier, "log_loss": loss}
