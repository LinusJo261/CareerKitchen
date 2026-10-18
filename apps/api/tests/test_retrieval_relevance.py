"""Portable public-positive artifacts cannot masquerade as outcome models."""

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.matching.learning import validate_artifact
from app.matching.retrieval_relevance import MODEL_TARGET, PortableRetrievalRanker
from app.matching.text_relevance import FEATURE_NAMES, PortableTextRanker, artifact_digest


def fixture():
    return PortableRetrievalRanker(
        means=(0.0,) * len(FEATURE_NAMES),
        scales=(1.0,) * len(FEATURE_NAMES),
        coefficients=(0.5,) * len(FEATURE_NAMES),
        regularization=1.0,
        source_sha256="a" * 64,
        training_job_clusters=5,
        training_positive_judgments=10,
        candidate_corpus_size=4,
    )


def test_portable_artifact_roundtrip_and_target():
    model = fixture()
    value = model.to_dict()
    assert value["target"] == MODEL_TARGET
    assert value["scope"] == "OFFLINE_RESEARCH_ONLY"
    assert value["production_eligible"] is False
    assert PortableRetrievalRanker.from_dict(value) == model
    assert model.score_features([[1.0] * len(FEATURE_NAMES)]) == (7.5,)
    with pytest.raises(ValueError):
        PortableTextRanker.from_dict(value)
    for require_eligible in (True, False):
        with pytest.raises(ValueError):
            validate_artifact(value, require_eligible=require_eligible)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("target", "OBSERVED_MUTUAL_INTEREST"),
        ("scope", "PRODUCTION"),
        ("production_eligible", True),
        ("feature_names", []),
        ("schema", "other"),
    ],
)
def test_target_scope_and_feature_mutations_rejected_even_with_new_digest(field, replacement):
    value = fixture().to_dict()
    value[field] = replacement
    value["model_sha256"] = artifact_digest(value)
    with pytest.raises(ValueError):
        PortableRetrievalRanker.from_dict(value)


def test_model_integrity_and_feature_numeric_contract():
    value = fixture().to_dict()
    changed = copy.deepcopy(value)
    changed["coefficients"][0] = 5.0
    with pytest.raises(ValueError):
        PortableRetrievalRanker.from_dict(changed)
    for invalid in (True, float("nan"), float("inf"), -0.1, 1.1, "1"):
        row = [0.5] * len(FEATURE_NAMES)
        row[0] = invalid
        with pytest.raises(ValueError):
            fixture().score_features([row])
    value["person_identifier"] = "fictional"
    with pytest.raises(ValueError):
        PortableRetrievalRanker.from_dict(value)


def test_inference_imports_no_numpy_or_research_training_runtime():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import sys; from app.matching.retrieval_relevance import PortableRetrievalRanker; "
            "model=PortableRetrievalRanker((0.0,)*15,(1.0,)*15,(0.0,)*15,1.0,'a'*64,5,5,4); "
            "assert model.score('python data',['python analysis','industrial welding']) == (0.0,0.0); "
            "assert 'numpy' not in sys.modules; assert 'scripts.train_retrieval_relevance' not in sys.modules",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
