"""Fictional fixtures verify learning software, never real matching accuracy."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts.matching_learning import (
    FEATURE_NAMES,
    INPUT_FEATURE_NAMES,
    canonical_hash,
    choose_threshold,
    compatibility_baseline,
    fit_challenger,
    fit_compatibility_probability_baseline,
    fit_logistic,
    fit_transforms,
    load_incumbent,
    metrics,
    paired_confidence,
    probabilities,
    sigmoid,
    train,
    transform,
    validate_artifact,
)
from scripts.mutual_matching_features import FEATURE_NAMES as RESEARCH_FEATURE_NAMES
from scripts.mutual_matching_research import (
    FEATURE_VERSION,
    TARGET,
    identity_group,
    load_records,
    split_records,
)


def fixture_identity(kind: str, group: str, index: int) -> str:
    attempt = 0
    while True:
        identity = f"fictional-{kind}-{group}-{index}-{attempt}"
        if identity_group(kind, identity, 42) == group:
            return identity
        attempt += 1


def fixture_inputs(directory: Path, count: int = 60) -> tuple[Path, Path]:
    manifest = {
        "schema_version": 1,
        "target": TARGET,
        "feature_version": FEATURE_VERSION,
        "horizon_days": 14,
        "source": {
            "kind": "fictional_fixture",
            "dataset": "fictional_software_test",
            "source_version": "fixture-v2",
            "exported_at": "2025-01-01T00:00:00Z",
        },
    }
    input_path, manifest_path = directory / "fictional.jsonl", directory / "manifest.json"
    rows = []
    for group, year in (("train", 2000), ("validation", 2010), ("test", 2020)):
        for index in range(count):
            positive = index % 10 >= 5
            exposed = f"{year}-01-01T00:00:00Z"
            features = dict.fromkeys(RESEARCH_FEATURE_NAMES)
            features.update(dict(zip(INPUT_FEATURE_NAMES, [(index % 10) / 9, 1, 1, 1], strict=True)))
            rows.append(
                {
                    "cycle_id": f"fictional-{group}-{index}",
                    "candidate_id": fixture_identity("candidate", group, index),
                    "vacancy_id": fixture_identity("vacancy", group, index),
                    "organization_id": f"fictional-organization-{group}-{index}",
                    "candidate_version": 1,
                    "vacancy_version": 1,
                    "policy_version": "fictional-policy",
                    "feature_as_of": exposed,
                    "first_exposed_at": exposed,
                    "first_mover": "candidate",
                    "eligibility": "ELIGIBLE",
                    "observation_status": "OBSERVABLE",
                    "observed_at": f"{year}-01-10T00:00:00Z",
                    "features": features,
                    "decisions": {
                        "candidate": {
                            "status": "INTERESTED" if positive else "PASSED",
                            "issued_at": exposed,
                            "answered_at": f"{year}-01-02T00:00:00Z",
                        },
                        "employer": {
                            "status": "INTERESTED" if positive else "NOT_ISSUED",
                            "issued_at": f"{year}-01-03T00:00:00Z" if positive else None,
                            "answered_at": f"{year}-01-04T00:00:00Z" if positive else None,
                        },
                    },
                }
            )
    input_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return input_path, manifest_path


def fixture_groups(tmp_path: Path) -> dict:
    inputs, manifest = fixture_inputs(tmp_path)
    rows, _ = load_records(inputs, json.loads(manifest.read_text()))
    groups, _ = split_records(rows, 42, "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
    return groups


class MatchingLearningTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[2] / ".local"
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.tmp_path = Path(self.temporary.name)

    def test_training_refuses_fictional_sources_unless_explicitly_requested(self):
        tmp_path = self.tmp_path
        inputs, manifest = fixture_inputs(tmp_path)
        with self.assertRaisesRegex(ValueError, "Fictional fixtures"):
            train(inputs, manifest, tmp_path / "forbidden", "2005-01-01Z", "2015-01-01Z")
        assert not (tmp_path / "forbidden").exists()

    def test_immutable_fixture_artifact_is_portable_and_never_review_eligible(self):
        tmp_path = self.tmp_path
        inputs, manifest = fixture_inputs(tmp_path)
        output = tmp_path / "output"
        report = train(
            inputs,
            manifest,
            output,
            "2005-01-01T00:00:00Z",
            "2015-01-01T00:00:00Z",
            bootstrap_replicates=50,
            allow_fictional=True,
        )
        artifact = json.loads((output / "fictional_model.json").read_text())
        model_id = artifact.pop("model_id")
        assert model_id == canonical_hash(artifact) == report["model_id"]
        assert artifact["feature_names"] == list(FEATURE_NAMES)
        assert len(artifact["coefficients"]) == 8
        assert artifact["fictional_data"] is True
        assert artifact["evidence"]["eligible_for_review"] is False
        assert "FICTIONAL_FIXTURE" in artifact["evidence"]["reasons"]
        assert report["evaluation"]["test"]["challenger"]["roc_auc"] == 1
        with self.assertRaises(FileExistsError):
            train(
                inputs,
                manifest,
                output,
                "2005-01-01T00:00:00Z",
                "2015-01-01T00:00:00Z",
                bootstrap_replicates=50,
                allow_fictional=True,
            )
        assert not (output / "observed_model.json").exists()

    def test_no_test_labels_features_or_identities_influence_model_selection(self):
        tmp_path = self.tmp_path
        groups = fixture_groups(tmp_path)
        fitted, selection = fit_challenger(groups)
        baseline = fit_compatibility_probability_baseline(groups)
        changed = deepcopy(groups)
        for row in changed["test"]:
            row["label"] = 1 - row["label"]
            row["features"] = dict.fromkeys(RESEARCH_FEATURE_NAMES, None)
            row["candidate_id"] = "fictional-held-out-changed"
        assert fit_challenger(changed) == (fitted, selection)
        assert fit_compatibility_probability_baseline(changed) == baseline
        del changed["test"]
        assert fit_challenger(changed) == (fitted, selection)
        assert fit_compatibility_probability_baseline(changed) == baseline

    def test_runtime_model_prediction_matches_offline_numpy_prediction(self):
        inputs, manifest = fixture_inputs(self.tmp_path)
        output = self.tmp_path / "parity"
        train(
            inputs,
            manifest,
            output,
            "2005-01-01T00:00:00Z",
            "2015-01-01T00:00:00Z",
            bootstrap_replicates=50,
            allow_fictional=True,
        )
        artifact = json.loads((output / "fictional_model.json").read_text())
        runtime = validate_artifact(artifact, require_eligible=False)
        with self.assertRaisesRegex(ValueError, "observed-outcome"):
            validate_artifact(artifact)
        groups = fixture_groups(self.tmp_path)
        for row in groups["test"]:
            values = {
                name: row["features"][source]
                for name, source in zip(FEATURE_NAMES, INPUT_FEATURE_NAMES, strict=True)
            }
            expected = probabilities(
                artifact, transform([row], artifact["transforms"]), artifact["calibration"]
            )[0]
            assert abs(runtime.predict_values(values) - expected) < 1e-12

    def test_incumbent_must_have_genuine_provenance_and_valid_hash(self):
        inputs, manifest = fixture_inputs(self.tmp_path)
        output = self.tmp_path / "incumbent"
        train(
            inputs,
            manifest,
            output,
            "2005-01-01T00:00:00Z",
            "2015-01-01T00:00:00Z",
            bootstrap_replicates=50,
            allow_fictional=True,
        )
        artifact_path = output / "fictional_model.json"
        with self.assertRaisesRegex(ValueError, "observed-outcome"):
            load_incumbent(artifact_path, json.loads(manifest.read_text()))
        artifact = json.loads(artifact_path.read_text())
        artifact["coefficients"][0] += 1
        artifact_path.write_text(json.dumps(artifact))
        with self.assertRaisesRegex(ValueError, "integrity"):
            load_incumbent(artifact_path, json.loads(manifest.read_text()))

    def test_calibration_does_not_split_tied_exposures_or_reuse_later_identities(self):
        groups = fixture_groups(self.tmp_path)
        _, selection = fit_challenger(groups)
        assert selection["calibration_fit_count"] == 0
        assert selection["calibration_selection_count"] == 60
        for index, row in enumerate(groups["validation"]):
            row["first_exposed_at"] = row["first_exposed_at"].replace(day=1 if index < 30 else 2)
            row["organization_id"] = f"fictional-repeated-organization-{index % 30}"
        _, selection = fit_challenger(groups)
        assert selection["calibration_fit_count"] == 0
        assert selection["calibration_selection_count"] == 30

    def test_no_signal_outcomes_do_not_pass_improvement_screen(self):
        inputs, manifest = fixture_inputs(self.tmp_path)
        rows = [json.loads(line) for line in inputs.read_text().splitlines()]
        for row in rows:
            row["features"].update(dict.fromkeys(INPUT_FEATURE_NAMES, 0.5))
        inputs.write_text("".join(json.dumps(row) + "\n" for row in rows))
        report = train(
            inputs,
            manifest,
            self.tmp_path / "no-signal",
            "2005-01-01T00:00:00Z",
            "2015-01-01T00:00:00Z",
            bootstrap_replicates=50,
            allow_fictional=True,
        )
        assert "NO_CONFIDENT_TEST_GAIN_VS_TRAINING_PREVALENCE" in report["evidence"]["reasons"]
        assert "NO_CONFIDENT_TEST_GAIN_VS_FITTED_COMPATIBILITY" in report["evidence"]["reasons"]
        assert report["evaluation"]["test"]["challenger"]["roc_auc"] == 0.5

    def test_failed_publication_does_not_expose_partial_model_directory(self):
        inputs, manifest = fixture_inputs(self.tmp_path)
        output = self.tmp_path / "failed-publication"
        original = Path.write_text

        def fail_report(path, *args, **kwargs):
            if path.name == "fictional_report.json":
                raise OSError("fictional simulated report write failure")
            return original(path, *args, **kwargs)

        with patch.object(Path, "write_text", fail_report), self.assertRaisesRegex(OSError, "simulated"):
            train(
                inputs,
                manifest,
                output,
                "2005-01-01T00:00:00Z",
                "2015-01-01T00:00:00Z",
                bootstrap_replicates=50,
                allow_fictional=True,
            )
        assert not output.exists()
        assert not list(self.tmp_path.glob(".matching-stage-*"))

    def test_imputation_and_scaling_use_only_training_rows(self):
        tmp_path = self.tmp_path
        groups = fixture_groups(tmp_path)
        groups["train"][0]["features"][INPUT_FEATURE_NAMES[0]] = None
        fitted = fit_transforms(groups["train"])
        median = float(np.median([row["features"][INPUT_FEATURE_NAMES[0]] for row in groups["train"][1:]]))
        assert fitted[0]["imputation_median"] == median
        encoded = transform([groups["train"][0]], fitted)
        assert encoded[0, 1] == 1
        assert np.isclose(encoded[0, 0], (median - fitted[0]["center"]) / fitted[0]["scale"])
        assert all(item["scale"] >= 0.05 for item in fitted)

    def test_no_observed_feature_and_single_class_training_fail(self):
        tmp_path = self.tmp_path
        groups = fixture_groups(tmp_path)
        for row in groups["train"]:
            row["features"] = dict.fromkeys(RESEARCH_FEATURE_NAMES)
        with self.assertRaisesRegex(ValueError, "No known training features"):
            fit_transforms(groups["train"])
        with self.assertRaisesRegex(ValueError, "both explicit outcome classes"):
            fit_logistic(np.ones((10, 4)), np.zeros(10), 0.01)

    def test_prediction_matches_documented_lightweight_formula(self):
        tmp_path = self.tmp_path
        groups = fixture_groups(tmp_path)
        fitted, _ = fit_challenger(groups)
        row = groups["test"][5]
        transformed = []
        for key, stats in zip(INPUT_FEATURE_NAMES, fitted["transforms"], strict=True):
            value = row["features"][key]
            transformed.extend(
                [
                    ((stats["imputation_median"] if value is None else value) - stats["center"])
                    / stats["scale"],
                    float(value is None),
                ]
            )
        raw = fitted["intercept"] + sum(
            a * b for a, b in zip(transformed, fitted["coefficients"], strict=True)
        )
        expected = 1 / (
            1 + np.exp(-(fitted["calibration"]["slope"] * raw + fitted["calibration"]["intercept"]))
        )
        assert np.isclose(
            probabilities(fitted, transform([row], fitted["transforms"]), fitted["calibration"])[0], expected
        )

    def test_tied_score_ranking_metrics_are_order_invariant(self):
        labels = np.array([1, 0, 1, 0])
        equal = np.full(4, 0.5)
        result = metrics(labels, equal)
        assert result["roc_auc"] == 0.5
        assert result["average_precision"] == 0.5
        assert result["brier_score"] == 0.25
        assert result["roc_auc"] == metrics(labels[::-1], equal)["roc_auc"]
        assert result["accuracy_wilson_95"][0] < 0.5 < result["accuracy_wilson_95"][1]

    def test_threshold_sweep_matches_brute_force_balanced_accuracy(self):
        rng = np.random.default_rng(891)
        for _ in range(20):
            labels = np.r_[0, 1, rng.integers(2, size=98)]
            scores = np.round(rng.random(len(labels)), 1)
            expected = max(
                np.unique(np.r_[0, scores, 1]),
                key=lambda threshold: (
                    metrics(labels, scores, threshold)["balanced_accuracy"],
                    -abs(threshold - 0.5),
                ),
            )
            assert choose_threshold(labels, scores) == expected

    def test_cluster_comparison_retains_paired_candidates_and_employers(self):
        rows = [
            {
                "candidate_id": f"fictional-candidate-{index // 2}",
                "organization_id": f"fictional-org-{index % 5}",
            }
            for index in range(40)
        ]
        labels = np.array([0, 1] * 20)
        learned = np.where(labels, 0.8, 0.2)
        result = paired_confidence(rows, labels, learned, np.full(40, 0.5), 42, 50)
        assert result["cluster_count"] == 20
        assert result["by_scope"]["organization_id"]["cluster_count"] == 5
        assert result["log_loss_delta_95"][1] < 0
        assert result["brier_delta_95"][1] < 0
        assert result == paired_confidence(rows, labels, learned, np.full(40, 0.5), 42, 50)

    def test_current_compatibility_baseline_matches_shared_live_formula(self):
        tmp_path = self.tmp_path
        groups = fixture_groups(tmp_path)
        row = groups["test"][5]
        skills = row["features"]["preferred_skill_coverage"]
        assert np.isclose(compatibility_baseline([row])[0], np.sqrt((1 + skills) / 2))
        row["features"]["preferred_skill_coverage"] = None
        assert compatibility_baseline([row])[0] == 1

    def test_extreme_sigmoid_has_no_overflow(self):
        with np.errstate(over="raise"):
            assert sigmoid(np.array([-1e300, 0, 1e300])).tolist() == [0, 0.5, 1]
