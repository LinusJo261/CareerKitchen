"""Fictional fixtures for frozen embedding mechanics; no pretrained model needed."""

import hashlib
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

import numpy as np

from scripts import matching_semantic_benchmark as semantic
from scripts import matching_text_benchmark as lexical
from tests.research.test_matching_text_benchmark import annotations, source_fixture


def model_fixture(directory):
    directory.mkdir()
    for name in semantic.MODEL_FILES:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}" if name.endswith(".json") else b"fictional model fixture")
    (directory / "README.md").write_text("---\nlicense: apache-2.0\n---\nFictional fixture only.\n")
    (directory / "config.json").write_text(json.dumps({"model_type": "bert", "hidden_size": 384}))
    (directory / "modules.json").write_text(
        json.dumps(
            [
                {"idx": 0, "name": "0", "path": "", "type": "sentence_transformers.models.Transformer"},
                {"idx": 1, "name": "1", "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"},
                {
                    "idx": 2,
                    "name": "2",
                    "path": "2_Normalize",
                    "type": "sentence_transformers.models.Normalize",
                },
            ]
        )
    )
    return hashlib.sha256((directory / "model.safetensors").read_bytes()).hexdigest()


class MockEncoder:
    def token_ids(self, text):
        return [ord(character) for character in text]

    def encode_chunks(self, chunks):
        values = np.zeros((len(chunks), semantic.DIMENSIONS))
        for index, chunk in enumerate(chunks):
            values[index, 0] = sum(chunk)
            values[index, 1] = len(chunk)
        return values


class ChunkingTests(unittest.TestCase):
    def test_long_input_preserves_all_token_ids_and_tail_without_decoding(self):
        tokens = list(range(561))
        chunks = semantic.token_chunks(tokens)
        self.assertEqual([len(chunk) for chunk in chunks], [200, 200, 200, 81])
        self.assertEqual(chunks[0], tokens[:200])
        self.assertEqual(chunks[1], tokens[160:360])
        self.assertEqual(chunks[-1], tokens[480:])
        covered = chunks[0] + [token for chunk in chunks[1:] for token in chunk[40:]]
        self.assertEqual(covered, tokens)

    def test_exact_chunk_boundary_does_not_emit_redundant_overlap_only_chunk(self):
        self.assertEqual([len(chunk) for chunk in semantic.token_chunks(list(range(200)))], [200])
        self.assertEqual([len(chunk) for chunk in semantic.token_chunks(list(range(360)))], [200, 200])
        self.assertEqual([len(chunk) for chunk in semantic.token_chunks(list(range(201)))], [200, 41])

    def test_invalid_token_sequences_rejected(self):
        for tokens in ([], [1, -1], [True], [0.1], ["1"]):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                semantic.token_chunks(tokens)

    def test_chunks_normalized_before_equal_mean_then_document_normalized(self):
        class UnequalEncoder(MockEncoder):
            def token_ids(self, text):
                return list(range(201))

            def encode_chunks(self, chunks):
                values = np.zeros((2, semantic.DIMENSIONS))
                values[0, 0], values[1, 1] = 2, 7
                return values

        vectors, stats = semantic.embed_documents(["Fictional long document"], UnequalEncoder())
        self.assertAlmostEqual(vectors[0, 0], 2**-0.5)
        self.assertAlmostEqual(vectors[0, 1], 2**-0.5)
        self.assertEqual(stats["documents_with_multiple_chunks"], 1)
        self.assertEqual(stats["truncated_documents"], 0)
        self.assertEqual(stats["max_tokens_per_document"], 201)

    def test_missing_empty_nonfinite_wrong_dimension_and_zero_embeddings_rejected(self):
        with self.assertRaises(ValueError):
            semantic.embed_documents(["   "], MockEncoder())
        for invalid in (
            np.ones((1, 2)),
            np.zeros((1, 384)),
            np.full((1, 384), np.nan),
        ):
            encoder = MockEncoder()
            encoder.encode_chunks = mock.Mock(return_value=invalid)
            with self.subTest(shape=invalid.shape), self.assertRaises(ValueError):
                semantic.embed_documents(["fixture"], encoder)


