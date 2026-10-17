"""Small deterministic evaluation helpers; no synthetic benchmark success claims."""

from dataclasses import dataclass
from datetime import datetime
from math import log

from .types import aware, probability


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
        aware(self.observed_at, "observed_at")
        aware(self.feature_as_of, "feature_as_of")
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
