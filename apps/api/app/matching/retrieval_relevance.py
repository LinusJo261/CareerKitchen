"""Portable public-positive retrieval inference; offline research only.

This distinct target cannot be loaded as an observed-outcome or ordinal model.
Inference is standard-library only; fitting lives in the research scripts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.matching.text_relevance import FEATURE_NAMES, FEATURE_VERSION, TextFeatureIndex, artifact_digest

MODEL_SCHEMA = "public-positive-listwise-retrieval-v1"
MODEL_TARGET = "PUBLIC_PUBLISHED_POSITIVE_RETRIEVAL"


@dataclass(frozen=True)
class PortableRetrievalRanker:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    regularization: float
    source_sha256: str
    training_job_clusters: int
    training_positive_judgments: int
    candidate_corpus_size: int

    def __post_init__(self) -> None:
        for values in (self.means, self.scales, self.coefficients):
            if (
                not isinstance(values, tuple)
                or len(values) != len(FEATURE_NAMES)
                or any(
                    isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value)
                    for value in values
                )
            ):
                raise ValueError("One finite numeric parameter per fixed feature is required.")
        if any(not 0 <= value <= 1 for value in self.means):
            raise ValueError("Feature means must be bounded.")
        if any(not 1e-8 <= value <= 1e4 for value in self.scales) or any(
            abs(value) > 1e4 for value in self.coefficients
        ):
            raise ValueError("Invalid model scaling or coefficient bounds.")
        if (
            isinstance(self.regularization, bool)
            or not isinstance(self.regularization, (int, float))
            or not math.isfinite(self.regularization)
            or not 0 < self.regularization <= 1e6
        ):
            raise ValueError("A finite bounded positive regularization is required.")
        if not isinstance(self.source_sha256, str) or not re.fullmatch("[0-9a-f]{64}", self.source_sha256):
            raise ValueError("Pinned source SHA256 is required.")
        if (
            any(
                type(value) is not int or not 1 <= value <= 10_000_000
                for value in (
                    self.training_job_clusters,
                    self.training_positive_judgments,
                    self.candidate_corpus_size,
                )
            )
            or self.training_positive_judgments > self.training_job_clusters * self.candidate_corpus_size
        ):
            raise ValueError("Invalid aggregate training geometry.")

    def score_features(self, rows: Sequence[Sequence[float]]) -> tuple[float, ...]:
        scores = []
        for row in rows:
            if len(row) != len(FEATURE_NAMES) or any(
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in row
            ):
                raise ValueError("One finite bounded value per feature is required.")
            scores.append(
                math.fsum(
                    (value - mean) / scale * coefficient
                    for value, mean, scale, coefficient in zip(
                        row, self.means, self.scales, self.coefficients, strict=True
                    )
                )
            )
        return tuple(scores)

    def score(self, query: str, documents: Sequence[str]) -> tuple[float, ...]:
        return self.score_features(TextFeatureIndex(documents).features(query))

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema": MODEL_SCHEMA,
            "target": MODEL_TARGET,
            "scope": "OFFLINE_RESEARCH_ONLY",
            "production_eligible": False,
            "feature_version": FEATURE_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "means": list(self.means),
            "scales": list(self.scales),
            "coefficients": list(self.coefficients),
            "regularization": self.regularization,
            "source_sha256": self.source_sha256,
            "training_job_clusters": self.training_job_clusters,
            "training_positive_judgments": self.training_positive_judgments,
            "candidate_corpus_size": self.candidate_corpus_size,
        }
        value["model_sha256"] = artifact_digest(value)
        return value

    @classmethod
    def from_dict(cls, value: Any) -> PortableRetrievalRanker:
        expected = {
            "schema",
            "target",
            "scope",
            "production_eligible",
            "feature_version",
            "feature_names",
            "means",
            "scales",
            "coefficients",
            "regularization",
            "source_sha256",
            "training_job_clusters",
            "training_positive_judgments",
            "candidate_corpus_size",
            "model_sha256",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Unexpected retrieval artifact schema.")
        if (
            value["schema"] != MODEL_SCHEMA
            or value["target"] != MODEL_TARGET
            or value["scope"] != "OFFLINE_RESEARCH_ONLY"
            or value["production_eligible"] is not False
            or value["feature_version"] != FEATURE_VERSION
            or value["feature_names"] != list(FEATURE_NAMES)
            or value["model_sha256"] != artifact_digest(value)
            or any(not isinstance(value[key], list) for key in ("means", "scales", "coefficients"))
        ):
            raise ValueError("Invalid retrieval artifact target, scope or integrity.")
        return cls(
            means=tuple(value["means"]),
            scales=tuple(value["scales"]),
            coefficients=tuple(value["coefficients"]),
            regularization=value["regularization"],
            source_sha256=value["source_sha256"],
            training_job_clusters=value["training_job_clusters"],
            training_positive_judgments=value["training_positive_judgments"],
            candidate_corpus_size=value["candidate_corpus_size"],
        )
