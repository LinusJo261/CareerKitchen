"""Pinned, offline human-ranking benchmark for lexical retrieval, never live matching.

Annotations order five vacancies for each CV, rather than CVs for each vacancy.
No parameters are selected against these labels. Raw documents stay in .local.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

SOURCE_REPOSITORY = "https://github.com/NataliaVanetik/vacancy-resume-matching-dataset"
SOURCE_COMMIT = "7ee8f043c6e31ee94cb67f5e60b069901b533adf"
ARCHIVE_SHA256 = "a30003477335398662c853125df17eae5493f72229225ab8e4becc7dbf7b0bba"
ARCHIVE_URL = (
    f"https://codeload.github.com/NataliaVanetik/vacancy-resume-matching-dataset/zip/{SOURCE_COMMIT}"
)
ROOT = f"vacancy-resume-matching-dataset-{SOURCE_COMMIT}/"
ANNOTATIONS = "annotations-for-the-first-30-vacancies.txt"
CITATION = (
    "Vanetik, Natalia, and Genady Kogan. 2023. Job Vacancy Ranking with Sentence "
    "Embeddings, Keywords, and Named Entities. Information 14(8), 468. "
    "https://doi.org/10.3390/info14080468"
)
PROTOCOL_VERSION = "five-vacancy-human-lexical-v1"
METHODS = ("lexical_jaccard", "bm25", "tfidf_cosine")
FIXED_PARAMETERS = {
    "bm25": {"k1": 1.2, "b": 0.75, "query_term_frequency": "binary", "idf": "log(1+(N-df+.5)/(df+.5))"},
    "tfidf_cosine": {"term_frequency": "raw_count", "idf": "1+log((N+1)/(df+1))", "normalization": "l2"},
    "index": "five vacancy titles plus descriptions; IDF fitted only to those five jobs",
    "tokenizer": "NFKC casefold; Unicode words with optional +/# suffixes and dotted segments",
    "stopwords": "none",
    "stemming": "none",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_source(archive: Path) -> None:
    """Download only the pinned archive, with TLS checks and no partial publication."""
    if archive.exists():
        raise FileExistsError(f"Source already exists: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=archive.parent) as temporary:
        staged = Path(temporary) / "repository.zip"
        subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "120",
                ARCHIVE_URL,
                "--output",
                str(staged),
            ],
            check=True,
        )
        if _sha256(staged.read_bytes()) != ARCHIVE_SHA256:
            raise ValueError("Downloaded archive differs from the pinned SHA256.")
        # Hard-link publication is atomic and refuses an existing destination.
        os.link(staged, archive)


def docx_text(data: bytes) -> str:
    """Read document paragraphs and tables without extracting or executing a DOCX."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > 5_000_000:
            raise ValueError("DOCX document XML exceeds the research size limit.")
        document = ET.fromstring(archive.read(info))
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = [
        "".join(element.text or "" for element in paragraph.iter(namespace + "t"))
        for paragraph in document.iter(namespace + "p")
    ]
    text = "\n".join(paragraphs).strip()
    if not text:
        raise ValueError("A source DOCX has no document text.")
    return text


def parse_annotations(text: str) -> tuple[dict[str, list[list[int] | None]], dict[str, int]]:
    """Safely parse literal assignments; exclude malformed orders without repair.

    The source defines position in each array as best-to-worst vacancy order.
    Duplicate IDs therefore are malformed orders, rather than ordinal ties.
    """
    start = text.find("ANNOTATOR_1_RANKINGS=")
    if start < 0:
        raise ValueError("Missing annotation assignments.")
    tree = ast.parse(text[start:])
    result: dict[str, list[list[int] | None]] = {}
    excluded: dict[str, int] = {}
    expected = {"ANNOTATOR_1_RANKINGS", "ANNOTATOR_2_RANKINGS"}
    for assignment in tree.body:
        if (
            not isinstance(assignment, ast.Assign)
            or len(assignment.targets) != 1
            or not isinstance(assignment.targets[0], ast.Name)
            or assignment.targets[0].id not in expected
            or assignment.targets[0].id in result
        ):
            raise ValueError("Only two known literal annotation assignments are accepted.")
        name = assignment.targets[0].id
        rows = ast.literal_eval(assignment.value)
        if not isinstance(rows, list) or len(rows) != 30:
            raise ValueError("Each annotator must provide exactly 30 indexed CV rows.")
        result[name] = []
        excluded[name] = 0
        for row in rows:
            valid = (
                isinstance(row, list)
                and len(row) == 5
                and all(type(value) is int for value in row)
                and set(row) == {1, 2, 3, 4, 5}
            )
            result[name].append(row if valid else None)
            excluded[name] += int(not valid)
    if set(result) != expected:
        raise ValueError("Both independent annotators are required.")
    return result, excluded