class BertBatchTests(unittest.TestCase):
    def test_exact_special_tokens_right_padding_and_attention_masks(self):
        long = list(range(1000, 1200))
        short = [700]
        original = [long.copy(), short.copy()]
        batch = semantic.bert_batch_inputs([long, short])
        self.assertEqual([long, short], original)
        self.assertEqual(batch["input_ids"][0], [101, *long, 102])
        self.assertEqual(batch["input_ids"][1], [101, 700, 102] + [0] * 199)
        self.assertEqual(batch["attention_mask"][0], [1] * 202)
        self.assertEqual(batch["attention_mask"][1], [1] * 3 + [0] * 199)
        self.assertEqual(batch["token_type_ids"], [[0] * 202, [0] * 202])

    def test_invalid_or_oversized_batches_rejected_without_truncation(self):
        for chunks in ([], [[]], [[1]] * 33, [list(range(201))], [[-1]], [[True]]):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                semantic.bert_batch_inputs(chunks)

    def test_actual_adapter_builds_int64_cpu_batches_without_tokenizer_prepare_api(self):
        adapter = semantic.FrozenMiniLM.__new__(semantic.FrozenMiniLM)
        adapter.torch = mock.Mock()
        adapter.torch.inference_mode.side_effect = nullcontext
        adapter.torch.long = np.int64
        adapter.torch.tensor.side_effect = lambda values, dtype, device: np.asarray(values, dtype=dtype)
        calls = []

        def forward(features):
            calls.append(features)
            embedding = mock.Mock()
            embedding.detach.return_value = embedding
            embedding.cpu.return_value = embedding
            embedding.float.return_value = embedding
            embedding.numpy.return_value = np.ones((len(features["input_ids"]), 384))
            return {"sentence_embedding": embedding}

        adapter.model = mock.Mock(side_effect=forward)
        # No tokenizer is installed on this object: direct IDs must suffice.
        result = adapter.encode_chunks([[1000, 1001]] * 32 + [[2000]])
        self.assertEqual(result.shape, (33, 384))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["input_ids"].shape, (32, 4))
        np.testing.assert_array_equal(calls[1]["input_ids"], [[101, 2000, 102]])
        for features in calls:
            for values in features.values():
                self.assertEqual(values.dtype, np.int64)
        for call in adapter.torch.tensor.call_args_list:
            self.assertEqual(call.kwargs["device"], "cpu")


class SnapshotTests(unittest.TestCase):
    def test_exact_local_snapshot_hashes_card_license_and_no_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "model"
            checksum = model_fixture(directory)
            with mock.patch.object(semantic, "MODEL_WEIGHTS_SHA256", checksum):
                provenance = semantic.verify_model_snapshot(directory)
            self.assertEqual(provenance["revision"], semantic.MODEL_REVISION)
            self.assertEqual(len(provenance["all_file_sha256"]), len(semantic.MODEL_FILES))
            self.assertTrue(provenance["local_files_only"])
            self.assertFalse(provenance["remote_code"])

    def test_changed_weights_and_unexpected_executable_or_pickle_files_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "model"
            checksum = model_fixture(directory)
            with self.assertRaisesRegex(ValueError, "SHA256"):
                semantic.verify_model_snapshot(directory)
            with mock.patch.object(semantic, "MODEL_WEIGHTS_SHA256", checksum):
                for name in ("pytorch_model.bin", "custom.py", "embedding.pkl"):
                    extra = directory / name
                    extra.write_bytes(b"fictional unsafe format")
                    with self.subTest(name=name), self.assertRaisesRegex(ValueError, "inventory"):
                        semantic.verify_model_snapshot(directory)
                    extra.unlink()

    def test_unknown_modules_dynamic_code_missing_license_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "model"
            checksum = model_fixture(directory)
            with mock.patch.object(semantic, "MODEL_WEIGHTS_SHA256", checksum):
                modules = directory / "modules.json"
                original = modules.read_text()
                modules.write_text(original.replace("sentence_transformers.models.Transformer", "evil.Model"))
                with self.assertRaisesRegex(ValueError, "built-in"):
                    semantic.verify_model_snapshot(directory)
                modules.write_text(original)
                config = directory / "tokenizer_config.json"
                config.write_text('{"auto_map": {"AutoTokenizer": "evil.Tokenizer"}}')
                with self.assertRaisesRegex(ValueError, "auto_map"):
                    semantic.verify_model_snapshot(directory)
                config.write_text("{}")
                card = directory / "README.md"
                original_card = card.read_text()
                card.write_text("Missing declared license")
                with self.assertRaisesRegex(ValueError, "license"):
                    semantic.verify_model_snapshot(directory)
                card.write_text(original_card)
                (directory / "unexpected-link").symlink_to(card)
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    semantic.verify_model_snapshot(directory)


