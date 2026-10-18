"""Independent synthetic utility checks; no employment-outcome labels exist here."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmark_live_matching import (
    AttentionCapacity,
    LiveProposal,
    Side,
    check_report,
    complete_greedy,
    evaluate,
    exhaustive_oracle,
    feasible,
    known_greedy_trap,
    run_benchmark,
)


class BenchmarkLiveMatchingTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / ".local"
        root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_known_greedy_trap_reaches_independent_subset_optimum(self):
        proposals, candidates, vacancies = known_greedy_trap()
        result = evaluate("fictional-known-trap", (proposals, candidates, vacancies), oracle=True)
        assert result["greedy_objective"] == 1
        assert result["live_objective"] == 1.8
        assert result["oracle_objective"] == 1.8
        assert result["live_oracle_optimum"] is True
        assert result["greedy_oracle_optimum"] is False
        assert result["live_feasible"] is True

    def test_seeded_inputs_objectives_and_feasibility_are_reproducible(self):
        first = run_benchmark(self.directory / "first", seed=204, small_cases=30, include_scale=False)
        second = run_benchmark(self.directory / "second", seed=204, small_cases=30, include_scale=False)
        assert first["input_sha256"] == second["input_sha256"]
        assert first["summary"] == second["summary"]
        assert first["source_sha256"] == second["source_sha256"]
        assert first["summary"]["oracle_checked"] == 30
        assert first["summary"]["live_oracle_optima"] == 30
        assert first["summary"]["regressions"] == 0
        assert first["summary"]["live_feasible_plans"] == 30
        assert check_report(first) == []
        assert first["hiring_accuracy"] is None
        assert (
            json.loads((self.directory / "first" / "report.json").read_text())["summary"] == first["summary"]
        )
        with self.assertRaises(FileExistsError):
            run_benchmark(self.directory / "first", small_cases=1)

    def test_greedy_does_not_stop_after_a_saturated_candidate(self):
        proposals = tuple(
            LiveProposal("c", f"v{index}", Side.CANDIDATE, 1 - index / 100) for index in range(3)
        ) + (LiveProposal("other", "v2", Side.CANDIDATE, 0.1),)
        candidates = {"c": AttentionCapacity(1, 10), "other": AttentionCapacity(1, 10)}
        vacancies = {f"v{index}": AttentionCapacity(10, 1) for index in range(3)}
        result = complete_greedy(proposals, candidates, vacancies)
        assert len(result) == 2
        assert result[-1].candidate_id == "other"
        assert feasible(result, proposals, candidates, vacancies)

    def test_attention_oracle_keeps_directions_separate_and_rejects_missing_capacity(self):
        proposals = (LiveProposal("c", "x", Side.CANDIDATE, 1), LiveProposal("c", "y", Side.EMPLOYER, 0.8))
        candidates = {"c": AttentionCapacity(1, 1)}
        vacancies = {"x": AttentionCapacity(0, 1), "y": AttentionCapacity(1, 0)}
        assert feasible(proposals, proposals, candidates, vacancies)
        assert exhaustive_oracle(proposals, candidates, vacancies)[0] == 1.8
        assert not feasible(proposals, proposals, {}, vacancies)
        assert not feasible((proposals[0], proposals[0]), proposals, candidates, vacancies)
