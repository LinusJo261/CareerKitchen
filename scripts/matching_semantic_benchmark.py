"""Frozen, pinned MiniLM comparison on the small human vacancy-ranking benchmark.

This is an offline retrieval experiment. Model loading is local and safetensors
only; source text and human orderings never appear in published experiment files.
The optional deep-learning dependencies are imported only for actual inference.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import tempfile
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from scripts import matching_text_benchmark as lexical

MODEL_REPOSITORY = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
# SHA256 published by the official pinned Hugging Face file page. Every local
# inference/config file is also fingerprinted below.
MODEL_WEIGHTS_SHA256 = "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"
PROTOCOL_VERSION = "five-vacancy-human-frozen-minilm-v1"
SEMANTIC_METHOD = "minilm_chunked_cosine"
DIMENSIONS = 384
CHUNK_TOKENS = 200
OVERLAP_TOKENS = 40
BATCH_SIZE = 32
BERT_CLS_TOKEN_ID = 101
BERT_SEP_TOKEN_ID = 102
BERT_PAD_TOKEN_ID = 0
MODEL_FILES = frozenset(
    {
        "README.md",
        "model.safetensors",
        "config.json",
        "config_sentence_transformers.json",
        "modules.json",
        "sentence_bert_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.txt",
        "1_Pooling/config.json",
    }
)
OPTIONAL_MODEL_FILES = frozenset({"2_Normalize/config.json", "LICENSE", ".gitattributes"})
EMBEDDING_PARAMETERS = {
    "tokenizer": "pinned model tokenizer; add_special_tokens=False, truncation=False",
    "chunk_tokens": CHUNK_TOKENS,
    "overlap_tokens": OVERLAP_TOKENS,
    "chunk_boundary": "contiguous tokenizer IDs; no decode/re-tokenization",
    "special_tokens": "pinned BERT CLS=101, SEP=102; right PAD=0; zero token_type_ids; padding attention masked",
    "coverage": "all tokens, including document tail; no document truncation",
    "chunk_embedding": "pinned Transformer/Pooling/Normalize modules; L2-normalize each vector",
    "document_embedding": "equal mean over all chunk vectors, then L2-normalize",
    "similarity": "cosine of normalized document vectors; no lexical/semantic blending",
    "text": "complete source CV text versus vacancy title + newline + description",
    "batch_size": BATCH_SIZE,
    "dimensions": DIMENSIONS,
    "device": "cpu",
    "dtype": "float32 inference; float64 aggregation and cosine",
    "torch_threads": 1,
    "torch_seed": 0,
    "training": "none; frozen pretrained weights and fixed parameters",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def software_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for package in (
        "numpy",
        "torch",
        "sentence-transformers",
        "transformers",
        "tokenizers",
        "huggingface-hub",
        "safetensors",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def verify_model_snapshot(model_dir: Path) -> dict[str, Any]:
    """Reject executable/unsafe model formats and fingerprint the exact snapshot."""
    if not model_dir.is_dir():
        raise FileNotFoundError(f"Pinned local model directory is missing: {model_dir}")
    if any(path.is_symlink() for path in model_dir.rglob("*")):
        raise ValueError("The local model snapshot must contain regular files, not symlinks.")
    files = {path.relative_to(model_dir).as_posix(): path for path in model_dir.rglob("*") if path.is_file()}
    if not MODEL_FILES <= set(files) or set(files) - MODEL_FILES - OPTIONAL_MODEL_FILES:
        raise ValueError("Local model inventory differs from the fixed safe inference files.")
    hashes = {name: _sha256(path.read_bytes()) for name, path in sorted(files.items())}
    if hashes["model.safetensors"] != MODEL_WEIGHTS_SHA256:
        raise ValueError("Model weights differ from the pinned remote safetensors SHA256.")
    readme = files["README.md"].read_text()
    if not re.search(r"(?m)^license:\s*apache-2\.0\s*$", readme):
        raise ValueError("The pinned model card must retain its Apache-2.0 license declaration.")
    modules = json.loads(files["modules.json"].read_text())
    allowed = [
        {"idx": 0, "name": "0", "path": "", "type": "sentence_transformers.models.Transformer"},
        {"idx": 1, "name": "1", "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"},
        {"idx": 2, "name": "2", "path": "2_Normalize", "type": "sentence_transformers.models.Normalize"},
    ]
    if modules not in (allowed, allowed[:2]):
        raise ValueError("Only the known built-in Transformer/Pooling/Normalize modules are allowed.")
    config = json.loads(files["config.json"].read_text())
    if config.get("model_type") != "bert" or config.get("hidden_size") != DIMENSIONS:
        raise ValueError("The pinned MiniLM architecture changed.")
    for name, path in files.items():
        if name.endswith(".json") and "auto_map" in path.read_text():
            raise ValueError("Dynamic model/tokenizer auto_map code is not permitted.")
    return {
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "license": "Apache-2.0, declared by the pinned model README retained locally",
        "all_file_sha256": hashes,
        "weights_format": "safetensors only",
        "remote_code": False,
        "local_files_only": True,
    }


def token_chunks(token_ids: list[int]) -> list[list[int]]:
    """Cover the entire input once with fixed overlapping windows, including tail."""
    if not token_ids or any(type(value) is not int or value < 0 for value in token_ids):
        raise ValueError("Each nonempty document requires nonnegative integer token IDs.")
    chunks = []
    start = 0
    while start < len(token_ids):
        end = min(start + CHUNK_TOKENS, len(token_ids))
        chunks.append(token_ids[start:end])
        if end == len(token_ids):
            break
        start += CHUNK_TOKENS - OVERLAP_TOKENS
    return chunks


def bert_batch_inputs(chunks: list[list[int]]) -> dict[str, list[list[int]]]:
    """Construct the pinned single-sequence BERT template from unmodified IDs.

    The pinned tokenizer's single template is CLS:0 $A:0 SEP:0 with right
    padding. Building this directly also supports tokenizer versions that no
    longer expose prepare_for_model. Attention masks exclude padding from mean
    pooling while all original chunk IDs remain attended.
    """
    if (
        not chunks
        or len(chunks) > BATCH_SIZE
        or any(
            not chunk
            or len(chunk) > CHUNK_TOKENS
            or any(type(value) is not int or value < 0 for value in chunk)
            for chunk in chunks
        )
    ):
        raise ValueError("A batch requires 1..32 nonempty windows of at most 200 integer token IDs.")
    width = max(len(chunk) for chunk in chunks) + 2
    inputs: dict[str, list[list[int]]] = {"input_ids": [], "attention_mask": [], "token_type_ids": []}
    for chunk in chunks:
        size = len(chunk) + 2
        inputs["input_ids"].append(
            [BERT_CLS_TOKEN_ID, *chunk, BERT_SEP_TOKEN_ID] + [BERT_PAD_TOKEN_ID] * (width - size)
        )
        inputs["attention_mask"].append([1] * size + [0] * (width - size))
        inputs["token_type_ids"].append([0] * width)
    return inputs


class ChunkEncoder(Protocol):
    def token_ids(self, text: str) -> list[int]: ...

    def encode_chunks(self, chunks: list[list[int]]) -> np.ndarray: ...


class FrozenMiniLM:
    """Small local-only adapter; no torch dependency for parsing or unit tests."""

    def __init__(self, model_dir: Path):
        # SentenceTransformer's module/config paths were checked before loading.
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(1)
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        self.torch = torch
        self.model = SentenceTransformer(
            str(model_dir.resolve()),
            device="cpu",
            trust_remote_code=False,
            local_files_only=True,
            model_kwargs={"use_safetensors": True},
        )
        self.model.float().eval()
        self.tokenizer = self.model.tokenizer
        if (
            self.tokenizer.cls_token_id,
            self.tokenizer.sep_token_id,
            self.tokenizer.pad_token_id,
            self.tokenizer.padding_side,
            self.tokenizer.num_special_tokens_to_add(pair=False),
        ) != (BERT_CLS_TOKEN_ID, BERT_SEP_TOKEN_ID, BERT_PAD_TOKEN_ID, "right", 2):
            raise ValueError("The pinned tokenizer's BERT special tokens or padding changed.")
        # Check direct-ID special-token construction against the actual library
        # tokenizer on a fixed non-benchmark string before any model inference.
        probe = "offline protocol check"
        probe_ids = self.token_ids(probe)
        reference = self.tokenizer(
            probe,
            add_special_tokens=True,
            truncation=False,
            return_attention_mask=True,
            return_token_type_ids=True,
        )
        expected = bert_batch_inputs([probe_ids])
        if any(list(reference[key]) != values[0] for key, values in expected.items()):
            raise ValueError("Direct-ID BERT input construction differs from the pinned tokenizer.")
        needed = CHUNK_TOKENS + self.tokenizer.num_special_tokens_to_add(pair=False)
        if needed > self.model.max_seq_length or needed > self.tokenizer.model_max_length:
            raise ValueError("Fixed windows plus special tokens exceed the pinned model token limit.")

    def token_ids(self, text: str) -> list[int]:
        return list(
            self.tokenizer(
                text,
                add_special_tokens=False,
                truncation=False,
                return_attention_mask=False,
                return_token_type_ids=False,
                verbose=False,
            )["input_ids"]
        )

    def encode_chunks(self, chunks: list[list[int]]) -> np.ndarray:
        batches = []
        with self.torch.inference_mode():
            for start in range(0, len(chunks), BATCH_SIZE):
                features = {
                    key: self.torch.tensor(values, dtype=self.torch.long, device="cpu")
                    for key, values in bert_batch_inputs(chunks[start : start + BATCH_SIZE]).items()
                }
                embedding = self.model(features)["sentence_embedding"]
                batches.append(embedding.detach().cpu().float().numpy())
        return np.concatenate(batches, axis=0)


def _normalized(vectors: np.ndarray, rows: int) -> np.ndarray:
    values = np.asarray(vectors, dtype=np.float64)
    if values.shape != (rows, DIMENSIONS) or not np.isfinite(values).all():
        raise ValueError("Embedding shape or finite values differ from the fixed 384-dimensional model.")
    norms = np.linalg.norm(values, axis=1)
    if np.any(norms <= 0):
        raise ValueError("Zero-length embedding vectors are not valid cosine inputs.")
    return values / norms[:, None]


def embed_documents(texts: list[str], encoder: ChunkEncoder) -> tuple[np.ndarray, dict[str, Any]]:
    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Nonempty complete document text is required.")
    chunks = []
    counts = []
    token_counts = []
    for text in texts:
        ids = encoder.token_ids(text)
        document_chunks = token_chunks(ids)
        chunks.extend(document_chunks)
        counts.append(len(document_chunks))
        token_counts.append(len(ids))
    chunk_vectors = _normalized(encoder.encode_chunks(chunks), len(chunks))
    vectors = []
    start = 0
    for count in counts:
        vectors.append(np.mean(chunk_vectors[start : start + count], axis=0))
        start += count
    normalized = _normalized(np.asarray(vectors), len(texts))
    return normalized, {
        "documents": len(texts),
        "chunks": len(chunks),
        "min_tokens_per_document": min(token_counts),
        "max_tokens_per_document": max(token_counts),
        "max_chunks_per_document": max(counts),
        "documents_with_multiple_chunks": sum(count > 1 for count in counts),
        "truncated_documents": 0,
    }


def _semantic_metrics(scores: np.ndarray, annotations: dict[str, list]) -> dict[str, Any]:
    if scores.shape != (30, 5) or not np.isfinite(scores).all():
        raise ValueError("The fixed benchmark requires 30 by five finite cosine scores.")
    per_rater = {}
    all_observations = []
    for rater, rows in sorted(annotations.items()):
        observations = [
            lexical.ranking_metrics(scores[index].tolist(), order)
            for index, order in enumerate(rows)
            if order is not None
        ]
        if not observations:
            raise ValueError("Each independent rater requires valid annotation rows.")
        per_rater[rater] = {
            "queries": len(observations),
            **{key: sum(row[key] for row in observations) / len(observations) for key in observations[0]},
        }
        all_observations.extend(observations)
    return {
        "per_rater": per_rater,
        "pooled_query_rater": {
            key: sum(row[key] for row in all_observations) / len(all_observations)
            for key in all_observations[0]
        },
        "pooled_query_rater_count": len(all_observations),
    }


def evaluate(
    jobs: list[str], resumes: list[str], annotations: dict[str, list], vectors: np.ndarray
) -> dict[str, Any]:
    """Use unchanged lexical baselines and the same tie-aware human metrics."""
    result = lexical.evaluate(jobs, resumes, annotations)
    normalized = _normalized(vectors, 35)
    if not np.allclose(normalized, vectors, atol=1e-12, rtol=0):
        raise ValueError("Document embeddings must already be normalized.")
    scores = np.clip(normalized[5:] @ normalized[:5].T, -1.0, 1.0)
    result["methods"][SEMANTIC_METHOD] = _semantic_metrics(scores, annotations)
    return result


def run_benchmark(
    source: Path,
    model_dir: Path,
    output: Path,
    *,
    encoder: ChunkEncoder | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    model_provenance = verify_model_snapshot(model_dir)
    jobs, resumes, annotations, provenance = lexical.load_source(source)
    versions = software_versions()
    protocol = {
        "version": PROTOCOL_VERSION,
        "parameters_predeclared_before_scoring": True,
        "embedding_parameters": EMBEDDING_PARAMETERS,
        "lexical_parameters_unchanged": lexical.FIXED_PARAMETERS,
        "source": provenance,
        "model": model_provenance,
        "software": versions,
        "implementation_sha256": {
            Path(__file__).name: _sha256(Path(__file__).read_bytes()),
            Path(lexical.__file__).name: _sha256(Path(lexical.__file__).read_bytes()),
        },
        "label_training_or_tuning": False,
        "random_seed_search": False,
        "source_text_or_individual_rankings_exported": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".semantic-", dir=output.parent) as temporary:
        staged = Path(temporary) / "result"
        staged.mkdir()
        protocol_data = _json_bytes(protocol)
        (staged / "protocol.json").write_bytes(protocol_data)
        # Protocol and configuration are serialized before model inference or scoring.
        documents = jobs + resumes
        vectors, stats = embed_documents(documents, FrozenMiniLM(model_dir) if encoder is None else encoder)
        cache = {
            "schema": 1,
            "protocol_sha256": _sha256(protocol_data),
            "document_order": "five vacancies in CSV order, then first 30 CVs in numeric order",
            "document_text_sha256": [_sha256(text.encode()) for text in documents],
            "vectors": vectors.tolist(),
            "aggregate_chunk_statistics": stats,
        }
        cache_data = _json_bytes(cache)
        (staged / "embeddings.json").write_bytes(cache_data)
        results = evaluate(jobs, resumes, annotations, vectors)
        restored = json.loads((staged / "embeddings.json").read_text())
        if restored["protocol_sha256"] != _sha256(protocol_data) or results != evaluate(
            jobs, resumes, annotations, np.asarray(restored["vectors"])
        ):
            raise ValueError("JSON embedding-cache replay differs from the original aggregate result.")
        report = {
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": _sha256(protocol_data),
            "source": provenance,
            "model": model_provenance,
            "software": versions,
            "fixed_parameters": EMBEDDING_PARAMETERS,
            "offline_only": True,
            "aggregate_only": True,
            "label_training_or_tuning": False,
            "deterministic_cache_replay_verified": True,
            "aggregate_chunk_statistics": stats,
            "embedding_cache": {
                "file": "embeddings.json",
                "sha256": _sha256(cache_data),
                "contents": "document hashes and embedding vectors; no text, scores, or human orderings",
            },
            "results": results,
            "limitations": [
                "Thirty CVs and five fixed vacancies are small and narrow; 58 pooled rater/query observations are correlated, not independent people.",
                "Two independent raters are retained separately; two malformed rows are excluded without guessed repairs.",
                "The benchmark ranks jobs for each CV, not candidates for each job, and cannot supply inverted candidate-ranking labels.",
                "No training or parameter/seed search uses these labels, but earlier lexical results have already been inspected; this is an exploratory model comparison.",
                "The model is general-purpose English text similarity; it has no app outcomes, employer decisions, essential requirements, or mutual-interest labels.",
                "Frozen pretrained embeddings may contain societal biases and their original training overlap with these public documents is unknown.",
                "All document tokens are covered; equal averaging of overlapping chunks can dilute specific skills and double-count boundary context.",
                "This is not a direct replay or accuracy estimate for structured five-feature Model A; missing required/preferred skill fields are not inferred.",
                "No reliability, calibrated match probability, hiring-success improvement, or statistically reliable winning method is established.",
                "GPL-3.0 source and Apache-2.0 model card remain local with hashes; raw source documents and individual human rankings are not redistributed.",
                "Cache replay checks serialization and deterministic aggregate calculations, not numerical identity across hardware or library versions.",
            ],
        }
        (staged / "report.json").write_bytes(_json_bytes(report))
        if output.exists():
            raise FileExistsError("Output appeared during evaluation; refusing to overwrite it.")
        staged.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path(".local/matching-human-benchmark/source/repository.zip")
    )
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = run_benchmark(arguments.source, arguments.model_dir, arguments.output)
    print("Frozen MiniLM human vacancy-ranking comparison; offline and descriptive")
    for method, result in report["results"]["methods"].items():
        metrics = result["pooled_query_rater"]
        print(
            f"{method}: pairwise={metrics['pairwise_agreement']:.4f}, top1={metrics['top1_agreement']:.4f}, MRR={metrics['mrr_human_first_choice']:.4f}"
        )
    print(f"Aggregate report: {arguments.output / 'report.json'}")


if __name__ == "__main__":
    main()