class MetricsAndRunTests(unittest.TestCase):
    def test_same_rater_rows_and_lexical_baselines_preserved_without_consensus(self):
        jobs = ["python", "java", "sql", "c++", "baking"]
        resumes = ["java"] * 30
        rows = annotations()
        rows["ANNOTATOR_1_RANKINGS"] = [[2, 1, 3, 4, 5] for _ in range(30)]
        rows["ANNOTATOR_1_RANKINGS"][0] = None
        vectors = np.zeros((35, 384))
        for index in range(5):
            vectors[index, index] = 1
        vectors[5:, 1] = 1
        result = semantic.evaluate(jobs, resumes, rows, vectors)
        old = lexical.evaluate(jobs, resumes, rows)
        for name in lexical.METHODS:
            self.assertEqual(result["methods"][name], old["methods"][name])
        fitted = result["methods"][semantic.SEMANTIC_METHOD]
        self.assertEqual(fitted["pooled_query_rater_count"], 59)
        self.assertEqual(fitted["per_rater"]["ANNOTATOR_1_RANKINGS"]["queries"], 29)
        self.assertEqual(fitted["per_rater"]["ANNOTATOR_1_RANKINGS"]["top1_agreement"], 1)
        self.assertEqual(fitted["per_rater"]["ANNOTATOR_2_RANKINGS"]["top1_agreement"], 0)
        self.assertEqual(result["human_inter_rater_agreement"], old["human_inter_rater_agreement"])

    def test_exact_semantic_ties_use_existing_uniform_tie_policy(self):
        vectors = np.zeros((35, 384))
        vectors[:, 0] = 1
        result = semantic.evaluate(["fixture"] * 5, ["fixture"] * 30, annotations(), vectors)
        observed = result["methods"][semantic.SEMANTIC_METHOD]["pooled_query_rater"]
        self.assertAlmostEqual(observed["pairwise_agreement"], 0.5)
        self.assertAlmostEqual(observed["top1_agreement"], 0.2)
        self.assertAlmostEqual(observed["mrr_human_first_choice"], sum(1 / rank for rank in range(1, 6)) / 5)

    def test_atomic_report_json_cache_replay_and_no_raw_text_or_rankings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, model, output = root / "source.zip", root / "model", root / "result"
            source_checksum = source_fixture(source)
            weights_checksum = model_fixture(model)
            with (
                mock.patch.object(lexical, "ARCHIVE_SHA256", source_checksum),
                mock.patch.object(semantic, "MODEL_WEIGHTS_SHA256", weights_checksum),
                mock.patch.object(
                    semantic, "FrozenMiniLM", side_effect=AssertionError("No real model in tests")
                ),
            ):
                report = semantic.run_benchmark(source, model, output, encoder=MockEncoder())
                self.assertEqual(json.loads((output / "report.json").read_text()), report)
                self.assertTrue(report["deterministic_cache_replay_verified"])
                self.assertFalse(report["label_training_or_tuning"])
                protocol = json.loads((output / "protocol.json").read_text())
                self.assertTrue(protocol["parameters_predeclared_before_scoring"])
                cache = json.loads((output / "embeddings.json").read_text())
                self.assertEqual(len(cache["vectors"]), 35)
                self.assertEqual(np.asarray(cache["vectors"]).shape, (35, 384))
                for path in output.iterdir():
                    self.assertNotIn("PRIVATE_FIXTURE_TEXT", path.read_text())
                    self.assertNotIn("fixture description", path.read_text())
                    self.assertNotIn("[1, 2, 3, 4, 5]", path.read_text())
                with self.assertRaises(FileExistsError):
                    semantic.run_benchmark(source, model, output, encoder=MockEncoder())

    def test_inference_failure_does_not_publish_partial_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, model, output = root / "source.zip", root / "model", root / "result"
            source_checksum = source_fixture(source)
            weights_checksum = model_fixture(model)
            encoder = MockEncoder()
            encoder.encode_chunks = mock.Mock(side_effect=RuntimeError("Fictional inference failure"))
            with (
                mock.patch.object(lexical, "ARCHIVE_SHA256", source_checksum),
                mock.patch.object(semantic, "MODEL_WEIGHTS_SHA256", weights_checksum),
                self.assertRaisesRegex(RuntimeError, "Fictional"),
            ):
                semantic.run_benchmark(source, model, output, encoder=encoder)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
