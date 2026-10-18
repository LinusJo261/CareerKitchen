"""Frozen ESCO text adapter for offline measurement of the current scoring core.

Extracted mentions are not confirmed application profiles. Eligibility, candidate
preferences and attention are unobserved in these corpora. Nothing in this module
is connected to live matching, inference, consent, or profile mutations.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.matching.attention import MarketPrices  # noqa: E402
from app.matching.reciprocal import ReciprocalFeatures, score_reciprocal, skill_coverage  # noqa: E402

from scripts.matching_text_benchmark import tokens

ADAPTER_VERSION = "esco-exact-phrase-conditional-compatibility-v1"
ASSUMPTIONS = {
    "candidate_skills": "ESCO concepts explicitly mentioned in text; not app-confirmed skills",
    "vacancy_preferences": "all ESCO skill mentions treated as optional for this component experiment",
    "candidate_role": "held at one, conditional on hypothetical eligibility",
    "candidate_work_mode": "held at one, conditional on hypothetical eligibility",
    "candidate_employment_type": "held at one, conditional on hypothetical eligibility",
    "eligibility": "not observed or evaluated; no production eligibility claim",
    "prices": "zero; evaluates compatibility before attention and allocation",
    "learned_model": "none; actual deterministic reciprocal-compatibility-v1 function",
    "missing_job_skills": "native not-applicable behavior retained without penalty",
    "alias_resolution": "exact token sequences only; all ambiguous labels excluded",
    "label_tuning": "none; no parameters or taxonomy terms selected using relevance labels",
}


class SkillProxy:
    """Resolve fixed official labels with a token trie, retaining concept identity."""

    def __init__(self, concepts: Iterable[dict]):
        aliases: dict[tuple[str, ...], set[str]] = {}
        concept_ids = set()
        normalized = []
        for concept in concepts:
            identifier = concept["id"]
            preferred = concept["preferred_label"]
            alternate = concept["aliases"]
            if (
                not isinstance(identifier, str)
                or not identifier
                or identifier in concept_ids
                or not isinstance(preferred, str)
                or not preferred.strip()
                or not isinstance(alternate, list)
                or any(not isinstance(v, str) or not v.strip() for v in alternate)
            ):
                raise ValueError("Unique concept IDs, preferred labels and string aliases are required")
            concept_ids.add(identifier)
            normalized.append(
                {"id": identifier, "preferred_label": preferred, "aliases": sorted(set(alternate))}
            )
            for label in (preferred, *alternate):
                sequence = tuple(tokens(label))
                if sequence:
                    aliases.setdefault(sequence, set()).add(identifier)
        if not concept_ids:
            raise ValueError("A frozen nonempty ESCO vocabulary is required")
        self.trie: dict = {}
        ambiguous = 0
        for phrase, identifiers in sorted(aliases.items()):
            if len(identifiers) != 1:
                ambiguous += 1
                continue
            node = self.trie
            for token in phrase:
                node = node.setdefault(token, {})
            node[None] = next(iter(identifiers))
        self.provenance = {
            "adapter_version": ADAPTER_VERSION,
            "concept_count": len(concept_ids),
            "unambiguous_alias_sequences": len(aliases) - ambiguous,
            "ambiguous_alias_sequences_excluded": ambiguous,
            "vocabulary_sha256": hashlib.sha256(
                json.dumps(
                    sorted(normalized, key=lambda row: row["id"]), sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "assumptions": ASSUMPTIONS,
        }

    def extract(self, text: str) -> frozenset[str]:
        if not isinstance(text, str):
            raise ValueError("Source text must be a string")
        sequence = tokens(text)
        found = set()
        for start in range(len(sequence)):
            node = self.trie
            for end in range(start, len(sequence)):
                token = sequence[end]
                if token not in node:
                    break
                node = node[token]
                if None in node:
                    found.add(node[None])
        return frozenset(found)


def score_skill_sets(candidate_skills: Iterable[str], vacancy_skills: Iterable[str]) -> float:
    """Call current production math under the explicitly stated proxy conditions."""
    confirmed_for_component_test = tuple((value, ()) for value in sorted(set(candidate_skills)))
    preferred_for_component_test = tuple(sorted(set(vacancy_skills)))
    coverage = skill_coverage(confirmed_for_component_test, preferred_for_component_test)
    features = ReciprocalFeatures(
        candidate_id="offline-proxy-candidate",
        vacancy_id="offline-proxy-vacancy",
        candidate_version=1,
        vacancy_version=1,
        as_of="2026-10-18T00:00:00+00:00",
        employer_skills=coverage,
        candidate_role=1.0,
        candidate_work_mode=1.0,
        candidate_employment_type=1.0,
        eligible=True,
    )
    return score_reciprocal(features, MarketPrices())["relevance"]


def extraction_summary(values: Iterable[frozenset[str]]) -> dict:
    counts = Counter(len(value) for value in values)
    total = sum(counts.values())
    return {
        "documents": total,
        "documents_with_no_detected_concepts": counts[0],
        "mean_detected_concepts": sum(size * count for size, count in counts.items()) / total
        if total
        else None,
    }
