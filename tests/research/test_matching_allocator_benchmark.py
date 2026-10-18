"""Independent tiny-market oracle checks; fictional inputs are never efficacy data."""

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.matching.portfolio import Commitment, MarketSnapshot, ResearchEdge, VacancyResearch, allocate_global
from app.matching.runtime import PlannerLimits, PlanningBudget

from scripts import benchmark_matching_allocator as benchmark


def generous_limits():
    return PlannerLimits(max_seconds=30, max_operations=2_000_000, max_edges=2_000)


class IndependentAllocationOracleTests(unittest.TestCase):
    def test_complementary_robust_bundle_has_known_optimum_despite_negative_singletons(self):
        snapshot = benchmark.adversarial_cases()[-1].snapshot
        self.assertAlmostEqual(benchmark.independent_objective(snapshot, {"j": set()}), 0.0)
        self.assertAlmostEqual(benchmark.independent_objective(snapshot, {"j": {"x"}}), -0.02)
        self.assertAlmostEqual(benchmark.independent_objective(snapshot, {"j": {"y"}}), -0.02)
        oracle = benchmark.exhaustive_oracle(snapshot)
        self.assertAlmostEqual(oracle.objective, 0.96)
        self.assertEqual(oracle.allocation, (("j", ("x", "y")),))
        self.assertEqual(oracle.feasible_assignments, 4)

    def test_independent_oracle_does_not_call_production_scenario_helpers(self):
        snapshot = benchmark.adversarial_cases()[-1].snapshot
        with (
            patch(
                "app.matching.scenario.robust_upper_failure",
                side_effect=AssertionError("oracle reused production risk"),
            ),
            patch(
                "app.matching.scenario.model_nonfill_risk",
                side_effect=AssertionError("oracle reused production risk"),
            ),
        ):
            self.assertAlmostEqual(benchmark.exhaustive_oracle(snapshot).objective, 0.96)

    def test_incomplete_model_population_stays_routing_only_for_every_subset(self):
        snapshot = MarketSnapshot(
            "fictional-incomplete-model",
            (VacancyResearch("j", 1, 2, (benchmark._model("stipulated-partial", {"known": 0.9}),)),),
            (ResearchEdge("known", "j", 0.1), ResearchEdge("unknown", "j", 0.2)),
        )
        self.assertAlmostEqual(benchmark.independent_objective(snapshot, {"j": {"known"}}), 0.1)
        oracle = benchmark.exhaustive_oracle(snapshot)
        self.assertAlmostEqual(oracle.objective, 0.3)
        limits = generous_limits()
        plan = allocate_global(snapshot, limits, PlanningBudget(limits, lambda: 0))
        self.assertAlmostEqual(plan.objective, oracle.objective)
        self.assertIsNone(plan.vacancies[0].model_nonfill_risk)
        self.assertIsNone(plan.expected_fills)
        self.assertTrue(all(benchmark.validate_plan(snapshot, plan, snapshot.digest).values()))

    def test_fixed_candidate_elsewhere_does_not_make_feasible_model_population_unknown(self):
        snapshot = MarketSnapshot(
            "fictional-fixed-elsewhere",
            (
                VacancyResearch(
                    "a", 1, 1, (benchmark._model("stipulated-known", {"x": 0.8}),), target_fill=1.0
                ),
                VacancyResearch("b", 1, 1),
            ),
            (ResearchEdge("x", "a", 0.1), ResearchEdge("fixed", "a", 99.0), ResearchEdge("fixed", "b", 0.4)),
            (Commitment("fixed", "b", "ACTIVE_DECISION"),),
        )
        oracle = benchmark.exhaustive_oracle(snapshot)
        self.assertAlmostEqual(oracle.objective, 1.2)
        limits = generous_limits()
        plan = allocate_global(snapshot, limits, PlanningBudget(limits, lambda: 0))
        self.assertAlmostEqual(plan.objective, oracle.objective)
        risk = plan.vacancies[0].model_nonfill_risk
        assert risk is not None
        self.assertAlmostEqual(risk, 0.2)

    def test_oracle_enforces_opt_in_eligibility_caps_costs_and_fixed_commitments(self):
        snapshot = benchmark.boundary_cases()[0].snapshot
        oracle = benchmark.exhaustive_oracle(snapshot)
        self.assertAlmostEqual(oracle.objective, 1.4)
        self.assertEqual(oracle.allocation, (("a", ("fixed",)), ("b", ("x", "y")), ("closed", ())))
        self.assertFalse(
            any(
                candidate in {"private", "ineligible", "closed-only", "costly"}
                for _, members in oracle.allocation
                for candidate in members
            )
        )

    def test_reduced_limit_preserves_existing_commitments_without_permitting_new_members(self):
        snapshot = MarketSnapshot(
            "fictional-reduced-cap",
            (VacancyResearch("j", 1, 0),),
            (ResearchEdge("fixed", "j", 0.4), ResearchEdge("new", "j", 100.0)),
            (Commitment("fixed", "j", "ACTIVE_DECISION"),),
        )
        oracle = benchmark.exhaustive_oracle(snapshot)
        self.assertEqual(oracle.allocation, (("j", ("fixed",)),))
        self.assertAlmostEqual(oracle.objective, 0.4)

    def test_oracle_refuses_large_search_instead_of_reporting_partial_optimum(self):
        with self.assertRaisesRegex(ValueError, "state bound"):
            benchmark.exhaustive_oracle(benchmark.sparse_scale_case(7).snapshot, max_states=100)
        for invalid in (0, -1, True, 1.2):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                benchmark.exhaustive_oracle(benchmark.boundary_cases()[0].snapshot, max_states=invalid)  # type: ignore[arg-type]

    def test_seeded_fixture_inventory_is_repeatable_without_external_data(self):
        first = benchmark.make_cases(17, 4, 3)
        self.assertEqual(first, benchmark.make_cases(17, 4, 3))
        self.assertNotEqual(first, benchmark.make_cases(18, 4, 3))
        for counts in ((True, 1), (-1, 1), (1, 0.5)):
            with self.assertRaises(ValueError):
                benchmark.make_cases(linear_cases=counts[0], modeled_cases=counts[1])  # type: ignore[arg-type]

    def test_optional_threshold_fixtures_preserve_default_inventory_and_cover_policy_boundaries(self):
        original = benchmark.make_cases(17, 4, 3)
        expanded = benchmark.make_cases(17, 4, 3, threshold_cases=12)
        thresholds = [case for case in expanded if case.family == "threshold_policy"]
        self.assertEqual(tuple(case for case in expanded if case.family != "threshold_policy"), original)
        self.assertEqual(expanded, benchmark.make_cases(17, 4, 3, threshold_cases=12))
        self.assertNotEqual(thresholds, list(benchmark.seeded_threshold_policy_cases(12, 18)))
        self.assertEqual(len(benchmark.make_cases(include_scale=False)), 367)
        self.assertEqual(len(thresholds), 12)
        self.assertEqual(
            {vacancy.target_fill for case in thresholds for vacancy in case.snapshot.vacancies},
            {0.0, 0.5, 0.8, 0.95, 0.999, 1.0},
        )
        for invalid in (True, -1, 0.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                benchmark.make_cases(threshold_cases=invalid)  # type: ignore[arg-type]

    def test_threshold_policy_preserves_reference_quality_and_reports_raw_oracle_limits(self):
        rows = [
            benchmark.evaluate_case(case, generous_limits())
            for case in benchmark.seeded_threshold_policy_cases(36, benchmark.DEFAULT_SEED)
        ]
        self.assertEqual(benchmark.check_report({"cases": rows}), [])
        policy_limited = [
            row["methods"]["improved_allocator"]
            for row in rows
            if row["methods"]["improved_allocator"]["oracle_gap"] > benchmark.TOLERANCE
        ]
        self.assertTrue(policy_limited)
        self.assertTrue(all(not entry["search_complete"] for entry in policy_limited))
        # target_fill=0 permits pruning every optional candidate. The raw oracle
        # still optimizes fill minus costs and therefore remains only an upper bound.
        self.assertAlmostEqual(rows[0]["methods"]["improved_allocator"]["objective"], 0.0)
        self.assertGreater(rows[0]["oracle"]["objective"], 0.0)

    def test_report_check_rejects_regression_missing_reference_and_false_optimality(self):
        row = benchmark.evaluate_case(benchmark.adversarial_cases()[-1], generous_limits())
        self.assertEqual(benchmark.check_report({"cases": [row]}), [])
        failures = []
        for mutation in (
            lambda methods: methods.pop("legacy_heuristic"),
            lambda methods: methods.pop("improved_allocator"),
            lambda methods: methods["improved_allocator"].update(completed=False),
            lambda methods: methods["improved_allocator"].update(objective=-1.0),
            lambda methods: methods["improved_allocator"].update(search_complete=True, oracle_gap=0.1),
        ):
            corrupted = json.loads(json.dumps(row))
            mutation(corrupted["methods"])
            failures.append(benchmark.check_report({"cases": [corrupted]}))
        self.assertTrue(all(failures))
        self.assertTrue(benchmark.check_report({"cases": []}))
        self.assertTrue(
            benchmark.check_report({"cases": [row], "default_shadow_trials": [{"completed": False}]})
        )

    def test_cli_check_returns_failure_for_incomplete_comparisons(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "checked"
            arguments = [
                "benchmark_matching_allocator.py",
                "--output",
                str(output),
                "--check",
                "--threshold-cases",
                "12",
                "--skip-scale",
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch.object(
                    benchmark,
                    "run_benchmark",
                    return_value={"summary": {}, "cases": [], "default_shadow_trials": []},
                ) as run,
                patch("builtins.print"),
            ):
                self.assertEqual(benchmark.main(), 1)
            self.assertEqual(run.call_args.kwargs["threshold_cases"], 12)

    def test_new_allocator_matches_independent_oracle_across_tiny_linear_and_nonlinear_markets(self):
        for case in benchmark.make_cases(270318, 35, 15, include_scale=False):
            with self.subTest(case=case.name):
                row = benchmark.evaluate_case(case, generous_limits())
                result = row["methods"]["improved_allocator"]
                self.assertTrue(result["completed"])
                self.assertLessEqual(result["oracle_gap"], benchmark.TOLERANCE)
                self.assertGreaterEqual(row["objective_gain"], -benchmark.TOLERANCE)
                self.assertTrue(all(result["invariants"].values()))

    def test_adversarial_cases_expose_legacy_local_search_limits(self):
        for case in benchmark.adversarial_cases():
            with self.subTest(case=case.name):
                row = benchmark.evaluate_case(case, generous_limits())
                self.assertGreater(row["objective_gain"], 0.1)
                self.assertLessEqual(row["methods"]["improved_allocator"]["oracle_gap"], benchmark.TOLERANCE)
        bundle = benchmark.evaluate_case(benchmark.adversarial_cases()[-1], generous_limits())
        self.assertAlmostEqual(bundle["methods"]["legacy_heuristic"]["objective"], 0)
        self.assertIsNone(bundle["relative_objective_gain"])

    def test_permuted_input_order_preserves_selected_assignment_and_objective(self):
        cases = (*benchmark.seeded_linear_cases(6, 41), *benchmark.seeded_modeled_cases(4, 41))
        for case in cases:
            with self.subTest(case=case.name):
                limits = generous_limits()
                original = allocate_global(case.snapshot, limits, PlanningBudget(limits, lambda: 0))
                permuted_snapshot = replace(
                    case.snapshot,
                    edges=tuple(reversed(case.snapshot.edges)),
                    vacancies=tuple(reversed(case.snapshot.vacancies)),
                )
                permuted = allocate_global(permuted_snapshot, limits, PlanningBudget(limits, lambda: 0))
                self.assertAlmostEqual(original.objective, permuted.objective)
                self.assertEqual(
                    {entry.vacancy_id: set(entry.candidates) for entry in original.vacancies},
                    {entry.vacancy_id: set(entry.candidates) for entry in permuted.vacancies},
                )

    def test_validator_catches_misreported_objectives_stale_provenance_and_certification(self):
        snapshot = benchmark.boundary_cases()[0].snapshot
        limits = generous_limits()
        plan = allocate_global(snapshot, limits, PlanningBudget(limits, lambda: 0))
        for corrupted in (
            replace(plan, objective=plan.objective + 0.1),
            replace(plan, snapshot_hash="stale"),
            replace(plan, mode="LIVE"),
            replace(
                plan,
                vacancies=(replace(plan.vacancies[0], certification_state="CERTIFIED"), *plan.vacancies[1:]),
            ),
        ):
            with self.subTest(corrupted=corrupted), self.assertRaises(ValueError):
                benchmark.validate_plan(snapshot, corrupted, snapshot.digest)

    def test_budget_exhaustion_is_recorded_without_fabricated_plan_or_objective(self):
        row = benchmark.evaluate_case(benchmark.adversarial_cases()[-1], PlannerLimits(max_operations=0))
        for method in row["methods"].values():
            self.assertFalse(method["completed"])
            self.assertEqual(method["reason"], "PLANNING_BUDGET_EXCEEDED_NO_PLAN")
            self.assertNotIn("objective", method)
        self.assertIsNone(row["objective_gain"])
        summary = benchmark.summarize([row])["all_cases"]
        self.assertEqual(summary["methods"]["improved_allocator"]["budget_exhausted"], 1)
        self.assertEqual(summary["methods"]["improved_allocator"]["oracle_checked"], 0)

    def test_report_preserves_provenance_limits_and_synthetic_interpretation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            report = benchmark.run_benchmark(
                output, linear_cases=2, modeled_cases=2, include_scale=False, threshold_cases=6
            )
            protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((output / "report.json").read_text(encoding="utf-8")), report)
            self.assertTrue(report["fictional_data"])
            self.assertFalse(report["external_data_used"])
            self.assertFalse(report["live_execution"])
            self.assertEqual(report["certification_state"], "CANNOT_CERTIFY")
            self.assertEqual(protocol["seed"], 270318)
            self.assertEqual(protocol["threshold_cases"], 6)
            self.assertEqual(
                protocol["independent_oracle_scope"], "raw_objective_upper_bound_without_target_fill_pruning"
            )
            self.assertIn("apps/api/app/matching/portfolio.py", protocol["source_sha256"])
            self.assertEqual(len(protocol["fixture_inventory"]), 17)
            self.assertEqual(report["summary"]["all_cases"]["objective_regressions"], 0)
            self.assertEqual(report["summary"]["threshold_policy"]["case_count"], 6)
            self.assertEqual(benchmark.check_report(report), [])
            with self.assertRaises(FileExistsError):
                benchmark.run_benchmark(output)

    def test_failed_evaluation_does_not_publish_partial_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            with patch.object(benchmark, "evaluate_case", side_effect=ValueError("invalid plan")):
                with self.assertRaisesRegex(ValueError, "invalid plan"):
                    benchmark.run_benchmark(output, linear_cases=0, modeled_cases=0, include_scale=False)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
