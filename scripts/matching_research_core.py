"""Offline synthetic-relevance experiments; never imported by the live matcher.

The published match IDs are a random, capped subset of skill-qualified resumes.
Their absence is therefore not a negative label. This module samples negatives
only below the published generator's threshold and returns uncalibrated logits.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

FEATURE_NAMES = (
    "required_skill_coverage",
    "preferred_skill_coverage",
    "preferred_skills_present",
    "seniority_match",
    "text_token_jaccard",
)


def normalize_generator_skill(value: str) -> str:
    """Match the dataset notebook's normalization, without inventing aliases."""
    if not isinstance(value, str):
        raise ValueError("Skill and text values must be strings.")
    value = re.sub(r"[^a-z0-9\+\#\.\-\/\s]", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings.")
    return list(value)


def _skills(value: Any, name: str) -> set[str]:
    return {normalized for item in _strings(value, name) if (normalized := normalize_generator_skill(item))}


def _tokens(row: dict, fields: tuple[str, ...], list_field: str) -> set[str]:
    texts = [row.get(field, "") for field in fields]
    texts.extend(_strings(row.get(list_field, []), list_field))
    if any(not isinstance(item, str) for item in texts):
        raise ValueError("Text fields must be strings.")
    return set(normalize_generator_skill(" ".join(texts)).split())


class PreparedCorpus:
    """Precompute resume fields in a stable ID order for repeated job scoring."""

    def __init__(self, rows: list[dict]):
        if any(not isinstance(row.get("resume_id"), str) or not row["resume_id"] for row in rows):
            raise ValueError("Every resume must have a nonempty string resume_id.")
        self.rows = sorted(rows, key=lambda row: row["resume_id"])
        self.ids = [row["resume_id"] for row in self.rows]
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("Duplicate resume IDs are not allowed.")
        self.skill_sets = [_skills(row.get("skills", []), "skills") for row in self.rows]
        self._text_sets = [_tokens(row, ("role", "summary"), "experience_bullets") for row in self.rows]
        self._seniorities = [normalize_generator_skill(row.get("seniority", "")) for row in self.rows]


def feature_matrix(job: dict, corpus: PreparedCorpus) -> np.ndarray:
    """Return Nx5 normalized features; an absent preference is explicit."""
    required = _skills(job.get("must_have_skills", []), "must_have_skills")
    preferred = _skills(job.get("nice_to_have_skills", []), "nice_to_have_skills")
    seniority = normalize_generator_skill(job.get("seniority", ""))
    text = _tokens(job, ("job_title", "description"), "responsibilities")
    matrix = np.zeros((len(corpus.ids), len(FEATURE_NAMES)), dtype=float)
    for index, skills in enumerate(corpus.skill_sets):
        matrix[index, 0] = len(required & skills) / len(required) if required else 1
        matrix[index, 1] = len(preferred & skills) / len(preferred) if preferred else 0
        matrix[index, 2] = bool(preferred)
        matrix[index, 3] = bool(seniority) and seniority == corpus._seniorities[index]
        resume_text = corpus._text_sets[index]
        union = text | resume_text
        matrix[index, 4] = len(text & resume_text) / len(union) if union else 0
    return matrix


def _digest(seed: int, value: Any) -> bytes:
    serialized = json.dumps([seed, value], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).digest()


def _partition(seed: int, value: Any) -> str:
    bucket = int.from_bytes(_digest(seed, value), "big") % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def split_jobs(jobs: list[dict], seed: int) -> dict[str, list[dict]]:
    """Keep duplicate structured job templates together in a 70/15/15 split."""
    partitions: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}
    for job in sorted(jobs, key=lambda row: row["job_id"]):
        template = (
            normalize_generator_skill(job.get("job_title", "")),
            normalize_generator_skill(job.get("seniority", "")),
            sorted(_skills(job.get("must_have_skills", []), "must_have_skills")),
            sorted(_skills(job.get("nice_to_have_skills", []), "nice_to_have_skills")),
        )
        partitions[_partition(seed, template)].append(job)
    return partitions


def resume_split(resume: dict, seed: int) -> str:
    """Stable resume-ID holdout; the caller separately checks content overlap."""
    return _partition(seed, resume["resume_id"])


