"""Prepare local unlabeled TalentCLEF test predictions; never submit them.

The strict published-positive artifact and its selected final policy are loaded
without fitting. A TREC-format run contains document identifiers and stays under
ignored .local storage. No external test score is available or implied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.matching.retrieval_relevance import PortableRetrievalRanker  # noqa: E402
from app.matching.text_relevance import TextFeatureIndex  # noqa: E402

from scripts.matching_text_benchmark import score_documents  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUN_TAG = "ck_public_positive_v1"


def test_predictions(
    source: Path, model: PortableRetrievalRanker, selected_policy: str
) -> tuple[str, dict[str, Any]]:
    """The caller must first validate the entire pinned source archive inventory."""
    if selected_policy not in {"LISTWISE_ML", "TFIDF_FALLBACK"}:
        raise ValueError("An explicitly selected final policy is required.")
    with zipfile.ZipFile(source) as archive:

        def documents(prefix: str) -> dict[str, str]:
            values = {
                name.removeprefix(prefix): archive.read(name).decode("utf-8-sig").strip()
                for name in archive.namelist()
                if name.startswith(prefix) and not name.endswith("/")
            }
            if any(not value or "\x00" in value for value in values.values()):
                raise ValueError("Test documents must be nonempty UTF-8 text.")
            return values

        jobs = documents("TaskA/test/en/queries/")
        candidates = documents("TaskA/test/en/corpus/")
    if len(jobs) != 40 or len(candidates) != 476:
        raise ValueError("Expected exactly 40 unlabeled English test jobs and 476 candidates.")
    candidate_ids = sorted(candidates)
    texts = [candidates[key] for key in candidate_ids]
    index = TextFeatureIndex(texts)
    lines = []
    for job, query in sorted(jobs.items()):
        scores = (
            model.score_features(index.features(query))
            if selected_policy == "LISTWISE_ML"
            else tuple(score_documents(query, texts)["tfidf_cosine"])
        )
        ranking = sorted(zip(candidate_ids, scores, strict=True), key=lambda value: (-value[1], value[0]))
        for rank, (candidate, score) in enumerate(ranking, 1):
            lines.append(f"{job}\tQ0\t{candidate}\t{rank}\t{score:.17g}\t{RUN_TAG}")
    run = "\n".join(lines) + "\n"
    return run, {
        "target": model.to_dict()["target"],
        "model_sha256": model.to_dict()["model_sha256"],
        "selected_policy": selected_policy,
        "queries": len(jobs),
        "candidate_pool": len(candidates),
        "prediction_rows": len(lines),
        "submission_sha256": hashlib.sha256(run.encode()).hexdigest(),
        "format": "TREC: query_id Q0 candidate_id rank score run_tag; tab separated",
        "run_tag": RUN_TAG,
        "labels_available": False,
        "external_submission_performed": False,
        "external_accuracy": None,
        "production_eligible": False,
        "tie_break": "candidate ID only for unlabeled submission formatting; scored development metrics use tie expectations",
    }


def prepare(source: Path, artifact: Path, policy_report: Path, output: Path) -> dict[str, Any]:
    from scripts.talentclef_source import load_source

    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a fresh immutable prediction directory.")
    if not output.resolve().is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Individual test predictions must stay in ignored workspace .local storage.")
    model_bytes, policy_bytes = artifact.read_bytes(), policy_report.read_bytes()
    model = PortableRetrievalRanker.from_dict(json.loads(model_bytes))
    report = json.loads(policy_bytes)
    if report.get("model_sha256") != model.to_dict()["model_sha256"]:
        raise ValueError("The final policy report must describe this exact model.")
    selected = report.get("final_model_policy", {}).get("selected_policy")
    _, _, _, provenance = load_source(source)
    run, summary = test_predictions(source, model, selected)
    if artifact.read_bytes() != model_bytes or policy_report.read_bytes() != policy_bytes:
        raise ValueError("Model or final policy changed during prediction.")
    summary["source_archive_sha256"] = provenance["archive_sha256"]
    summary["implementation_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".retrieval-test-predictions-", dir=output.parent) as temporary:
        staged = Path(temporary) / "complete"
        staged.mkdir()
        (staged / "talentclef-test-en.run").write_text(run, encoding="utf-8")
        (staged / "report.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        if output.exists() or output.is_symlink():
            raise FileExistsError("Prediction output appeared during execution.")
        staged.rename(output)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--talent-source", type=Path, default=Path(".local/matching-accuracy/talentclef/source/TaskA.zip")
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--policy-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.talent_source, args.artifact, args.policy_report, args.output), indent=2))


if __name__ == "__main__":
    main()
