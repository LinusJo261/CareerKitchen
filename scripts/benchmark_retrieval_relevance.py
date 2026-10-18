"""Exploratory nested whole-job validation of a public-positive ML retriever.

The candidate corpus is shared transductive background, not an independent
candidate holdout. Public development labels have already been examined. This
never measures binary suitability accuracy, mutual interest or hiring outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.matching_skill_proxy import SkillProxy, score_skill_sets
from scripts.matching_text_benchmark import score_documents
from scripts.train_retrieval_relevance import (
    TRAINING_PROTOCOL,
    PortableRetrievalRanker,
    TextFeatureIndex,
    nested_cross_validate,
    train_final,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = "public-positive-listwise-nested-whole-job-v1"
RAW_ML = "listwise_published_positive_nested_oof"
GATED_ML = "listwise_inner_selected_tfidf_fallback_nested_oof"
PROXY = "current_structured_skill_proxy"
ORDINAL = "pairwise_ordinal_external_transfer"
LEXICAL = ("bm25", "tfidf_cosine", "lexical_jaccard")
SOURCE_FILES = (
    "apps/api/app/matching/retrieval_relevance.py",
    "apps/api/app/matching/text_relevance.py",
    "apps/api/app/matching/reciprocal.py",
    "apps/api/app/matching/score.py",
    "apps/api/app/matching/attention.py",
    "apps/api/app/matching/types.py",
    "scripts/train_retrieval_relevance.py",
    "scripts/benchmark_retrieval_relevance.py",
    "scripts/train_text_relevance.py",
    "scripts/matching_text_benchmark.py",
    "scripts/matching_binary_metrics.py",
    "scripts/matching_accuracy_metrics.py",
    "scripts/matching_skill_proxy.py",
    "scripts/esco_source.py",
    "scripts/talentclef_source.py",
)
LIMITATIONS = [
    "Exploratory nested leave-one-job-out evaluation on already examined public English development data; not an untouched external test or official leaderboard score.",
    "The entire candidate corpus is shared seen background across folds and label-free indexing; this is transductive validation of new job labels, not an independent candidate holdout.",
    "Candidate labels from a held-out job never enter fitting, scaling, regularization selection or the decision to use the deterministic TF-IDF fallback for that job.",
    "Only published-positive judgments supply targets. Unlisted candidates compete in the softmax denominator as unlabeled background, not confirmed negative suitability or outcome labels.",
    "This surrogate encourages published positives above background. Missing or selectively recorded positives can bias the ranking; no unbiased positive-unlabeled risk claim is made.",
    "TalentCLEF documents are privacy-preserving synthetic profiles with expert relevance annotations, not consented observed applicant or employer decisions.",
    "MAP and published-positive P@10 measure retrieval credit. Neither is binary matching accuracy, verified suitability precision, calibrated interest probability or hiring success.",
    "Ten held-out job clusters and a shared corpus are small; query bootstrap intervals condition on fitted outer predictions and do not account for retraining uncertainty or correlated skills and organizations.",
    "Public ML artifacts have a distinct retrieval target and OFFLINE_RESEARCH_ONLY scope. They cannot qualify for consented outcome-model promotion or bypass eligibility, consent, attention or double opt-in.",
    "All raw learner, inner-gated policy and lexical comparisons are reported. Inner validation selects lambda and fallback; outer results never tune this protocol.",
]


def _fingerprints() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in SOURCE_FILES
    }


def run_benchmark(
    talent_source: Path,
    esco_source: Path,
    output: Path,
    *,
    ordinal_model: Path | None = None,
    bootstrap_replicates: int = 10_000,
) -> dict[str, Any]:
    from app.matching.text_relevance import PortableTextRanker

    from scripts.esco_source import load_source as load_esco_source
    from scripts.matching_binary_metrics import evaluate_retrieval_scores
    from scripts.talentclef_source import load_source as load_talent_source

    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a fresh immutable evaluation directory.")
    if type(bootstrap_replicates) is not int or bootstrap_replicates < 1000:
        raise ValueError("At least 1000 whole-job bootstrap replicates are required.")
    fingerprints = _fingerprints()
    concepts, taxonomy = load_esco_source(esco_source)
    proxy = SkillProxy(concepts)
    ordinal = None
    ordinal_sha = None
    if ordinal_model is not None:
        ordinal_bytes = ordinal_model.read_bytes()
        ordinal_sha = hashlib.sha256(ordinal_bytes).hexdigest()
        ordinal = PortableTextRanker.from_dict(json.loads(ordinal_bytes))
    methods = [RAW_ML, GATED_ML, PROXY, *LEXICAL, *([ORDINAL] if ordinal is not None else [])]
    protocol = {
        "protocol_version": PROTOCOL_VERSION,
        "source_sha256": fingerprints,
        "training": TRAINING_PROTOCOL,
        "taxonomy": taxonomy,
        "adapter": proxy.provenance,
        "bootstrap_replicates": bootstrap_replicates,
        "bootstrap_seed": 20261018,
        "primary_metric": "published_positive_map",
        "retrieval_cutoff": 10,
        "reference_method": "tfidf_cosine",
        "methods": methods,
        "optional_external_ordinal_artifact_sha256": ordinal_sha,
        "candidate_corpus_holdout": False,
        "shared_candidate_background": True,
        "human_ordinal_labels_used_to_fit_retrieval_model": False,
        "production_eligible": False,
        "external_outcome_accuracy_measured": False,
    }
    serialized = json.dumps(protocol, sort_keys=True, allow_nan=False)
    protocol_digest = hashlib.sha256(serialized.encode()).hexdigest()
    # All settings and relevant sources are frozen before loading retrieval labels.
    started = time.perf_counter()
    jobs, resumes, qrels, provenance = load_talent_source(talent_source)
    candidate_ids = sorted(resumes)
    job_ids = sorted(jobs)
    texts = [resumes[key] for key in candidate_ids]
    index = TextFeatureIndex(texts)
    features, positives, baseline = [], [], []
    predictions: dict[str, dict[str, dict[str, float]]] = {name: {} for name in methods}
    candidate_skills = [proxy.extract(text) for text in texts]
    for job in job_ids:
        if not qrels.get(job) or any(value != 1 for value in qrels[job].values()):
            raise ValueError(
                "The frozen public-positive protocol requires positive-only judgments for every job."
            )
        if not set(qrels[job]) <= set(candidate_ids):
            raise ValueError("Published-positive documents must belong to the common candidate pool.")
        text = jobs[job]
        rows = index.features(text)
        features.append(rows)
        positives.append([i for i, key in enumerate(candidate_ids) if key in qrels[job]])
        lexical = score_documents(text, texts)
        baseline.append(lexical["tfidf_cosine"])
        for method in LEXICAL:
            predictions[method][job] = dict(zip(candidate_ids, lexical[method], strict=True))
        job_skills = proxy.extract(text)
        predictions[PROXY][job] = dict(
            zip(
                candidate_ids,
                [score_skill_sets(value, job_skills) for value in candidate_skills],
                strict=True,
            )
        )
        if ordinal is not None:
            predictions[ORDINAL][job] = dict(zip(candidate_ids, ordinal.score_features(rows), strict=True))
    learned, gated, validation = nested_cross_validate(
        features,
        positives,
        baseline,
        source_sha256=provenance["archive_sha256"],
    )
    for job, raw, selected in zip(job_ids, learned, gated, strict=True):
        predictions[RAW_ML][job] = dict(zip(candidate_ids, raw, strict=True))
        predictions[GATED_ML][job] = dict(zip(candidate_ids, selected, strict=True))
    results = evaluate_retrieval_scores(
        predictions,
        qrels,
        cutoff=10,
        bootstrap_replicates=bootstrap_replicates,
        seed=20261018,
        reference_method="tfidf_cosine",
    )
    model, final_policy = train_final(
        features, positives, baseline, source_sha256=provenance["archive_sha256"]
    )
    restored = PortableRetrievalRanker.from_dict(json.loads(json.dumps(model.to_dict(), allow_nan=False)))
    replay = all(model.score_features(rows) == restored.score_features(rows) for rows in features)
    if not replay:
        raise ValueError("Portable numeric artifact replay differs; no artifact published.")
    if fingerprints != _fingerprints():
        raise ValueError("Evaluation sources changed during the run; no artifact published.")
    if ordinal_model is not None and hashlib.sha256(ordinal_model.read_bytes()).hexdigest() != ordinal_sha:
        raise ValueError("External comparator artifact changed during evaluation.")
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_digest,
        "evaluation_completed": True,
        "production_model_promoted": False,
        "production_matching_accuracy": None,
        "binary_accuracy_measured": False,
        "source": provenance,
        "validation": validation,
        "results": results,
        "final_model_policy": final_policy,
        "model_sha256": model.to_dict()["model_sha256"],
        "portable_artifact_replay_verified": replay,
        "runtime": {"python": platform.python_version(), "elapsed_seconds": time.perf_counter() - started},
        "limitations": LIMITATIONS,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".listwise-retrieval-", dir=output.parent) as temporary:
        staged = Path(temporary) / "complete"
        staged.mkdir()
        for filename, value in (
            ("protocol.json", protocol),
            ("report.json", report),
            ("public-retrieval-model.json", model.to_dict()),
        ):
            (staged / filename).write_text(
                json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
            )
        if output.exists() or output.is_symlink():
            raise FileExistsError("Output appeared during evaluation; refusing replacement.")
        staged.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--talent-source", type=Path, default=Path(".local/matching-accuracy/talentclef/source/TaskA.zip")
    )
    parser.add_argument("--esco-source", type=Path, default=Path(".local/matching-accuracy/esco"))
    parser.add_argument("--ordinal-model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    args = parser.parse_args()
    report = run_benchmark(
        args.talent_source,
        args.esco_source,
        args.output,
        ordinal_model=args.ordinal_model,
        bootstrap_replicates=args.bootstrap_replicates,
    )
    print(
        json.dumps(
            {
                "completed": True,
                "output": str(args.output),
                "validation": report["validation"],
                "methods": {key: value["mean"] for key, value in report["results"]["methods"].items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
