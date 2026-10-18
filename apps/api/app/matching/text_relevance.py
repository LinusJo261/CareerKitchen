"""Portable, vocabulary-free text relevance inference for offline research.

The artifact target is human ordinal relevance, never mutual interest or hiring.
This module has no registry, database, network or pickle dependency. Loading an
artifact does not qualify it for production promotion or bypass any hard gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

FEATURE_VERSION = "bounded-lexical-multiview-v2"
MODEL_SCHEMA = "public-ordinal-pairwise-logistic-v1"
MODEL_TARGET = "PUBLIC_HUMAN_ORDINAL_RELEVANCE"
FEATURE_NAMES = (
    "normalized_bm25",
    "tfidf_cosine",
    "sublinear_tfidf_cosine",
    "token_jaccard",
    "query_token_coverage",
    "document_token_coverage",
    "query_idf_coverage",
    "document_idf_coverage",
    "bigram_jaccard",
    "query_bigram_coverage",
    "document_bigram_coverage",
    "bigram_tfidf_cosine",
    "character_3gram_tfidf_cosine",
    "character_4gram_tfidf_cosine",
    "character_5gram_tfidf_cosine",
)
MAX_TEXT_CHARACTERS = 200_000
MAX_CORPUS_CHARACTERS = 5_000_000
MAX_DOCUMENTS = 5_000


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _tokens(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARACTERS:
        raise ValueError("Text must be nonempty and within the research character limit.")
    # Contact addresses are not evidence of professional suitability. No person,
    # organization, ID, gender, age or ethnicity feature is engineered here.
    normalized = unicodedata.normalize("NFKC", text).casefold()
    # A word boundary would restart inside a long punctuation-separated local
    # part without '@', rescanning every suffix. Admit only its true beginning.
    normalized = re.sub(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|https?://\S+", " ", normalized)
    normalized = re.sub(r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)", " ", normalized)
    return re.findall(r"[^\W_]+(?:[+#]+)?(?:\.[^\W_]+)*", normalized)


def _bigrams(words: list[str]) -> Counter[str]:
    return Counter(left + "\x1f" + right for left, right in zip(words, words[1:], strict=False))


def _characters(words: list[str], size: int) -> Counter[str]:
    text = " ".join(words)
    return Counter(text[index : index + size] for index in range(max(0, len(text) - size + 1)))


def _idf(counters: Sequence[Counter[str]]) -> dict[str, float]:
    count = len(counters)
    frequency = Counter(token for counter in counters for token in counter)
    return {token: 1.0 + math.log((count + 1) / (value + 1)) for token, value in frequency.items()}


def _vector(counter: Counter[str], idf: dict[str, float], *, sublinear: bool = False) -> dict[str, float]:
    return {
        token: (1.0 + math.log(count) if sublinear else float(count)) * idf[token]
        for token, count in counter.items()
        if token in idf
    }


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    norm = math.sqrt(math.fsum(value * value for value in left.values())) * math.sqrt(
        math.fsum(value * value for value in right.values())
    )
    if not norm:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return min(
        1.0, max(0.0, math.fsum(value * right.get(token, 0.0) for token, value in left.items()) / norm)
    )


def _overlap(left: set[str], right: set[str]) -> tuple[float, float, float]:
    intersection = len(left & right)
    return (
        intersection / len(left | right) if left or right else 0.0,
        intersection / len(left) if left else 0.0,
        intersection / len(right) if right else 0.0,
    )


class TextFeatureIndex:
    """Label-free document statistics for the current retrieval candidate pool.

    IDF uses candidate documents only, including a held-out query's permitted
    retrieval pool. It is unsupervised indexing, not supervised training. Corpus
    dependence and query/document direction are part of this feature contract.
    """

    def __init__(self, documents: Sequence[str]) -> None:
        if isinstance(documents, (str, bytes)) or not 1 <= len(documents) <= MAX_DOCUMENTS:
            raise ValueError("A bounded nonempty document sequence is required.")
        if (
            any(not isinstance(text, str) for text in documents)
            or sum(map(len, documents)) > MAX_CORPUS_CHARACTERS
        ):
            raise ValueError("Document corpus exceeds the research character limit.")
        words = [_tokens(text) for text in documents]
        self.words = [Counter(value) for value in words]
        self.bigrams = [_bigrams(value) for value in words]
        self.characters = {size: [_characters(value, size) for value in words] for size in (3, 4, 5)}
        self.word_idf = _idf(self.words)
        self.bigram_idf = _idf(self.bigrams)
        self.character_idf = {size: _idf(values) for size, values in self.characters.items()}
        self.lengths = [sum(counter.values()) for counter in self.words]
        self.mean_length = math.fsum(self.lengths) / len(self.lengths)
        self.frequency = Counter(token for counter in self.words for token in counter)
        self.word_vectors = [_vector(value, self.word_idf) for value in self.words]
        self.sublinear_vectors = [_vector(value, self.word_idf, sublinear=True) for value in self.words]
        self.bigram_vectors = [_vector(value, self.bigram_idf) for value in self.bigrams]
        self.character_vectors = {
            size: [_vector(value, self.character_idf[size]) for value in values]
            for size, values in self.characters.items()
        }

    def features(self, query: str) -> tuple[tuple[float, ...], ...]:
        words = _tokens(query)
        query_counter = Counter(words)
        query_set = set(query_counter)
        query_vector = _vector(query_counter, self.word_idf)
        sublinear = _vector(query_counter, self.word_idf, sublinear=True)
        bigrams = _bigrams(words)
        bigram_set = set(bigrams)
        bigram_vector = _vector(bigrams, self.bigram_idf)
        character_vectors = {
            size: _vector(_characters(words, size), self.character_idf[size]) for size in (3, 4, 5)
        }
        query_idf = math.fsum(
            self.word_idf.get(token, 1.0 + math.log(len(self.words) + 1)) for token in query_set
        )
        bm25_idf = {
            token: math.log(
                1.0 + (len(self.words) - self.frequency[token] + 0.5) / (self.frequency[token] + 0.5)
            )
            for token in query_set
        }
        bm25_maximum = 2.2 * math.fsum(bm25_idf.values())
        rows = []
        for index, counter in enumerate(self.words):
            document_set = set(counter)
            intersection = query_set & document_set
            covered_idf = math.fsum(self.word_idf[token] for token in intersection)
            document_idf = math.fsum(self.word_idf[token] for token in document_set)
            bm25 = (
                math.fsum(
                    bm25_idf[token]
                    * counter[token]
                    * 2.2
                    / (counter[token] + 1.2 * (0.25 + 0.75 * self.lengths[index] / self.mean_length))
                    for token in intersection
                )
                if self.mean_length
                else 0.0
            )
            rows.append(
                (
                    bm25 / bm25_maximum if bm25_maximum else 0.0,
                    _cosine(query_vector, self.word_vectors[index]),
                    _cosine(sublinear, self.sublinear_vectors[index]),
                    *_overlap(query_set, document_set),
                    covered_idf / query_idf if query_idf else 0.0,
                    covered_idf / document_idf if document_idf else 0.0,
                    *_overlap(bigram_set, set(self.bigrams[index])),
                    _cosine(bigram_vector, self.bigram_vectors[index]),
                    *(
                        _cosine(character_vectors[size], self.character_vectors[size][index])
                        for size in (3, 4, 5)
                    ),
                )
            )
        return tuple(rows)


def artifact_digest(value: dict[str, Any]) -> str:
    body = {key: field for key, field in value.items() if key != "model_sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class PortableTextRanker:
    """A linear score learned with pairwise logistic loss, not a probability."""

    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    regularization: float
    source_sha256: str
    training_query_clusters: int
    training_judgments: int
    training_preference_pairs: int

    def __post_init__(self) -> None:
        for name, values in (
            ("means", self.means),
            ("scales", self.scales),
            ("coefficients", self.coefficients),
        ):
            if (
                not isinstance(values, tuple)
                or len(values) != len(FEATURE_NAMES)
                or any(not _finite(value) for value in values)
            ):
                raise ValueError(f"Invalid {name} feature vector.")
        if any(not 0 <= value <= 1 for value in self.means):
            raise ValueError("Training feature means must be in [0, 1].")
        if any(not 1e-8 <= value <= 1e4 for value in self.scales) or any(
            abs(value) > 1e4 for value in self.coefficients
        ):
            raise ValueError("Model scaling or coefficient bounds are invalid.")
        if not _finite(self.regularization) or not 0 < self.regularization <= 1e6:
            raise ValueError("A finite positive regularization strength is required.")
        if not isinstance(self.source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("Pinned training source SHA256 is required.")
        if any(
            type(value) is not int or not 1 <= value <= 10_000_000
            for value in (
                self.training_query_clusters,
                self.training_judgments,
                self.training_preference_pairs,
            )
        ):
            raise ValueError("Positive bounded aggregate training counts are required.")

    def score_features(self, rows: Sequence[Sequence[float]]) -> tuple[float, ...]:
        scores = []
        for row in rows:
            if len(row) != len(FEATURE_NAMES) or any(
                not _finite(value) or not 0 <= value <= 1 for value in row
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
            "training_query_clusters": self.training_query_clusters,
            "training_judgments": self.training_judgments,
            "training_preference_pairs": self.training_preference_pairs,
        }
        value["model_sha256"] = artifact_digest(value)
        return value

    @classmethod
    def from_dict(cls, value: Any) -> PortableTextRanker:
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
            "training_query_clusters",
            "training_judgments",
            "training_preference_pairs",
            "model_sha256",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Text relevance artifact has an unexpected schema.")
        if (
            value["schema"] != MODEL_SCHEMA
            or value["target"] != MODEL_TARGET
            or value["scope"] != "OFFLINE_RESEARCH_ONLY"
            or value["production_eligible"] is not False
            or value["feature_version"] != FEATURE_VERSION
            or value["feature_names"] != list(FEATURE_NAMES)
        ):
            raise ValueError("Artifact target, scope or feature contract is invalid.")
        try:
            if value["model_sha256"] != artifact_digest(value):
                raise ValueError("Artifact integrity check failed.")
            if any(not isinstance(value[name], list) for name in ("means", "scales", "coefficients")):
                raise ValueError("Artifact feature vectors must be JSON arrays.")
            return cls(
                means=tuple(value["means"]),
                scales=tuple(value["scales"]),
                coefficients=tuple(value["coefficients"]),
                regularization=value["regularization"],
                source_sha256=value["source_sha256"],
                training_query_clusters=value["training_query_clusters"],
                training_judgments=value["training_judgments"],
                training_preference_pairs=value["training_preference_pairs"],
            )
        except (TypeError, OverflowError) as error:
            raise ValueError("Artifact contains invalid numeric or JSON values.") from error
