"""Offline synthetic relevance benchmark and optional training; no live API access.

Run from the repository root: python -m scripts.matching_research --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from scripts.matching_research_core import (
    FEATURE_NAMES,
    PreparedCorpus,
    feature_matrix,
    fit_logistic,
    normalize_generator_skill,
    ranking_metrics,
    sample_training_indices,
    split_jobs,
)

ROOT = Path(__file__).resolve().parents[1]
# The API need not be installed, configured, or running to import its pure scorer.
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.matching.reciprocal import skill_coverage  # noqa: E402

DATASET = "michaelozon/candidate-matching-synthetic"
REVISION = "178ab864dcad9910c5670d43e4bdbbb901a11f18"
FILES = {
    "resumes": "data/resumes-00000-of-00001.parquet",
    "jobs": "jobs/train-00000-of-00001.parquet",
    "matches": "matches/train-00000-of-00001.parquet",
}
LIMITATIONS = [
    "Synthetic skill-rule agreement only; not mutual-interest or hiring accuracy.",
    "Listed positives were randomly capped at 30; unlisted qualifying pairs are unlabeled.",
    "Training negatives are below the generator's 60% must-have coverage threshold, not real rejections.",
    "The live skill baseline below is only its preferred-skill component, not full matching or eligibility.",
    "Seniority, preferred skills and text were not used to generate the labels; their learned weights lack outcome evidence.",
    "Repeated language and related role templates can remain across splits; this is not a temporal evaluation.",
    "No candidate preferences, consent, pay, location, attention or independent employment outcomes are available.",
]


def load_tables(data_dir: Path | None, download: bool) -> tuple[dict, dict]:
    import pyarrow.parquet as parquet
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    tables, checksums = {}, {}
    for name, filename in FILES.items():
        if data_dir:
            path = data_dir / filename
        else:
            # Try both the standard cache used by inspect_matching_dataset.py and
            # our project-local download cache. Offline is always the default.
            path = None
            for cache in (None, ROOT / ".local" / "matching-research" / "cache"):
                try:
                    path = Path(
                        hf_hub_download(
                            DATASET,
                            filename,
                            repo_type="dataset",
                            revision=REVISION,
                            local_files_only=True,
                            cache_dir=cache,
                        )
                    )
                    break
                except LocalEntryNotFoundError:
                    continue
            if path is None:
                if not download:
                    raise ValueError(
                        "Pinned dataset is not cached. Use --download once, or --data-dir PATH "
                        "containing the data/, jobs/ and matches/ Parquet files."
                    )
                path = Path(
                    hf_hub_download(
                        DATASET,
                        filename,
                        repo_type="dataset",
                        revision=REVISION,
                        cache_dir=ROOT / ".local" / "matching-research" / "cache",
                    )
                )
        assert path is not None
        tables[name] = parquet.read_table(path).to_pylist()
        checksums[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"Loaded {name}: {len(tables[name]):,}", flush=True)
    validate_tables(tables)
    return tables, checksums


def validate_tables(tables: dict) -> None:
    for name, key in (("resumes", "resume_id"), ("jobs", "job_id"), ("matches", "job_id")):
        rows = tables[name]
        ids = [row[key] for row in rows]
        if not rows or len(set(ids)) != len(ids) or not all(isinstance(x, str) and x for x in ids):
            raise ValueError(f"{name}: empty table, duplicate or invalid IDs")
    resume_ids = {row["resume_id"] for row in tables["resumes"]}
    jobs = {row["job_id"]: row for row in tables["jobs"]}
    if set(jobs) != {row["job_id"] for row in tables["matches"]}:
        raise ValueError("Every job must have exactly one matching record")
    for row in tables["resumes"]:
        _skill_list(row["skills"])
        for field in ("role", "seniority", "summary"):
            if not isinstance(row[field], str):
                raise ValueError(f"Invalid resume {field}")
    for row in tables["jobs"]:
        required = _skill_list(row["must_have_skills"])
        _skill_list(row["nice_to_have_skills"])
        if not required:
            raise ValueError("Must-have skills cannot be empty for this benchmark")
    for row in tables["matches"]:
        listed = row["relevant_resume_ids"]
        if not isinstance(listed, list) or len(set(listed)) != len(listed) or not set(listed) <= resume_ids:
            raise ValueError("Invalid, duplicate or dangling relevant resume IDs")
    # Verify the assumed generator rule against ALL supplied positives before
    # using it to derive any negative examples.
    skills = {row["resume_id"]: _skill_list(row["skills"]) for row in tables["resumes"]}
    for row in tables["matches"]:
        required = _skill_list(jobs[row["job_id"]]["must_have_skills"])
        if any(len(required & skills[rid]) / len(required) < 0.6 for rid in row["relevant_resume_ids"]):
            raise ValueError("Listed positives contradict the assumed generator rule; training refused")


def _skill_list(values: list[str]) -> set[str]:
    if not isinstance(values, list) or any(not isinstance(x, str) or not x.strip() for x in values):
        raise ValueError("Skills must be lists of nonempty strings")
    result = {normalize_generator_skill(value) for value in values}
    if "" in result:
        raise ValueError("Skill normalizes to empty text")
    return result


def resume_partitions(rows: list[dict], seed: int) -> tuple[dict[str, PreparedCorpus], dict]:
    groups: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}
    signatures = []
    for row in rows:
        # Duplicate model-visible content stays together even when IDs differ.
        content = {
            "seniority": normalize_generator_skill(row["seniority"]),
            "skills": sorted(_skill_list(row["skills"])),
            "text_tokens": sorted(
                set(
                    normalize_generator_skill(
                        " ".join(
                            [
                                row["role"],
                                row["summary"],
                                *row["experience_bullets"],
                            ]
                        )
                    ).split()
                )
            ),
        }
        signature = json.dumps(content, sort_keys=True, ensure_ascii=True)
        signatures.append(signature)
        bucket = int(hashlib.sha256(f"{seed}:{signature}".encode()).hexdigest(), 16) % 100
        group = "train" if bucket < 70 else "validation" if bucket < 85 else "test"
        groups[group].append(row)
    if any(not values for values in groups.values()):
        raise ValueError("Not enough distinct resume templates for train/validation/test splits")
    diagnostics = {
        "duplicate_model_visible_resume_rows": len(rows) - len(set(signatures)),
        "resume_split_counts": {key: len(value) for key, value in groups.items()},
        "job_split_policy": "70/15/15 stable hash of structured job template; duplicate templates kept together",
        "resume_split_policy": "70/15/15 stable hash of model-visible resume content; no ID features",
    }
    return {key: PreparedCorpus(values) for key, values in groups.items()}, diagnostics


def baseline_scores(job: dict, corpus: PreparedCorpus, features: np.ndarray) -> dict:
    # Reuse the real helper, with no fabricated taxonomy aliases/confirmations.
    # This is a synthetic relevance calculation, not an import of real profiles.
    current = np.array(
        [
            skill_coverage(tuple((name, ()) for name in row["skills"]), tuple(job["nice_to_have_skills"]))
            or 0.0
            for row in corpus.rows
        ]
    )
    return {
        "current_preferred_skill_component": current,
        "required_skill_overlap": features[:, 0],
        "equal_required_preferred_overlap": (
            (features[:, 0] + features[:, 1]) / 2 if job["nice_to_have_skills"] else features[:, 0]
        ),
    }


def evaluate(jobs: list[dict], corpus: PreparedCorpus, labels: dict, k: int, model=None) -> dict:
    per_method: dict[str, list[dict]] = {}
    examples = {}
    for count, job in enumerate(jobs, 1):
        features = feature_matrix(job, corpus)
        methods = baseline_scores(job, corpus, features)
        if model is not None:
            methods["learned_synthetic_relevance"] = model.scores(features)
        for name, scores in methods.items():
            metric = ranking_metrics(scores, corpus, labels[job["job_id"]], features[:, 0] >= 0.6, k)
            recommended = metric.pop("recommended_ids")
            per_method.setdefault(name, []).append(metric)
            if count == 1:
                positions = {rid: index for index, rid in enumerate(corpus.ids)}
                examples[name] = {
                    "job_id": job["job_id"],
                    "recommended_ids": recommended,
                    "first_five": [
                        {
                            "resume_id": rid,
                            "score": float(scores[positions[rid]]),
                            "features": dict(
                                zip(FEATURE_NAMES, features[positions[rid]].tolist(), strict=True)
                            ),
                            "listed_positive": rid in labels[job["job_id"]],
                        }
                        for rid in recommended[:5]
                    ],
                }
        if count % 25 == 0:
            print(f"  Evaluated {count}/{len(jobs)} jobs", flush=True)
    summary = {}
    for name, records in per_method.items():
        means = {}
        for key in records[0]:
            values = [record[key] for record in records if record[key] is not None]
            means[key] = float(np.mean(values)) if values else None
        summary[name] = {
            "macro_mean": means,
            "jobs": len(records),
            "jobs_with_listed_positives": sum(record["listed_positive_count"] > 0 for record in records),
        }
    return {"candidate_pool": len(corpus.rows), "metrics": summary, "first_job_examples": examples}


def run(args: argparse.Namespace) -> dict:
    tables, checksums = load_tables(args.data_dir, args.download)
    labels = {row["job_id"]: set(row["relevant_resume_ids"]) for row in tables["matches"]}
    partitions = split_jobs(tables["jobs"], args.seed)
    corpora, diagnostics = resume_partitions(tables["resumes"], args.seed)
    diagnostics["job_split_counts"] = {key: len(value) for key, value in partitions.items()}
    diagnostics["unique_job_templates"] = sum(
        len(
            {
                json.dumps(
                    [
                        normalize_generator_skill(row["job_title"]),
                        normalize_generator_skill(row["seniority"]),
                        sorted(_skill_list(row["must_have_skills"])),
                        sorted(_skill_list(row["nice_to_have_skills"])),
                    ]
                )
                for row in values
            }
        )
        for values in partitions.values()
    )
    model = None
    model_info = None
    diagnostics["reused_job_description_rows"] = sum(
        count - 1 for count in Counter(row["description"] for row in tables["jobs"]).values()
    )
    diagnostics["reused_resume_bullet_rows"] = sum(
        count - 1 for count in Counter(tuple(row["experience_bullets"]) for row in tables["resumes"]).values()
    )
    if args.command == "train":
        xs, ys = [], []
        training_resume_ids = set(corpora["train"].ids)
        for count, job in enumerate(partitions["train"][: args.max_jobs], 1):
            indices, target = sample_training_indices(
                job,
                corpora["train"],
                labels[job["job_id"]] & training_resume_ids,
                args.seed,
                args.pairs_per_class,
            )
            if len(indices):
                xs.append(feature_matrix(job, corpora["train"])[indices])
                ys.append(target)
            if count % 25 == 0:
                print(f"  Prepared training pairs for {count} jobs", flush=True)
        if not xs:
            raise ValueError("No labeled training pairs in this partition")
        x, y = np.vstack(xs), np.concatenate(ys)
        print(f"Fitting {len(y):,} synthetic examples from training jobs/resumes only", flush=True)
        model = fit_logistic(x, y, l2=args.l2, epochs=args.epochs)
        model_info = model.to_dict()
        model_info.update(
            {
                "training_pairs": len(y),
                "positive_pairs": int(y.sum()),
                "negative_pairs": int(len(y) - y.sum()),
                "l2": args.l2,
                "epochs": args.epochs,
            }
        )

    results = {}
    # Validation is shown separately; no test observations enter fitting. CLI
    # hyperparameters must be selected using validation, not repeated test tuning.
    for name, job_group, corpus in (
        ("validation_jobs_training_resume_pool", "validation", corpora["train"]),
        ("test_jobs_training_resume_pool", "test", corpora["train"]),
        ("test_jobs_unseen_resume_pool", "test", corpora["test"]),
    ):
        jobs = partitions[job_group][: args.max_jobs]
        if not jobs:
            raise ValueError(f"No jobs in {job_group}; need more distinct templates")
        print(f"Evaluating {name}: {len(jobs)} jobs, {len(corpus.rows):,} resumes", flush=True)
        results[name] = evaluate(jobs, corpus, labels, args.k, model)

    report = {
        "target": "synthetic_relevance_only",
        "live_execution": False,
        "dataset": DATASET,
        "revision": None if args.data_dir else REVISION,
        "source": "local_override" if args.data_dir else "pinned_huggingface_files",
        "reference_revision": REVISION,
        "file_sha256": checksums,
        "command": args.command,
        "seed": args.seed,
        "k": args.k,
        "max_jobs_per_partition": args.max_jobs,
        "feature_names": list(FEATURE_NAMES),
        "limitations": LIMITATIONS,
        "diagnostics": diagnostics,
        "results": results,
        "model": model_info,
    }
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / f"{args.command}_report.json"
    report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if model_info is not None:
        (output / "synthetic_relevance_model.json").write_text(
            json.dumps(
                {
                    **model_info,
                    "dataset": DATASET,
                    "revision": report["revision"],
                    "seed": args.seed,
                    "source": report["source"],
                    "reference_revision": REVISION,
                    "file_sha256": checksums,
                    "limitations": LIMITATIONS,
                },
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
    print(f"\nReport: {report_file}")
    for scenario, result in results.items():
        print(f"\n{scenario}")
        for name, metrics in result["metrics"].items():
            means = metrics["macro_mean"]
            recall = means["listed_recall_at_k"]
            recall_text = "n/a" if recall is None else f"{recall:.1%}"
            print(
                f"  {name}: listed Recall@{args.k}={recall_text}; "
                f"rule-qualified Precision@{args.k}={means['threshold_precision_at_k']:.1%}"
            )
    print("\nSynthetic benchmark only. See report limitations; no live matching changed.")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("benchmark", "train"))
    parser.add_argument("--data-dir", type=Path, help="Local root with data/, jobs/, matches/ Parquet files")
    parser.add_argument(
        "--download", action="store_true", help="Allow downloading pinned files if not cached"
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "matching-research")
    parser.add_argument("--max-jobs", type=int, default=100, help="Maximum jobs PER split; 2500 covers all")
    parser.add_argument("--k", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pairs-per-class", type=int, default=30)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--epochs", type=int, default=500)
    args = parser.parse_args()
    if (
        min(args.max_jobs, args.k, args.pairs_per_class, args.epochs) < 1
        or not np.isfinite(args.l2)
        or args.l2 < 0
    ):
        parser.error("Counts must be positive and l2 finite and nonnegative")
    try:
        run(args)
    except (ValueError, FileNotFoundError, ImportError) as exc:
        parser.exit(1, f"Research check failed: {exc}\n")


if __name__ == "__main__":
    main()