def sample_training_indices(
    job: dict,
    corpus: PreparedCorpus,
    positives: set[str],
    seed: int,
    per_class: int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample listed positives and confirmed synthetic-threshold negatives.

    Qualifying but unlisted resumes stay unlabeled. Return empty arrays when a
    balanced sample cannot be formed, so callers can skip such a job.
    """
    if not isinstance(per_class, int) or isinstance(per_class, bool) or per_class < 1:
        raise ValueError("per_class must be a positive integer.")
    missing = positives - set(corpus.ids)
    if missing:
        raise ValueError(f"Listed positive resume IDs are absent: {sorted(missing)}")
    required = feature_matrix(job, corpus)[:, 0]
    positive_indices = np.asarray(
        [index for index, resume_id in enumerate(corpus.ids) if resume_id in positives],
        dtype=int,
    )
    if np.any(required[positive_indices] < 0.6):
        raise ValueError("A listed positive is below the generator's 60% threshold.")
    negative_indices = np.flatnonzero(required < 0.6)
    count = min(per_class, len(positive_indices), len(negative_indices))
    if not count:
        return np.empty(0, dtype=int), np.empty(0, dtype=float)
    rng = np.random.default_rng(int.from_bytes(_digest(seed, job["job_id"])[:8], "big"))
    indices = np.concatenate(
        (
            rng.choice(positive_indices, size=count, replace=False),
            rng.choice(negative_indices, size=count, replace=False),
        )
    )
    labels = np.concatenate((np.ones(count), np.zeros(count)))
    permutation = rng.permutation(len(indices))
    return indices[permutation], labels[permutation]


def _matrix(value: Any) -> np.ndarray:
    matrix = np.asarray(value, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_NAMES):
        raise ValueError(f"Expected a two-dimensional matrix with {len(FEATURE_NAMES)} features.")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("Features must be finite.")
    if np.any((matrix < 0) | (matrix > 1)):
        raise ValueError("Features must be normalized to [0, 1].")
    return matrix


@dataclass
class LogisticModel:
    weights: list[float]
    bias: float
    initial_loss: float | None = None
    final_loss: float | None = None

    def scores(self, x: np.ndarray) -> np.ndarray:
        """Raw logits used only to rank synthetic relevance, not probabilities."""
        matrix = _matrix(x)
        weights = np.asarray(self.weights, dtype=float)
        if weights.shape != (len(FEATURE_NAMES),) or not np.all(np.isfinite(weights)):
            raise ValueError("Model weights must contain five finite values.")
        if not np.isfinite(self.bias):
            raise ValueError("Model bias must be finite.")
        return matrix @ weights + self.bias

    def to_dict(self) -> dict:
        return {
            "model_type": "numpy_logistic_regression",
            "feature_names": list(FEATURE_NAMES),
            "weights": [float(weight) for weight in self.weights],
            "bias": float(self.bias),
            "target": "synthetic_relevance",
            "output": "uncalibrated_logit",
            "calibration": None,
            "initial_loss": self.initial_loss,
            "final_loss": self.final_loss,
        }


def fit_logistic(
    x: np.ndarray,
    y: np.ndarray,
    l2: float = 0.01,
    epochs: int = 500,
) -> LogisticModel:
    """Fit a small, deterministic L2-regularized offline ranking baseline."""
    matrix = _matrix(x)
    labels = np.asarray(y, dtype=float)
    if labels.ndim != 1 or len(labels) != len(matrix) or not len(labels):
        raise ValueError("Labels must be a nonempty vector matching the feature rows.")
    if not np.all(np.isfinite(labels)) or set(np.unique(labels)) != {0.0, 1.0}:
        raise ValueError("Binary labels must contain both 0 and 1.")
    if not np.isfinite(l2) or l2 < 0:
        raise ValueError("l2 must be a finite nonnegative number.")
    if not isinstance(epochs, int) or isinstance(epochs, bool) or epochs < 1:
        raise ValueError("epochs must be a positive integer.")
    weights = np.zeros(len(FEATURE_NAMES), dtype=float)
    bias = 0.0

    def loss() -> float:
        logits = matrix @ weights + bias
        return float(np.mean(np.logaddexp(0, logits) - labels * logits) + l2 * (weights @ weights) / 2)

    initial_loss = loss()
    # An augmented row has squared norm <= 6, giving a safe fixed step size.
    learning_rate = 0.5 / (1 + l2)
    for _ in range(epochs):
        logits = matrix @ weights + bias
        predictions = np.empty_like(logits)
        nonnegative = logits >= 0
        predictions[nonnegative] = 1 / (1 + np.exp(-logits[nonnegative]))
        negative_exp = np.exp(logits[~nonnegative])
        predictions[~nonnegative] = negative_exp / (1 + negative_exp)
        residual = predictions - labels
        weights -= learning_rate * (matrix.T @ residual / len(labels) + l2 * weights)
        bias -= learning_rate * float(np.mean(residual))
    return LogisticModel(weights.tolist(), float(bias), initial_loss, loss())


def ranking_metrics(
    scores: np.ndarray,
    corpus: PreparedCorpus,
    positive_ids: set[str],
    qualifies: np.ndarray,
    k: int = 30,
) -> dict:
    """Report incomplete-label recall separately from synthetic qualification."""
    values = np.asarray(scores, dtype=float)
    qualified = np.asarray(qualifies)
    if values.ndim != 1 or len(values) != len(corpus.ids) or not np.all(np.isfinite(values)):
        raise ValueError("Scores must be a finite vector matching the corpus.")
    if qualified.ndim != 1 or len(qualified) != len(corpus.ids):
        raise ValueError("Qualifications must be a vector matching the corpus.")
    if not np.all(np.isin(qualified, [False, True])):
        raise ValueError("Qualifications must be boolean values.")
    qualified = qualified.astype(bool)
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer.")
    # Resume holdouts deliberately exclude some listed IDs. Recall is conditional
    # on this retrieval corpus; report its relevant-label denominator explicitly.
    positive_ids = positive_ids & set(corpus.ids)
    order = np.lexsort((np.asarray(corpus.ids, dtype=str), -values))[:k]
    recommendations = [corpus.ids[index] for index in order]
    qualifying_count = int(np.count_nonzero(qualified))
    return {
        "listed_recall_at_k": (
            len(set(recommendations) & positive_ids) / len(positive_ids) if positive_ids else None
        ),
        "threshold_precision_at_k": (float(np.mean(qualified[order])) if len(order) else None),
        "qualifying_count": qualifying_count,
        "listed_positive_count": len(positive_ids),
        "expected_listed_recall_for_qualified_only_ranker": (
            min(k, qualifying_count) / qualifying_count if qualifying_count else None
        ),
        "recommended_ids": recommendations,
    }
