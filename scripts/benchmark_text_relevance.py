"""Nested public-human validation and external exploratory transfer of a learned ranker.

The known public labels are not an untouched external test. This command never
trains on TalentCLEF labels, treats its unlisted pairs as negatives, promotes a
model, or claims observed mutual-interest/hiring accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from scripts.matching_skill_proxy import SkillProxy, score_skill_sets
from scripts.matching_text_benchmark import load_source as load_human_source
from scripts.matching_text_benchmark import score_documents
from scripts.train_text_relevance import (
    TRAINING_PROTOCOL,
    PortableTextRanker,
    TextFeatureIndex,
    nested_cross_validate,
    train_final,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = "public-human-pairwise-learning-nested-cv-v1"
LEARNED = "pairwise_logistic_nested_oof"
PROXY = "current_structured_skill_proxy"
LEXICAL = ("bm25", "tfidf_cosine", "lexical_jaccard")
SOURCE_FILES = (
    "apps/api/app/matching/reciprocal.py",
    "apps/api/app/matching/attention.py",
    "apps/api/app/matching/score.py",
    "apps/api/app/matching/types.py",
    "apps/api/app/matching/text_relevance.py",
    "scripts/train_text_relevance.py",
    "scripts/benchmark_text_relevance.py",
    "scripts/matching_text_benchmark.py",
    "scripts/matching_accuracy_metrics.py",
    "scripts/matching_binary_metrics.py",
    "scripts/matching_skill_proxy.py",
    "scripts/talentclef_source.py",
    "scripts/esco_source.py",
)
LIMITATIONS = [
    "Public human ordinal relevance is not consented observed mutual interest or hiring; this artifact is not eligible for production outcome-model promotion.",
    "Vanetik data were already examined before this experiment. Nested group cross-validation prevents direct fold leakage but is exploratory, conditional on five fixed jobs, two raters and source selection.",
    "All raters and pairwise labels for a CV remain in the same fold. Each CV contributes equal training weight. Outer held-out CV labels do not select that CV's model or scaling.",
    "Bootstrap CV clusters contain the correlated rater judgments. Conditional intervals do not account for the uncertainty of retraining, dataset selection, fixed jobs or general population shifts.",
    "TalentCLEF English development data were already examined before this experiment. Transfer results are external exploratory diagnostics, not an untouched independent test or official leaderboard score.",
    "TalentCLEF labels never enter training, scaling or hyperparameter selection. Its unlisted pairs earn no retrieval credit but are not confirmed negative examples.",
    "TalentCLEF profiles are synthetic, expert annotated, and queried in the opposite direction from the human training task. Candidate-pool IDF and query/document direction are part of the feature contract.",
    "Generic lexical features do not resolve negation, verify skills, infer actual bilateral preferences or guarantee fairness. No explicit demographic, person-ID, organization-ID or job-ID predictor is used.",
    "Different human first choices impose a dataset-specific upper bound on pooled top-one agreement. The oracle ceiling is descriptive only, never used for fitting, normalized accuracy or model selection.",
    "The optional official test submission is predictions on unlabeled test text only; no external evaluation, fairness certification or held-out result is implied.",
]


def _fingerprints() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in SOURCE_FILES
    }


def human_agreement(annotations: dict[str, list[list[int] | None]]) -> dict[str, Any]:
    rows = list(annotations.values())
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("Rater arrays must share CV positions.")
    shared, same, judgments, attainable = 0, 0, 0, 0
    for index in range(len(rows[0])):
        orders = [row[index] for row in rows]
        first = [order[0] for order in orders if order is not None]
        if not first:
            continue
        judgments += len(first)
        attainable += max(first.count(choice) for choice in set(first))
        if len(first) == 2:
            shared += 1
            same += int(first[0] == first[1])
    return {
        "cv_clusters_with_two_raters": shared,
        "same_first_choice_clusters": same,
        "two_rater_first_choice_agreement": same / shared if shared else None,
        "available_query_rater_judgments": judgments,
        "oracle_attainable_first_choice_judgments": attainable,
        "oracle_maximum_pooled_top1_agreement": attainable / judgments if judgments else None,
        "oracle_is_used_for_training_or_normalizing_accuracy": False,
    }


def _official_test_predictions(source: Path, model: PortableTextRanker) -> tuple[str, dict[str, Any]]:
    # The strict source loader has already validated the entire pinned inventory.
    with zipfile.ZipFile(source) as archive:

        def documents(prefix: str) -> dict[str, str]:
            return {
                name.removeprefix(prefix): archive.read(name).decode("utf-8-sig").strip()
                for name in archive.namelist()
                if name.startswith(prefix) and not name.endswith("/")
            }

        jobs = documents("TaskA/test/en/queries/")
        resumes = documents("TaskA/test/en/corpus/")
    if len(jobs) != 40 or len(resumes) != 476:
        raise ValueError("Expected the pinned unlabeled official English test inventory.")
    candidate_ids = sorted(resumes)
    index = TextFeatureIndex([resumes[key] for key in candidate_ids])
    lines = []
    for job, text in sorted(jobs.items()):
        scores = model.score_features(index.features(text))
        ranked = sorted(zip(candidate_ids, scores, strict=True), key=lambda item: (-item[1], item[0]))
        for rank, (candidate, score) in enumerate(ranked, 1):
            lines.append(f"{job}\tQ0\t{candidate}\t{rank}\t{score:.17g}\tck_public_ordinal_v1")
    text = "\n".join(lines) + "\n"
    return text, {
        "queries": len(jobs),
        "candidate_pool": len(resumes),
        "prediction_rows": len(lines),
        "submission_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "labels_available": False,
        "external_submission_performed": False,
        "external_accuracy": None,
        "tie_break": "candidate ID only for submission formatting; aggregate evaluations use tie expectations",
    }


def run_benchmark(
    human_source: Path,
    talent_source: Path,
    esco_source: Path,
    output: Path,
    *,
    bootstrap_replicates: int = 10_000,
    prepare_official_test: bool = False,
) -> dict[str, Any]:
    from scripts.esco_source import load_source as load_esco_source
    from scripts.matching_accuracy_metrics import evaluate_scores
    from scripts.matching_binary_metrics import evaluate_retrieval_scores
    from scripts.talentclef_source import load_source as load_talent_source

    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a fresh immutable evaluation output directory.")
    if (
        type(bootstrap_replicates) is not int
        or bootstrap_replicates < 1000
        or type(prepare_official_test) is not bool
    ):
        raise ValueError(
            "At least 1000 bootstrap replicates and an explicit boolean test option are required."
        )
    fingerprints = _fingerprints()
    concepts, taxonomy = load_esco_source(esco_source)
    proxy = SkillProxy(concepts)
    protocol = {
        "protocol_version": PROTOCOL_VERSION,
        "source_sha256": fingerprints,
        "training": TRAINING_PROTOCOL,
        "bootstrap_replicates": bootstrap_replicates,
        "bootstrap_seed": 20261018,
        "primary_human_metric": "pairwise_agreement",
        "secondary_human_metric": "top1_agreement",
        "external_transfer_primary_metric": "map_of_published_positive_candidates",
        "comparison_reference": "tfidf_cosine",
        "retrieval_cutoff": 10,
        "human_methods": [LEARNED, PROXY, *LEXICAL],
        "transfer_methods": ["pairwise_logistic_all_human_labels", PROXY, *LEXICAL],
        "adapter": proxy.provenance,
        "taxonomy": taxonomy,
        "prepare_official_unlabeled_test": prepare_official_test,
        "additional_neural_features": False,
        "selection_or_tuning_after_seeing_outer_or_transfer_results": False,
    }
    protocol_digest = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    started = time.perf_counter()
    jobs, resumes, annotations, provenance = load_human_source(human_source)
    index = TextFeatureIndex(jobs)
    features = [index.features(text) for text in resumes]
    oof, validation = nested_cross_validate(features, annotations, source_sha256=provenance["archive_sha256"])
    model, final_selection = train_final(features, annotations, source_sha256=provenance["archive_sha256"])
    predictions: dict[str, list[list[float]]] = {LEARNED: oof, PROXY: [], **{name: [] for name in LEXICAL}}
    job_skills = [proxy.extract(text) for text in jobs]
    for text in resumes:
        skills = proxy.extract(text)
        predictions[PROXY].append([score_skill_sets(skills, preferred) for preferred in job_skills])
        lexical = score_documents(text, jobs)
        for name in LEXICAL:
            predictions[name].append(lexical[name])
    human_results = evaluate_scores(
        predictions,
        annotations,
        bootstrap_replicates=bootstrap_replicates,
        seed=20261018,
        reference_method="tfidf_cosine",
    )
    talent_jobs, talent_resumes, qrels, talent_provenance = load_talent_source(talent_source)
    candidate_ids = sorted(talent_resumes)
    texts = [talent_resumes[key] for key in candidate_ids]
    candidate_skills = [proxy.extract(text) for text in texts]
    transfer_index = TextFeatureIndex(texts)
    transfer: dict[str, dict[str, dict[str, float]]] = {
        name: {} for name in ("pairwise_logistic_all_human_labels", PROXY, *LEXICAL)
    }
    for job, text in sorted(talent_jobs.items()):
        values = model.score_features(transfer_index.features(text))
        transfer["pairwise_logistic_all_human_labels"][job] = dict(zip(candidate_ids, values, strict=True))
        skills = proxy.extract(text)
        transfer[PROXY][job] = dict(
            zip(candidate_ids, [score_skill_sets(value, skills) for value in candidate_skills], strict=True)
        )
        lexical = score_documents(text, texts)
        for name in LEXICAL:
            transfer[name][job] = dict(zip(candidate_ids, lexical[name], strict=True))
    transfer_results = evaluate_retrieval_scores(
        transfer,
        qrels,
        cutoff=10,
        bootstrap_replicates=bootstrap_replicates,
        seed=20261018,
        reference_method="tfidf_cosine",
    )
    submission, submission_summary = (
        _official_test_predictions(talent_source, model) if prepare_official_test else (None, None)
    )
    if fingerprints != _fingerprints():
        raise ValueError("Evaluation source changed during the run; no artifact published.")
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_digest,
        "evaluation_completed": True,
        "production_model_promoted": False,
        "production_matching_accuracy": None,
        "fitted_model_sha256": model.to_dict()["model_sha256"],
        "runtime": {"python": platform.python_version(), "elapsed_seconds": time.perf_counter() - started},
        "validation": validation,
        "final_model_selection": final_selection,
        "datasets": {
            "vanetik_nested_cv": {
                "source": provenance,
                "results": human_results,
                "human_agreement": human_agreement(annotations),
            },
            "talentclef_exploratory_transfer": {"source": talent_provenance, "results": transfer_results},
        },
        "unlabeled_official_test": submission_summary,
        "limitations": LIMITATIONS,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".text-relevance-evaluation-", dir=output.parent) as temporary:
        staged = Path(temporary) / "complete"
        staged.mkdir()
        for name, value in (
            ("protocol.json", protocol),
            ("report.json", report),
            ("public-ordinal-model.json", model.to_dict()),
        ):
            (staged / name).write_text(
                json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
            )
        if submission is not None:
            (staged / "talentclef-test-en.run").write_text(submission, encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Output appeared during evaluation; refusing replacement.")
        staged.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--human-source", type=Path, default=Path(".local/matching-human-benchmark/source/repository.zip")
    )
    parser.add_argument(
        "--talent-source", type=Path, default=Path(".local/matching-accuracy/talentclef/source/TaskA.zip")
    )
    parser.add_argument("--esco-source", type=Path, default=Path(".local/matching-accuracy/esco"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    parser.add_argument("--prepare-official-test", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(
        args.human_source,
        args.talent_source,
        args.esco_source,
        args.output,
        bootstrap_replicates=args.bootstrap_replicates,
        prepare_official_test=args.prepare_official_test,
    )
    print(
        json.dumps(
            {
                "completed": report["evaluation_completed"],
                "output": str(args.output),
                "model_sha256": report["fitted_model_sha256"],
                "production_model_promoted": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
