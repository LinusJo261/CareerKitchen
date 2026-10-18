"""Measure frozen compatibility-core proxies against public human relevance labels.

This is not deployed-system, mutual-interest or hiring accuracy. Native structured
features are unavailable; the explicit ESCO adapter and conditional assumptions
are part of the measured experiment. It never trains or activates a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
import time
from pathlib import Path

from scripts.matching_skill_proxy import ASSUMPTIONS, SkillProxy, extraction_summary, score_skill_sets
from scripts.matching_text_benchmark import FIXED_PARAMETERS, score_documents
from scripts.matching_text_benchmark import load_source as load_human_source

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = "public-human-compatibility-core-evaluation-v2"
REFERENCE = "current_structured_skill_proxy"
COMPARATORS = ("bm25", "tfidf_cosine", "lexical_jaccard")
SOURCE_FILES = (
    "apps/api/app/matching/reciprocal.py",
    "apps/api/app/matching/attention.py",
    "apps/api/app/matching/score.py",
    "apps/api/app/matching/types.py",
    "scripts/matching_text_benchmark.py",
    "scripts/matching_skill_proxy.py",
    "scripts/matching_accuracy_metrics.py",
    "scripts/matching_binary_metrics.py",
    "scripts/talentclef_source.py",
    "scripts/esco_source.py",
    "scripts/benchmark_matching_accuracy.py",
)
LIMITATIONS = [
    "The actual live algorithm's full matching accuracy remains unmeasured: native features, eligibility, consent and bilateral outcomes are not supplied by these sources.",
    "The current production scoring function is called with a frozen ESCO text adapter; extracted mentions are unconfirmed and all candidate compatibility inputs are held at one.",
    "This measures an offline compatibility-core proxy, not production profile extraction, attention allocation, reciprocal interest or hiring.",
    "Vanetik has 30 CV queries, five fixed jobs and two correlated raters; its uncertainty is conditional on those jobs and raters.",
    "TalentCLEF development documents are privacy-preserving synthetic text derived from real-world statistics, with human expert relevance judgments; no observed employment outcomes are supplied.",
    "TalentCLEF English development qrels contain only published positive judgments. Unlisted pairs earn no retrieval credit but are not confirmed negative matches.",
    "TalentCLEF results are published-qrels retrieval metrics on development data, not binary classification accuracy or an independently held-out official leaderboard submission.",
    "All methods, taxonomy matching rules, seeds and metrics are fixed; no fitting or label-based parameter selection occurs.",
    "Bootstrap intervals are conditional descriptive query-cluster summaries, not guarantees of population coverage, independent employer effects or hiring reliability.",
    "Baseline text methods are research comparators; their scores must never be attributed to the live matching algorithm.",
]


def _fingerprints() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in SOURCE_FILES
    }


def run_benchmark(
    human_source: Path,
    talent_source: Path,
    esco_source: Path,
    output: Path,
    *,
    seed: int = 20261018,
    bootstrap_replicates: int = 10000,
) -> dict:
    from scripts.esco_source import load_source as load_esco_source
    from scripts.matching_accuracy_metrics import evaluate_scores
    from scripts.matching_binary_metrics import evaluate_retrieval_scores
    from scripts.talentclef_source import load_source as load_talent_source

    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a fresh immutable benchmark output directory")
    if type(seed) is not int or type(bootstrap_replicates) is not int or bootstrap_replicates < 1000:
        raise ValueError("Use an integer seed and at least 1000 cluster-bootstrap replicates")
    fingerprints = _fingerprints()
    concepts, taxonomy = load_esco_source(esco_source)
    proxy = SkillProxy(concepts)
    protocol = {
        "protocol_version": PROTOCOL_VERSION,
        "source_sha256": fingerprints,
        "source_hash_normalization": "CRLF normalized to LF for Python source fingerprints only",
        "seed": seed,
        "bootstrap_replicates": bootstrap_replicates,
        "methods": [REFERENCE, *COMPARATORS],
        "reference_method": REFERENCE,
        "lexical_parameters": {key: value for key, value in FIXED_PARAMETERS.items() if key != "index"},
        "lexical_index_by_dataset": {
            "vanetik_human_rankings": "five vacancy titles plus descriptions; IDF fitted only to those five jobs",
            "talentclef_2026_english_development": "all 472 English development candidate documents; IDF fitted only to those documents",
        },
        "skill_adapter": proxy.provenance,
        "taxonomy": taxonomy,
        "human_primary_metric": "top1_agreement",
        "retrieval_primary_metric": "map_of_published_relevant_candidates",
        "retrieval_cutoff": 10,
        "fitting_or_parameter_selection": False,
        "native_feature_assumptions": ASSUMPTIONS,
        "scope": "offline_compatibility_core_proxy_with_public_text_adapter",
        "production_matching_accuracy": None,
    }
    # Freeze source code, vocabulary and all settings before reading any labels.
    serialized_protocol = json.dumps(protocol, sort_keys=True, allow_nan=False)
    protocol_digest = hashlib.sha256(serialized_protocol.encode()).hexdigest()
    started = time.perf_counter()
    jobs, resumes, annotations, human_provenance = load_human_source(human_source)
    human_jobs = [proxy.extract(text) for text in jobs]
    human_resumes = [proxy.extract(text) for text in resumes]
    ordinal: dict[str, list[list[float]]] = {name: [] for name in (REFERENCE, *COMPARATORS)}
    for text, skills in zip(resumes, human_resumes, strict=True):
        ordinal[REFERENCE].append([score_skill_sets(skills, preferred) for preferred in human_jobs])
        lexical = score_documents(text, jobs)
        for name in COMPARATORS:
            ordinal[name].append(lexical[name])
    human_results = evaluate_scores(
        ordinal, annotations, bootstrap_replicates=bootstrap_replicates, seed=seed, reference_method=REFERENCE
    )
    talent_jobs, talent_resumes, qrels, talent_provenance = load_talent_source(talent_source)
    candidate_ids = sorted(talent_resumes)
    candidate_texts = [talent_resumes[key] for key in candidate_ids]
    candidate_skills = {key: proxy.extract(talent_resumes[key]) for key in candidate_ids}
    job_skills = {key: proxy.extract(text) for key, text in talent_jobs.items()}
    retrieval: dict[str, dict[str, dict[str, float]]] = {name: {} for name in (REFERENCE, *COMPARATORS)}
    for job_id, text in sorted(talent_jobs.items()):
        retrieval[REFERENCE][job_id] = {
            key: score_skill_sets(candidate_skills[key], job_skills[job_id]) for key in candidate_ids
        }
        lexical = score_documents(text, candidate_texts)
        for name in COMPARATORS:
            retrieval[name][job_id] = dict(zip(candidate_ids, lexical[name], strict=True))
    talent_results = evaluate_retrieval_scores(
        retrieval,
        qrels,
        cutoff=10,
        bootstrap_replicates=bootstrap_replicates,
        seed=seed,
        reference_method=REFERENCE,
    )
    if fingerprints != _fingerprints():
        raise ValueError("Evaluation code changed while running; rerun against a frozen snapshot")
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_digest,
        "evaluation_completed": True,
        "production_matching_accuracy": None,
        "production_matching_accuracy_status": "NO_NATIVE_FEATURES_OR_OBSERVED_BILATERAL_OUTCOMES",
        "full_native_input_coverage": 0,
        "compatibility_core_experiment": True,
        "active_ml_model_evaluated": False,
        "runtime": {"python": platform.python_version(), "elapsed_seconds": time.perf_counter() - started},
        "datasets": {
            "vanetik_human_rankings": {
                "source": human_provenance,
                "results": human_results,
                "extraction": {
                    "vacancies": extraction_summary(human_jobs),
                    "resumes": extraction_summary(human_resumes),
                },
            },
            "talentclef_2026_english_development": {
                "source": talent_provenance,
                "results": talent_results,
                "extraction": {
                    "vacancies": extraction_summary(job_skills.values()),
                    "resumes": extraction_summary(candidate_skills.values()),
                },
            },
        },
        "limitations": LIMITATIONS,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".human-accuracy-", dir=output.parent) as temporary:
        staged = Path(temporary) / "complete"
        staged.mkdir()
        for filename, value in (("protocol.json", protocol), ("report.json", report)):
            (staged / filename).write_text(
                json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
            )
        if output.exists() or output.is_symlink():
            raise FileExistsError("Output appeared during evaluation; refusing to replace it")
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
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    args = parser.parse_args()
    report = run_benchmark(
        args.human_source,
        args.talent_source,
        args.esco_source,
        args.output,
        seed=args.seed,
        bootstrap_replicates=args.bootstrap_replicates,
    )
    print(
        json.dumps(
            {
                "completed": report["evaluation_completed"],
                "output": str(args.output),
                "production_accuracy": None,
                "scope": "compatibility core with an unconfirmed public-text adapter",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
