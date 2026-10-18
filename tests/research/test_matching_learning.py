"""Fictional fixtures verify learning software, never real matching accuracy."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts.matching_learning import (
    FEATURE_NAMES,
    INPUT_FEATURE_NAMES,
    SPLIT_POLICY_VERSION,
    canonical_hash,
    choose_threshold,
    compatibility_baseline,
    feature_diagnostics,
    fit_challenger,
    fit_compatibility_probability_baseline,
    fit_logistic,
    fit_transforms,
    incumbent_scores,
    load_incumbent,
    metrics,
    paired_confidence,
    probabilities,
    sigmoid,
    split_learning_records,
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
)
from scripts.mutual_matching_research import (
    split_records as legacy_split_records,
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
            features.update(dict(zip(INPUT_FEATURE_NAMES[:4], [(index % 10) / 9, 1, 1, 1], strict=True)))
            rows.append(
                {
                    "cycle_id": f"fictional-{group}-{index}",
                    "candidate_id": fixture_identity("candidate", group, index),
                    "vacancy_id": fixture_identity("vacancy", group, index),
                    "organization_id": fixture_identity("organization", group, index),
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
    groups, _ = split_learning_records(rows, 42, "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
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
        assert artifact["provenance"]["split"]["policy_version"] == SPLIT_POLICY_VERSION
        assert artifact["provenance"]["split"]["grouping_entities"] == ["candidate_id", "organization_id"]
        assert artifact["schema_version"] == 3
        assert len(artifact["coefficients"]) == 14
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

    def test_recurring_employers_with_multiple_vacancies_get_disjoint_cohorts_upfront(self):
        base = fixture_groups(self.tmp_path)
        records = []
        for calendar_group, source_rows in base.items():
            for employer_index, employer_group in enumerate(base):
                for vacancy_index in range(3):
                    index = employer_index * 3 + vacancy_index
                    row = deepcopy(source_rows[index])
                    row["cycle_id"] = f"fictional-recurring-{calendar_group}-{index}"
                    row["candidate_id"] = fixture_identity("candidate", calendar_group, index)
                    row["vacancy_id"] = fixture_identity("vacancy", calendar_group, index)
                    row["organization_id"] = fixture_identity("organization", employer_group, 0)
                    records.append(row)
        old, _ = legacy_split_records(records, 42, "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
        old_orgs = {group: {row["organization_id"] for row in rows} for group, rows in old.items()}
        assert old_orgs["train"] & old_orgs["validation"] & old_orgs["test"]
        groups, policy = split_learning_records(records, 42, "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
        assert policy["policy_version"] == SPLIT_POLICY_VERSION
        assert policy["counts"] == {"train": 3, "validation": 3, "test": 3}
        for identity in ("candidate_id", "organization_id", "vacancy_id"):
            identities = {name: {row[identity] for row in rows} for name, rows in groups.items()}
            assert not (identities["train"] & identities["validation"])
            assert not (identities["train"] & identities["test"])
            assert not (identities["validation"] & identities["test"])
        assert all(len({row["vacancy_id"] for row in rows}) == 3 for rows in groups.values())

    def test_split_membership_is_independent_of_labels_and_separate_vacancy_hashes(self):
        records = [row for rows in fixture_groups(self.tmp_path).values() for row in rows]
        groups, policy = split_learning_records(records, 42, "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
        altered = deepcopy(records)
        for index, row in enumerate(altered):
            row["label"] = 1 - row["label"]
            row["vacancy_id"] = f"fictional-independent-vacancy-{index}"
        changed, changed_policy = split_learning_records(
            altered, 42, "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z"
        )
        assert {name: [row["cycle_id"] for row in rows] for name, rows in groups.items()} == {
            name: [row["cycle_id"] for row in rows] for name, rows in changed.items()
        }
        assert policy == changed_policy

    def test_vacancy_ownership_must_be_consistent_even_in_an_excluded_censored_row(self):
        inputs, manifest = fixture_inputs(self.tmp_path)
        records = [json.loads(line) for line in inputs.read_text().splitlines()]
        censored = deepcopy(records[0])
        censored["cycle_id"] = "fictional-censored-inconsistent-ownership"
        censored["organization_id"] = records[-1]["organization_id"]
        censored["decisions"]["candidate"]["status"] = "INTERESTED"
        inputs.write_text("".join(json.dumps(row) + "\n" for row in [*records, censored]))
        # The ordinary label loader excludes the unresolved row. Training still
        # validates its immutable vacancy ownership before splitting labeled rows.
        labeled, diagnostics = load_records(inputs, json.loads(manifest.read_text()))
        assert len(labeled) == 180
        assert diagnostics["excluded"]["unresolved"] == 1
        with self.assertRaisesRegex(ValueError, "exactly one organization"):
            train(
                inputs,
                manifest,
                self.tmp_path / "invalid-ownership",
                "2005-01-01T00:00:00Z",
                "2015-01-01T00:00:00Z",
                bootstrap_replicates=50,
                allow_fictional=True,
            )
        assert not (self.tmp_path / "invalid-ownership").exists()

    def test_new_split_preserves_existing_observed_and_exposure_cutoff_boundaries(self):
        original = fixture_groups(self.tmp_path)
        original["train"][0]["observed_at"] = datetime(2005, 1, 1, tzinfo=UTC)
        original["validation"][0]["first_exposed_at"] = datetime(2005, 1, 1, tzinfo=UTC)
        original["validation"][1]["observed_at"] = datetime(2015, 1, 1, tzinfo=UTC)
        original["test"][0]["first_exposed_at"] = datetime(2015, 1, 1, tzinfo=UTC)
        records = [row for rows in original.values() for row in rows]
        groups, _ = split_learning_records(records, 42, "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
        assert len(groups["train"]) == 59
        assert len(groups["validation"]) == 59
        assert original["validation"][0] in groups["validation"]
        assert original["test"][0] in groups["test"]

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
                name: row["features"].get(source)
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
            row["features"].update(dict.fromkeys(INPUT_FEATURE_NAMES[:4], 0.5))
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
            value = row["features"].get(key)
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

    def test_expanded_contract_learns_a_new_signal_when_old_inputs_are_constant(self):
        """Fabricated feature/outcome relation verifies fitting, never real accuracy."""
        inputs, manifest_path = fixture_inputs(self.tmp_path)
        manifest = json.loads(manifest_path.read_text())
        manifest.update(schema_version=2, feature_version="mutual-pair-features-v2")
        manifest_path.write_text(json.dumps(manifest))
        rows = [json.loads(line) for line in inputs.read_text().splitlines()]
        for row in rows:
            row["feature_provenance"] = {"text_relevance_model_id": "a" * 64}
            row["features"].update(
                preferred_skill_coverage=0.5,
                skill_precision=None,
                skill_jaccard=None,
                text_relevance=0.9 if row["decisions"]["candidate"]["status"] == "INTERESTED" else 0.1,
            )
        inputs.write_text("".join(json.dumps(row) + "\n" for row in rows))
        report = train(
            inputs,
            manifest_path,
            self.tmp_path / "expanded",
            "2005-01-01T00:00:00Z",
            "2015-01-01T00:00:00Z",
            bootstrap_replicates=50,
            allow_fictional=True,
        )
        artifact = json.loads((self.tmp_path / "expanded" / "fictional_model.json").read_text())
        runtime = validate_artifact(artifact, require_eligible=False)
        base = dict(zip(FEATURE_NAMES, [0.5, 1, 1, 1, None, None, 0.1], strict=True))
        assert runtime.predict_values({**base, "text_relevance": 0.9}) > runtime.predict_values(base)
        assert report["feature_readiness"]["training_has_feature_variation"] is True
        assert report["feature_diagnostics"]["train"]["candidate_role"]["known_values_constant"] is True
        assert report["feature_diagnostics"]["train"]["text_relevance"]["distinct_known_values"] == 2
        assert report["fictional_data"] is True
        assert report["evidence"]["eligible_for_review"] is False

    def test_legacy_missing_expanded_inputs_stay_unknown_in_diagnostics_and_inference(self):
        groups = fixture_groups(self.tmp_path)
        diagnostics = feature_diagnostics(groups["train"])
        for name in ("skill_precision", "skill_jaccard", "text_relevance"):
            assert diagnostics[name] == {
                "known_count": 0,
                "missing_count": 60,
                "distinct_known_values": 0,
                "known_values_constant": False,
                "input_varies": False,
                "known_mean": None,
                "known_min": None,
                "known_max": None,
            }
        fitted, _ = fit_challenger(groups)
        encoded = transform(groups["test"], fitted["transforms"])
        assert encoded.shape == (60, 14)
        assert np.all(encoded[:, 8::2] == 0)
        assert np.all(encoded[:, 9::2] == 1)

    def test_runtime_and_offline_transforms_keep_v2_incumbent_predictions_identical(self):
        groups = fixture_groups(self.tmp_path)
        fitted, _ = fit_challenger(groups)
        legacy_transforms = fitted["transforms"][:4]
        legacy_matrix = transform(groups["test"], legacy_transforms)
        assert legacy_matrix.shape == (60, 8)
        assert np.array_equal(legacy_matrix, transform(groups["test"], fitted["transforms"])[:, :8])

    def test_expanded_manifest_refuses_missing_extra_inputs_and_legacy_version_mixing(self):
        inputs, manifest_path = fixture_inputs(self.tmp_path)
        manifest = json.loads(manifest_path.read_text())
        manifest.update(schema_version=2, feature_version="mutual-pair-features-v2")
        with self.assertRaisesRegex(ValueError, "documented snapshot/outcome"):
            load_records(inputs, manifest)
        manifest["schema_version"] = 1
        with self.assertRaisesRegex(ValueError, "Unsupported feature version"):
            load_records(inputs, manifest)

    def test_mixed_text_extractors_are_rejected_before_any_training_or_publication(self):
        inputs, manifest_path = fixture_inputs(self.tmp_path)
        manifest = json.loads(manifest_path.read_text())
        manifest.update(schema_version=2, feature_version="mutual-pair-features-v2")
        manifest_path.write_text(json.dumps(manifest))
        rows = [json.loads(line) for line in inputs.read_text().splitlines()]
        for index, row in enumerate(rows):
            row["features"].update(skill_precision=None, skill_jaccard=None, text_relevance=0.5)
            row["feature_provenance"] = {"text_relevance_model_id": ("a" if index % 2 else "b") * 64}
        inputs.write_text("".join(json.dumps(row) + "\n" for row in rows))
        output = self.tmp_path / "mixed"
        with patch("scripts.matching_learning.fit_challenger") as fit:
            with self.assertRaisesRegex(ValueError, "Mixed text relevance extractors"):
                train(
                    inputs,
                    manifest_path,
                    output,
                    "2005-01-01T00:00:00Z",
                    "2015-01-01T00:00:00Z",
                    allow_fictional=True,
                )
            fit.assert_not_called()
        assert not output.exists()

    def test_incumbent_comparison_replays_runtime_extractor_mismatch_fallback(self):
        groups = fixture_groups(self.tmp_path)
        fitted, _ = fit_challenger(groups)
        rows = deepcopy(groups["test"][:3])
        artifact = {
            "schema_version": 3,
            **fitted,
            "provenance": {"feature_extractors": {"text_relevance_model_id": "a" * 64}},
        }
        for index, row in enumerate(rows):
            row["features"]["text_relevance"] = 0.5 if index < 2 else None
            row["feature_provenance"] = {
                "text_relevance_model_id": "a" * 64 if index == 0 else "b" * 64 if index == 1 else None
            }
        expected = probabilities(fitted, transform(rows, fitted["transforms"]), fitted["calibration"])
        scores, fallbacks = incumbent_scores(artifact, rows)
        assert fallbacks == 1
        assert scores[0] == expected[0]
        assert scores[1] == compatibility_baseline(rows)[1]
        assert scores[2] == expected[2]