def load_source(archive_path: Path) -> tuple[list[str], list[str], dict[str, list], dict[str, Any]]:
    data = archive_path.read_bytes()
    if _sha256(data) != ARCHIVE_SHA256:
        raise ValueError("Source archive differs from the pinned SHA256.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        expected = {ROOT + f"CV/{index}.docx" for index in range(1, 66)} | {
            ROOT + name
            for name in (
                "5_vacancies.csv",
                "LICENSE",
                "README.md",
                "annotation_instructions.docx",
                ANNOTATIONS,
            )
        }
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("Pinned source inventory does not match the documented 65 CVs and metadata.")
        files = {name.removeprefix(ROOT): archive.read(name) for name in names}
    if b"GNU GENERAL PUBLIC LICENSE" not in files["LICENSE"] or b"Version 3" not in files["LICENSE"]:
        raise ValueError("Expected source GPL-3.0 license is missing.")
    records = list(csv.DictReader(io.StringIO(files["5_vacancies.csv"].decode("utf-8-sig"))))
    # Human IDs 1..5 refer to CSV row position, not its original IDs 8,37,90,207,499.
    if [row["id"] for row in records] != ["8", "37", "90", "207", "499"]:
        raise ValueError("The annotation-to-vacancy CSV row join changed.")
    jobs = [row["job_title"] + "\n" + row["job_description"] for row in records]
    if any(not text.strip() for text in jobs):
        raise ValueError("All five vacancies require text.")
    resumes = [docx_text(files[f"CV/{index}.docx"]) for index in range(1, 31)]
    annotations, excluded = parse_annotations(files[ANNOTATIONS].decode("utf-8-sig"))
    docx_text(files["annotation_instructions.docx"])
    provenance = {
        "repository": SOURCE_REPOSITORY,
        "commit": SOURCE_COMMIT,
        "archive_url": ARCHIVE_URL,
        "archive_sha256": ARCHIVE_SHA256,
        "license": "GPL-3.0 source repository; source license remains inside the local archive",
        "citation": CITATION,
        "all_file_sha256": {name: _sha256(value) for name, value in sorted(files.items())},
        "source_cv_count": 65,
        "evaluated_cv_count": 30,
        "vacancy_count": 5,
        "annotation_semantics": "Each CV row is an ordered list of vacancy IDs 1..5, best first; IDs map to CSV row position.",
        "malformed_annotation_rows_excluded_by_rater": excluded,
        "exclusion_policy": "Skip only the malformed rater/query row; retain the other rater; no inferred repairs.",
    }
    return jobs, resumes, annotations, provenance


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:[+#]+)?(?:\.[^\W_]+)*", unicodedata.normalize("NFKC", text).casefold())


def score_documents(query: str, documents: list[str]) -> dict[str, list[float]]:
    """Fixed lexical baselines with document statistics independent of labels."""
    if not documents or any(not text.strip() for text in documents):
        raise ValueError("A nonempty text corpus is required.")
    counters = [Counter(tokens(text)) for text in documents]
    query_counter = Counter(tokens(query))
    frequency = Counter(token for counter in counters for token in counter)
    count = len(counters)
    lengths = [sum(counter.values()) for counter in counters]
    mean_length = sum(lengths) / count
    if not mean_length:
        raise ValueError("The document corpus has no tokens.")
    idf = {token: 1 + math.log((count + 1) / (df + 1)) for token, df in frequency.items()}
    query_vector = {token: value * idf[token] for token, value in query_counter.items() if token in idf}
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    scores: dict[str, list[float]] = {method: [] for method in METHODS}
    for counter, length in zip(counters, lengths, strict=True):
        union = set(counter) | set(query_counter)
        scores["lexical_jaccard"].append(
            len(set(counter) & set(query_counter)) / len(union) if union else 0.0
        )
        bm25 = 0.0
        for token in query_counter:
            tf = counter[token]
            if not tf:
                continue
            df = frequency[token]
            bm25 += (
                math.log(1 + (count - df + 0.5) / (df + 0.5))
                * (tf * 2.2)
                / (tf + 1.2 * (0.25 + 0.75 * length / mean_length))
            )
        scores["bm25"].append(bm25)
        document_vector = {token: value * idf[token] for token, value in counter.items()}
        document_norm = math.sqrt(sum(value * value for value in document_vector.values()))
        dot = sum(value * document_vector.get(token, 0) for token, value in query_vector.items())
        scores["tfidf_cosine"].append(
            dot / (query_norm * document_norm) if query_norm and document_norm else 0.0
        )
    return scores


def ranking_metrics(scores: list[float], human_order: list[int]) -> dict[str, float]:
    """Expected metrics under uniformly random ordering within exact score ties."""
    size = len(scores)
    if size < 2 or any(not math.isfinite(score) for score in scores):
        raise ValueError("At least two finite scores are required.")
    if len(human_order) != size or set(human_order) != set(range(1, size + 1)):
        raise ValueError("Human order must be a permutation of document IDs.")
    positions = {document_id: index for index, document_id in enumerate(human_order)}
    agreements = []
    for left in range(size):
        for right in range(left + 1, size):
            difference = scores[left] - scores[right]
            agrees = (difference > 0) == (positions[left + 1] < positions[right + 1])
            agreements.append(0.5 if difference == 0 else float(agrees))
    best = scores[human_order[0] - 1]
    greater = sum(score > best for score in scores)
    tied = sum(score == best for score in scores)
    return {
        "pairwise_agreement": sum(agreements) / len(agreements),
        "top1_agreement": 1 / tied if greater == 0 else 0.0,
        "mrr_human_first_choice": sum(1 / rank for rank in range(greater + 1, greater + tied + 1)) / tied,
        "score_pair_tie_rate": sum(
            scores[left] == scores[right] for left in range(size) for right in range(left + 1, size)
        )
        / len(agreements),
    }


def evaluate(jobs: list[str], resumes: list[str], annotations: dict[str, list]) -> dict[str, Any]:
    if (
        len(jobs) != 5
        or len(resumes) != 30
        or set(annotations) != {"ANNOTATOR_1_RANKINGS", "ANNOTATOR_2_RANKINGS"}
    ):
        raise ValueError("The fixed benchmark requires 30 CVs, five jobs, and two raters.")
    if any(len(rows) != 30 for rows in annotations.values()):
        raise ValueError("Every annotation row must retain its original CV position.")
    predictions = [score_documents(resume, jobs) for resume in resumes]
    metrics: dict[str, Any] = {}
    for method in METHODS:
        per_rater = {}
        all_metrics = []
        for rater, rows in sorted(annotations.items()):
            observations = [
                ranking_metrics(predictions[index][method], order)
                for index, order in enumerate(rows)
                if order is not None
            ]
            if not observations:
                raise ValueError("Each rater needs at least one valid query.")
            per_rater[rater] = {
                "queries": len(observations),
                **{key: sum(row[key] for row in observations) / len(observations) for key in observations[0]},
            }
            all_metrics.extend(observations)
        metrics[method] = {
            "per_rater": per_rater,
            "pooled_query_rater": {
                key: sum(row[key] for row in all_metrics) / len(all_metrics) for key in all_metrics[0]
            },
            "pooled_query_rater_count": len(all_metrics),
        }
    first, second = annotations["ANNOTATOR_1_RANKINGS"], annotations["ANNOTATOR_2_RANKINGS"]
    comparisons = []
    for left, right in zip(first, second, strict=True):
        if left is None or right is None:
            continue
        # Exact human ordering scores, no fabricated consensus or cardinal gains.
        scores = [float(5 - left.index(document_id)) for document_id in range(1, 6)]
        comparisons.append(ranking_metrics(scores, right))
    if not comparisons:
        raise ValueError("No valid shared queries for rater agreement.")
    return {
        "methods": metrics,
        "human_inter_rater_agreement": {
            "shared_valid_queries": len(comparisons),
            "pairwise_agreement": sum(row["pairwise_agreement"] for row in comparisons) / len(comparisons),
            "top1_agreement": sum(row["top1_agreement"] for row in comparisons) / len(comparisons),
        },
        "uniform_random_expected": {
            "pairwise_agreement": 0.5,
            "top1_agreement": 0.2,
            "mrr_human_first_choice": sum(1 / rank for rank in range(1, 6)) / 5,
        },
    }


def run_benchmark(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    jobs, resumes, annotations, provenance = load_source(source)
    results = evaluate(jobs, resumes, annotations)
    # Independent replay detects accidental stateful corpus fitting or unstable ranking.
    if results != evaluate(jobs, resumes, annotations):
        raise ValueError("Deterministic benchmark replay differs.")
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "source": provenance,
        "fixed_parameters": FIXED_PARAMETERS,
        "label_training_or_tuning": False,
        "offline_only": True,
        "aggregate_only": True,
        "deterministic_replay_verified": True,
        "results": results,
        "limitations": [
            "Thirty software-developer CV queries and five fixed vacancies are a small, narrow benchmark, not a hiring-accuracy estimate.",
            "Annotations rank vacancies per CV; they cannot be inverted into labeled rankings of candidates per job.",
            "Two CS-background human annotators followed senior HR guidance; their disagreement is retained, not replaced with a consensus label.",
            "Source documentation explicitly defines ordered vacancy IDs; malformed permutations are excluded without guessing repairs.",
            "All three methods are lexical text retrieval, not semantic embedding models or calibrated match probabilities.",
            "The existing five-feature Model A cannot be replayed because trusted structured required/preferred skills are unavailable; none were invented.",
            "No mutual interest, employer outcomes, satisfaction, eligibility, or essential-requirement checks are evaluated.",
            "Pairwise agreement gives predicted ties half credit; top1 and MRR average uniformly over tied score positions.",
            "MRR concerns each rater's first choice only; ordinal annotations do not justify cardinal NDCG gains.",
            "Pooled query-rater observations are correlated; results are descriptive and no significance or superiority claim is made.",
            "The original paper reports different text preprocessing and methods; these results do not reproduce its reported scores.",
            "The repository provides GPL-3.0 source; third-party vacancy provenance is retained and raw source data are not redistributed by this project.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".benchmark-", dir=output.parent) as temporary:
        staged = Path(temporary) / "result"
        staged.mkdir()
        (staged / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        (staged / "protocol.json").write_text(
            json.dumps(
                {"version": PROTOCOL_VERSION, "parameters": FIXED_PARAMETERS, "source": provenance},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        if output.exists():
            raise FileExistsError("Output appeared during evaluation; refusing to replace it.")
        staged.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path(".local/matching-human-benchmark/source/repository.zip")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download and hash-check the pinned public archive using curl.",
    )
    arguments = parser.parse_args()
    if arguments.download:
        download_source(arguments.source)
    report = run_benchmark(arguments.source, arguments.output)
    print("Human vacancy-ranking lexical benchmark; offline, descriptive, no label tuning")
    for method, result in report["results"]["methods"].items():
        metrics = result["pooled_query_rater"]
        print(
            f"{method}: pairwise={metrics['pairwise_agreement']:.4f}, top1={metrics['top1_agreement']:.4f}, MRR={metrics['mrr_human_first_choice']:.4f}"
        )
    print(f"Aggregate report: {arguments.output / 'report.json'}")


if __name__ == "__main__":
    main()
