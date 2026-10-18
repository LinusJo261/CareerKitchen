"""Offline allocation benchmark on declared fictional markets; never hiring accuracy.

The oracle enumerates assignments and evaluates the scenario equations directly.
It does not call the allocator's objective, risk, exchange, or optimization helpers.
No network, database, training data, JTH data, or production execution is involved.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import platform
import random
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from math import isclose, prod
from pathlib import Path
from time import perf_counter
from typing import Any

from app.matching.portfolio import (
    Commitment,
    GlobalPlan,
    MarketSnapshot,
    ResearchEdge,
    VacancyResearch,
    allocate_global,
    allocate_heuristic,
)
from app.matching.runtime import PlannerLimits, PlanningBudget, PlanningBudgetExceeded
from app.matching.scenario import CandidateProbability, RiskScenario, ScenarioModel
from app.matching.shadow_adapter import run_shadow

PROTOCOL_VERSION = "stipulated-allocation-oracle-v1"
DEFAULT_SEED = 270318
TOLERANCE = 1e-9
LIMITATIONS = [
    "All markets, routing values, costs and scenario probabilities are stipulated synthetic inputs, not observed people or hiring outcomes.",
    "Objective improvement measures optimization of the declared mathematical objective, not matching accuracy, mutual interest, employment or welfare.",
    "Adversarial cases deliberately expose known failure modes; their gains do not estimate gains in production.",
    "Seeded cases are software stress tests, not representative samples from a real marketplace; no significance or reliability claim is made.",
    "The independent exhaustive oracle is restricted to tiny markets; the larger sparse case has no independently established optimum.",
    "The exhaustive oracle maximizes the raw objective without target-fill pruning; threshold-policy outputs can remain below this upper bound, which is not itself a feasible policy optimum.",
    "Runtime is descriptive for this machine and run; operation limits are cooperative and do not establish a hard process deadline.",
    "Shortlist limits are hypothetical planning constraints, not permission to issue cards or reserve candidates; live consent, double opt-in and attention checks remain separate.",
    "Experimental planning remains read-only SHADOW and every vacancy retains CANNOT_CERTIFY.",
]


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    family: str
    snapshot: MarketSnapshot
    exhaustive_oracle: bool = True


@dataclass(frozen=True)
class OracleResult:
    objective: float
    allocation: tuple[tuple[str, tuple[str, ...]], ...]
    feasible_assignments: int
    upper_state_count: int


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _direct_risk(members: set[str], models: tuple[ScenarioModel, ...]) -> float | None:
    """Independent transcription of the declared weighted conditional risk model."""
    if not models:
        return None
    risks = []
    for model in models:
        if not model.conditional_independence_asserted:
            return None
        mixture = 0.0
        for scenario in model.scenarios:
            successes = {entry.candidate_id: entry.success for entry in scenario.candidates}
            if not members.issubset(successes):
                return None
            conditional_nonfill = prod(1.0 - successes[candidate] for candidate in sorted(members))
            mixture += scenario.weight * (
                scenario.job_wide_failure + (1.0 - scenario.job_wide_failure) * conditional_nonfill
            )
        risks.append(min(1.0, max(0.0, mixture)))
    return max(risks)


def independent_objective(snapshot: MarketSnapshot, allocation: dict[str, set[str]]) -> float:
    """Evaluate a complete assignment independently, including fixed/shared claims."""
    fixed = {(entry.candidate_id, entry.vacancy_id) for entry in snapshot.commitments}
    fixed_roles: dict[str, set[str]] = defaultdict(set)
    for candidate, vacancy in fixed:
        fixed_roles[candidate].add(vacancy)
    competition_unknown = {vacancy for roles in fixed_roles.values() if len(roles) > 1 for vacancy in roles}
    edges = {edge.pair: edge for edge in snapshot.edges if edge.eligible and edge.candidate_opted_in}
    result = 0.0
    fixed_candidates = set(fixed_roles)
    for definition in snapshot.vacancies:
        vacancy_id = definition.vacancy_id
        members = allocation[vacancy_id]
        fixed_members = {candidate for candidate, role in fixed if role == vacancy_id}
        feasible_population = fixed_members | {
            candidate
            for candidate, role in edges
            if role == vacancy_id
            and candidate not in fixed_candidates
            and len(fixed_members) < definition.shortlist_limit
        }
        # Model support is determined once over the optimization-feasible pool,
        # never switched between modeled and routing units as subsets change.
        population_supported = _direct_risk(feasible_population, definition.models) is not None
        risk = (
            None
            if vacancy_id in competition_unknown or not population_supported
            else _direct_risk(members, definition.models)
        )
        costs = sum(
            edges[(candidate, vacancy_id)].attention_cost + edges[(candidate, vacancy_id)].delay_cost
            for candidate in sorted(members)
            if (candidate, vacancy_id) in edges and (candidate, vacancy_id) not in fixed
        )
        if risk is None:
            value = sum(
                edges[(candidate, vacancy_id)].routing_value
                for candidate in sorted(members)
                if (candidate, vacancy_id) in edges
            )
        else:
            value = 1.0 - risk
        result += value - costs
    return result


def exhaustive_oracle(snapshot: MarketSnapshot, max_states: int = 2_000_000) -> OracleResult:
    """Enumerate candidate-to-vacancy assignments, with an explicit size guard.

    This deliberately uses no production search, pruning, scenario helper or
    solver. The bound is checked before enumeration, so it cannot silently return
    a partial optimum. Existing human commitments may exceed a reduced limit.
    """
    if type(max_states) is not int or max_states < 1:
        raise ValueError("max_states must be a positive integer")
    jobs = {vacancy.vacancy_id: vacancy for vacancy in snapshot.vacancies}
    fixed: dict[str, set[str]] = {vacancy: set() for vacancy in jobs}
    fixed_candidates = {commitment.candidate_id for commitment in snapshot.commitments}
    for commitment in snapshot.commitments:
        fixed[commitment.vacancy_id].add(commitment.candidate_id)
    choices: dict[str, set[str]] = defaultdict(set)
    for edge in snapshot.edges:
        if edge.eligible and edge.candidate_opted_in and edge.candidate_id not in fixed_candidates:
            choices[edge.candidate_id].add(edge.vacancy_id)
    candidates = sorted(choices)
    alternatives = [(None, *sorted(choices[candidate])) for candidate in candidates]
    state_count = prod(len(values) for values in alternatives)
    if state_count > max_states:
        raise ValueError(f"Independent oracle state bound {state_count} exceeds {max_states}")
    best_value = float("-inf")
    best: tuple[tuple[str, tuple[str, ...]], ...] = ()
    checked = 0
    for assignment in itertools.product(*alternatives):
        trial = {vacancy: set(members) for vacancy, members in fixed.items()}
        feasible = True
        for candidate, vacancy in zip(candidates, assignment, strict=True):
            if vacancy is None:
                continue
            if len(trial[vacancy]) >= jobs[vacancy].shortlist_limit:
                feasible = False
                break
            trial[vacancy].add(candidate)
        if not feasible:
            continue
        checked += 1
        value = independent_objective(snapshot, trial)
        encoded = tuple((vacancy, tuple(sorted(members))) for vacancy, members in sorted(trial.items()))
        if value > best_value + 1e-12 or (
            isclose(value, best_value, abs_tol=1e-12, rel_tol=0) and encoded < best
        ):
            best_value, best = value, encoded
    return OracleResult(best_value, best, checked, state_count)


def validate_plan(snapshot: MarketSnapshot, plan: GlobalPlan, original_hash: str) -> dict[str, bool]:
    """Fail the benchmark on feasibility, immutable-input or objective violations."""
    jobs = {entry.vacancy_id: entry for entry in snapshot.vacancies}
    fixed: dict[str, set[str]] = {vacancy: set() for vacancy in jobs}
    fixed_candidates = {entry.candidate_id for entry in snapshot.commitments}
    for commitment in snapshot.commitments:
        fixed[commitment.vacancy_id].add(commitment.candidate_id)
    allowed = {edge.pair for edge in snapshot.edges if edge.eligible and edge.candidate_opted_in}
    allocation = {entry.vacancy_id: set(entry.candidates) for entry in plan.vacancies}
    if set(allocation) != set(jobs) or len(plan.vacancies) != len(jobs):
        raise ValueError("Planner omitted or duplicated an enrolled vacancy")
    new_candidates: list[str] = []
    for plan_entry in plan.vacancies:
        vacancy = plan_entry.vacancy_id
        if len(plan_entry.candidates) != len(allocation[vacancy]):
            raise ValueError("Planner duplicated a candidate within a shortlist")
        if (
            not fixed[vacancy].issubset(allocation[vacancy])
            or set(plan_entry.fixed_candidates) != fixed[vacancy]
        ):
            raise ValueError("Planner changed an existing human commitment")
        if len(allocation[vacancy]) > max(jobs[vacancy].shortlist_limit, len(fixed[vacancy])):
            raise ValueError("Planner exceeded a hypothetical shortlist limit")
        for candidate in allocation[vacancy] - fixed[vacancy]:
            if candidate in fixed_candidates or (candidate, vacancy) not in allowed:
                raise ValueError("Planner reused a fixed candidate or proposed an unauthorized edge")
            new_candidates.append(candidate)
        if plan_entry.certification_state != "CANNOT_CERTIFY":
            raise ValueError("Research benchmark cannot issue reliability certification")
    if len(new_candidates) != len(set(new_candidates)):
        raise ValueError("Planner allocated the same contingent candidate to several vacancies")
    if snapshot.digest != original_hash or plan.snapshot_hash != original_hash:
        raise ValueError("Planner mutated the snapshot or returned stale provenance")
    if plan.mode != "SHADOW":
        raise ValueError("Experimental planner left read-only shadow mode")
    direct = independent_objective(snapshot, allocation)
    if not isclose(direct, plan.objective, abs_tol=TOLERANCE, rel_tol=1e-10):
        raise ValueError(f"Reported objective {plan.objective} differs from independent replay {direct}")
    return {
        "all_enrolled_vacancies_retained": True,
        "fixed_human_commitments_retained": True,
        "shortlist_limits_respected": True,
        "contingent_candidates_not_double_counted": True,
        "only_eligible_opted_in_edges_proposed": True,
        "snapshot_unchanged": True,
        "independent_objective_replay": True,
        "shadow_and_cannot_certify": True,
    }


def _model(version: str, probabilities: dict[str, float], failure: float = 0.0) -> ScenarioModel:
    return ScenarioModel(
        version,
        (
            RiskScenario(
                "stipulated-scenario",
                1.0,
                tuple(
                    CandidateProbability(candidate, success)
                    for candidate, success in sorted(probabilities.items())
                ),
                failure,
                "fictional-benchmark-v1",
            ),
        ),
        True,
    )


def adversarial_cases() -> tuple[BenchmarkCase, ...]:
    cases = []
    for size in (4, 6, 9):
        # A high edge blocks a chain; every local pairwise repair is inferior to
        # the complete cycle. Reassignment length grows while degree stays two.
        edges = [ResearchEdge(f"c{index}", f"j{index}", 1.0) for index in range(size)]
        edges.extend(
            ResearchEdge(f"c{index}", f"j{(index + 1) % size}", 1.5 if index == size - 1 else 0.99)
            for index in range(size)
        )
        cases.append(
            BenchmarkCase(
                f"augmenting-cycle-{size}",
                "adversarial_linear",
                MarketSnapshot(
                    f"fictional-cycle-{size}",
                    tuple(VacancyResearch(f"j{index}", 1, 1) for index in range(size)),
                    tuple(edges),
                ),
            )
        )
    bundle = MarketSnapshot(
        "fictional-complementary-bundle",
        (
            VacancyResearch(
                "j",
                1,
                2,
                (
                    _model("stipulated-world-a", {"x": 1.0, "y": 0.0}),
                    _model("stipulated-world-b", {"x": 0.0, "y": 1.0}),
                ),
                target_fill=1.0,
            ),
        ),
        (ResearchEdge("x", "j", 0.5, 0.02), ResearchEdge("y", "j", 0.5, 0.02)),
    )
    cases.append(BenchmarkCase("complementary-bundle-zero-singleton-gain", "adversarial_modeled", bundle))
    return tuple(cases)


def boundary_cases() -> tuple[BenchmarkCase, ...]:
    jobs = (VacancyResearch("a", 1, 1), VacancyResearch("b", 1, 2), VacancyResearch("closed", 1, 0))
    edges = (
        ResearchEdge("fixed", "a", 0.4),
        ResearchEdge("fixed", "b", 100.0),
        ResearchEdge("x", "a", 1.0),
        ResearchEdge("x", "b", 0.6, 0.1),
        ResearchEdge("y", "b", 0.7, 0.1, 0.1),
        ResearchEdge("private", "b", 999.0, candidate_opted_in=False),
        ResearchEdge("ineligible", "b", 999.0, eligible=False),
        ResearchEdge("closed-only", "closed", 999.0),
        ResearchEdge("costly", "b", 0.1, 0.2),
    )
    fixed = MarketSnapshot(
        "fictional-boundaries", jobs, edges, (Commitment("fixed", "a", "ACTIVE_DECISION"),)
    )
    shared = MarketSnapshot(
        "fictional-shared-commitments",
        (
            VacancyResearch("a", 1, 1, (_model("stipulated-a", {"shared": 0.9, "new": 0.8}),)),
            VacancyResearch("b", 1, 1, (_model("stipulated-b", {"shared": 0.9, "new": 0.8}),)),
            VacancyResearch("empty", 1, 0),
        ),
        (ResearchEdge("shared", "a", 0.7), ResearchEdge("shared", "b", 0.6), ResearchEdge("new", "a", 0.8)),
        (Commitment("shared", "a", "ACTIVE_DECISION"), Commitment("shared", "b", "ACTIVE_DECISION")),
    )
    return (
        BenchmarkCase("eligibility-consent-costs-and-fixed-commitment", "boundary", fixed),
        BenchmarkCase("shared-live-commitments-and-empty-vacancy", "boundary", shared),
        BenchmarkCase("empty-market", "boundary", MarketSnapshot("fictional-empty", (), ())),
    )


def seeded_linear_cases(count: int, seed: int) -> Iterable[BenchmarkCase]:
    rng = random.Random(seed)
    for case in range(count):
        jobs = tuple(VacancyResearch(f"j{vacancy}", 1, 1) for vacancy in range(4))
        edges = tuple(
            ResearchEdge(f"c{candidate}", f"j{vacancy}", rng.randint(1, 100) / 100)
            for candidate in range(4)
            for vacancy in range(4)
            if rng.random() < 0.65
        )
        yield BenchmarkCase(
            f"seeded-linear-{case:04d}",
            "seeded_linear",
            MarketSnapshot(f"fictional-linear-{seed}-{case}", jobs, edges),
        )


def seeded_modeled_cases(count: int, seed: int) -> Iterable[BenchmarkCase]:
    rng = random.Random(seed + 1)
    candidates = tuple(f"c{index}" for index in range(4))
    for case in range(count):
        jobs = []
        for vacancy in range(3):
            models = []
            for alternative in range(2):
                scenarios = tuple(
                    RiskScenario(
                        f"stipulated-scenario-{scenario}",
                        0.5,
                        tuple(
                            CandidateProbability(candidate, rng.choice((0.05, 0.2, 0.5, 0.8, 0.95)))
                            for candidate in candidates
                        ),
                        rng.choice((0.0, 0.05)),
                        "fictional-benchmark-v1",
                    )
                    for scenario in range(2)
                )
                models.append(ScenarioModel(f"stipulated-model-{alternative}", scenarios, True))
            jobs.append(VacancyResearch(f"j{vacancy}", 1, rng.randint(1, 2), tuple(models), target_fill=1.0))
        edges = tuple(
            ResearchEdge(candidate, f"j{vacancy}", 0.5, rng.randint(0, 6) / 100, rng.randint(0, 3) / 100)
            for candidate in candidates
            for vacancy in range(3)
            if rng.random() < 0.75
        )
        yield BenchmarkCase(
            f"seeded-modeled-{case:04d}",
            "seeded_modeled",
            MarketSnapshot(f"fictional-modeled-{seed}-{case}", tuple(jobs), edges),
        )


def seeded_threshold_policy_cases(count: int, seed: int) -> Iterable[BenchmarkCase]:
    """Exercise final shortlist pruning with a separate deterministic random stream."""
    rng = random.Random(seed + 3)
    candidates = tuple(f"c{index}" for index in range(4))
    thresholds = (0.0, 0.5, 0.8, 0.95, 0.999, 1.0)
    for case in range(count):
        target = thresholds[case % len(thresholds)]
        jobs = []
        for vacancy in range(3):
            models = []
            for alternative in range(2):
                scenarios = tuple(
                    RiskScenario(
                        f"stipulated-scenario-{scenario}",
                        0.5,
                        tuple(
                            CandidateProbability(candidate, rng.choice((0.05, 0.2, 0.5, 0.8, 0.95)))
                            for candidate in candidates
                        ),
                        rng.choice((0.0, 0.05)),
                        "fictional-benchmark-v1",
                    )
                    for scenario in range(2)
                )
                models.append(ScenarioModel(f"stipulated-model-{alternative}", scenarios, True))
            jobs.append(
                VacancyResearch(f"j{vacancy}", 1, rng.randint(1, 2), tuple(models), target_fill=target)
            )
        edges = tuple(
            ResearchEdge(candidate, f"j{vacancy}", 0.5, rng.randint(0, 6) / 100, rng.randint(0, 3) / 100)
            for candidate in candidates
            for vacancy in range(3)
            if rng.random() < 0.75
        )
        yield BenchmarkCase(
            f"seeded-threshold-policy-{case:04d}",
            "threshold_policy",
            MarketSnapshot(f"fictional-threshold-policy-{seed}-{case}", tuple(jobs), edges),
        )


def sparse_scale_case(seed: int) -> BenchmarkCase:
    rng = random.Random(seed + 2)
    jobs = tuple(VacancyResearch(f"j{index:03d}", 1, 2) for index in range(40))
    edges = tuple(
        ResearchEdge(
            f"c{candidate:03d}", f"j{vacancy:03d}", rng.randint(10, 100) / 100, rng.randint(0, 8) / 100
        )
        for candidate in range(80)
        for vacancy in sorted(rng.sample(range(40), 4))
    )
    return BenchmarkCase(
        "sparse-80-candidates-40-vacancies-320-edges",
        "bounded_sparse_scale",
        MarketSnapshot(f"fictional-scale-{seed}", jobs, edges),
        exhaustive_oracle=False,
    )


def default_shadow_scale_cases(seed: int) -> tuple[MarketSnapshot, ...]:
    """Worker-shaped sparse and dense pools, using the actual default sidecar budget."""
    result = []
    for degree in (4, 20):
        rng = random.Random(seed + 10 + degree)
        jobs = tuple(VacancyResearch(f"j{index:03d}", 1, 10) for index in range(20))
        edges = tuple(
            ResearchEdge(
                f"c{candidate:03d}", f"j{vacancy:03d}", rng.randint(10, 100) / 100, rng.randint(0, 8) / 100
            )
            for candidate in range(100)
            for vacancy in sorted(rng.sample(range(20), degree))
        )
        result.append(MarketSnapshot(f"fictional-default-shadow-degree-{degree}-seed-{seed}", jobs, edges))
    return tuple(result)


def evaluate_default_shadow(snapshot: MarketSnapshot) -> dict[str, Any]:
    original_hash = snapshot.digest
    started = perf_counter()
    result = run_shadow(snapshot, (), enabled=True)
    elapsed = perf_counter() - started
    baseline_preserved = result.baseline_proposals == ()
    if not baseline_preserved or result.side_effect_count != 0:
        raise ValueError("Default shadow trial changed baseline proposals or produced side effects")
    row: dict[str, Any] = {
        "snapshot_sha256": original_hash,
        "vacancy_count": len(snapshot.vacancies),
        "candidate_count": len({edge.candidate_id for edge in snapshot.edges}),
        "sparse_edge_count": len(snapshot.edges),
        "actual_default_limits": asdict(PlannerLimits()),
        "completed": result.advanced_plan is not None,
        "reasons": list(result.reasons),
        "seconds_including_sidecar_hashing": elapsed,
        "reported_shadow_seconds": result.elapsed_seconds,
        "baseline_preserved": baseline_preserved,
        "side_effect_count": result.side_effect_count,
        "independent_oracle_available": False,
    }
    if result.advanced_plan is not None:
        row["invariants"] = validate_plan(snapshot, result.advanced_plan, original_hash)
        row["operation_count"] = result.advanced_plan.operation_count
        row["objective"] = result.advanced_plan.objective
        row["solver"] = result.advanced_plan.solver
    return row


def make_cases(
    seed: int = DEFAULT_SEED,
    linear_cases: int = 300,
    modeled_cases: int = 60,
    include_scale: bool = True,
    *,
    threshold_cases: int = 0,
) -> tuple[BenchmarkCase, ...]:
    if type(seed) is not int or any(
        type(count) is not int or count < 0 for count in (linear_cases, modeled_cases, threshold_cases)
    ):
        raise ValueError("Seed must be an integer and case counts must be nonnegative integers")
    cases = (
        *adversarial_cases(),
        *boundary_cases(),
        *seeded_linear_cases(linear_cases, seed),
        *seeded_modeled_cases(modeled_cases, seed),
        *seeded_threshold_policy_cases(threshold_cases, seed),
    )
    return (*cases, sparse_scale_case(seed)) if include_scale else cases


def evaluate_case(case: BenchmarkCase, limits: PlannerLimits) -> dict:
    original_hash = case.snapshot.digest
    oracle = exhaustive_oracle(case.snapshot) if case.exhaustive_oracle else None
    oracle_payload = asdict(oracle) if oracle else None
    if oracle is not None and oracle_payload is not None:
        oracle_payload["allocation"] = [[vacancy, list(members)] for vacancy, members in oracle.allocation]
    row: dict[str, Any] = {
        "name": case.name,
        "family": case.family,
        "snapshot_sha256": original_hash,
        "candidate_count": len({edge.candidate_id for edge in case.snapshot.edges}),
        "vacancy_count": len(case.snapshot.vacancies),
        "sparse_edge_count": len(case.snapshot.edges),
        "oracle": oracle_payload,
        "methods": {},
    }
    planners: tuple[tuple[str, Callable[..., GlobalPlan]], ...] = (
        ("legacy_heuristic", allocate_heuristic),
        ("improved_allocator", allocate_global),
    )
    for method, planner in planners:
        started = perf_counter()
        work = PlanningBudget(limits)
        try:
            plan = planner(case.snapshot, limits, work)
        except PlanningBudgetExceeded:
            row["methods"][method] = {
                "completed": False,
                "reason": "PLANNING_BUDGET_EXCEEDED_NO_PLAN",
                "seconds": perf_counter() - started,
                "operation_count": work.operations,
            }
            continue
        elapsed = perf_counter() - started
        checks = validate_plan(case.snapshot, plan, original_hash)
        if oracle is not None and plan.objective > oracle.objective + TOLERANCE:
            raise ValueError("Planner exceeded independent exhaustive optimum")
        gap = max(0.0, oracle.objective - plan.objective) if oracle is not None else None
        row["methods"][method] = {
            "completed": True,
            "objective": plan.objective,
            "oracle_gap": gap,
            "relative_oracle_gap": gap / oracle.objective
            if gap is not None and oracle is not None and oracle.objective > 0
            else None,
            "seconds": elapsed,
            "operation_count": plan.operation_count,
            "solver": getattr(plan, "solver", "legacy_heuristic"),
            "search_complete": getattr(plan, "search_complete", False),
            "expected_fills_under_stipulated_models": plan.expected_fills,
            "invariants": checks,
            "allocation_sha256": _digest(
                [(item.vacancy_id, sorted(item.candidates)) for item in plan.vacancies]
            ),
        }
    old, new = row["methods"]["legacy_heuristic"], row["methods"]["improved_allocator"]
    row["objective_gain"] = (
        new["objective"] - old["objective"] if old["completed"] and new["completed"] else None
    )
    row["relative_objective_gain"] = (
        row["objective_gain"] / old["objective"]
        if row["objective_gain"] is not None and old["objective"] > 0
        else None
    )
    if case.snapshot.digest != original_hash:
        raise ValueError("Benchmark observed a mutated immutable input")
    return row


def summarize(rows: list[dict]) -> dict:
    result = {}
    for family in sorted({row["family"] for row in rows} | {"all_cases"}):
        selected = rows if family == "all_cases" else [row for row in rows if row["family"] == family]
        methods = {}
        for method in ("legacy_heuristic", "improved_allocator"):
            completed = [row["methods"][method] for row in selected if row["methods"][method]["completed"]]
            checked = [entry for entry in completed if entry["oracle_gap"] is not None]
            methods[method] = {
                "completed": len(completed),
                "budget_exhausted": len(selected) - len(completed),
                "oracle_checked": len(checked),
                "oracle_optimum_count": sum(entry["oracle_gap"] <= TOLERANCE for entry in checked),
                "mean_oracle_gap": sum(entry["oracle_gap"] for entry in checked) / len(checked)
                if checked
                else None,
                "maximum_oracle_gap": max((entry["oracle_gap"] for entry in checked), default=None),
                "total_seconds": sum(row["methods"][method]["seconds"] for row in selected),
                "maximum_seconds": max((row["methods"][method]["seconds"] for row in selected), default=0),
                "maximum_operations": max(
                    (row["methods"][method]["operation_count"] for row in selected), default=0
                ),
            }
        paired = [row for row in selected if row["objective_gain"] is not None]
        result[family] = {
            "case_count": len(selected),
            "methods": methods,
            "paired_completed": len(paired),
            "strict_objective_improvements": sum(row["objective_gain"] > TOLERANCE for row in paired),
            "objective_regressions": sum(row["objective_gain"] < -TOLERANCE for row in paired),
            "mean_objective_gain": sum(row["objective_gain"] for row in paired) / len(paired)
            if paired
            else None,
        }
    return result


def check_report(report: dict) -> list[str]:
    """Return CI failures without mistaking policy limits for objective optima."""
    failures = []
    cases = report.get("cases", [])
    if not cases:
        failures.append("No paired allocator comparisons were recorded")
    for row in cases:
        name = row.get("name", "unnamed case")
        methods = row.get("methods", {})
        paired = []
        for method in ("legacy_heuristic", "improved_allocator"):
            entry = methods.get(method)
            if not entry or not entry.get("completed") or "objective" not in entry:
                failures.append(f"{name}: missing completed {method} comparison")
                continue
            paired.append(entry)
            gap = entry.get("oracle_gap")
            if entry.get("search_complete") and gap is not None and gap > TOLERANCE:
                failures.append(f"{name}: {method} claims complete search below the raw oracle optimum")
        if len(paired) == 2 and paired[1]["objective"] < paired[0]["objective"] - TOLERANCE:
            failures.append(f"{name}: improved allocator regressed against the preserved reference")
    for index, trial in enumerate(report.get("default_shadow_trials", [])):
        if not trial.get("completed"):
            failures.append(f"Default shadow trial {index}: no completed advanced plan")
    return failures


def run_benchmark(
    output: Path,
    seed: int = DEFAULT_SEED,
    linear_cases: int = 300,
    modeled_cases: int = 60,
    include_scale: bool = True,
    limits: PlannerLimits | None = None,
    *,
    threshold_cases: int = 0,
) -> dict:
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    chosen_limits = limits or PlannerLimits(
        max_seconds=10, max_operations=2_000_000, max_edges=2_000, exchange_steps=20
    )
    cases = make_cases(seed, linear_cases, modeled_cases, include_scale, threshold_cases=threshold_cases)
    default_shadow_snapshots = default_shadow_scale_cases(seed) if include_scale else ()
    root = Path(__file__).resolve().parents[1]
    sources = [Path(__file__).resolve(), *sorted((root / "apps/api/app/matching").glob("*.py"))]
    protocol = {
        "protocol_version": PROTOCOL_VERSION,
        "source_kind": "stipulated_synthetic_market_fixtures",
        "seed": seed,
        "linear_cases": linear_cases,
        "modeled_cases": modeled_cases,
        "threshold_cases": threshold_cases,
        "include_scale": include_scale,
        "limits_per_method_per_case": asdict(chosen_limits),
        "independent_oracle_max_states": 2_000_000,
        "independent_oracle_scope": "raw_objective_upper_bound_without_target_fill_pruning",
        "comparison_tolerance": TOLERANCE,
        "python_version": platform.python_version(),
        "source_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
        "fixture_inventory": [
            {"name": case.name, "family": case.family, "snapshot_sha256": case.snapshot.digest}
            for case in cases
        ],
        "default_shadow_fixture_sha256": [snapshot.digest for snapshot in default_shadow_snapshots],
        "actual_default_shadow_limits": asdict(PlannerLimits()),
        "fictional_data": True,
        "external_data_used": False,
        "live_execution": False,
        "mode": "SHADOW",
        "limitations": LIMITATIONS,
    }
    # Fix provenance and parameters before executing either method.
    serialized_protocol = json.dumps(protocol, indent=2, sort_keys=True, allow_nan=False) + "\n"
    rows = [evaluate_case(case, chosen_limits) for case in cases]
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": hashlib.sha256(serialized_protocol.encode("utf-8")).hexdigest(),
        "fixture_inventory_sha256": _digest(protocol["fixture_inventory"]),
        "fictional_data": True,
        "external_data_used": False,
        "live_execution": False,
        "mode": "SHADOW",
        "certification_state": "CANNOT_CERTIFY",
        "objective_kind": "stipulated_routing_or_robust_modeled_fill_less_declared_costs",
        "independent_oracle_scope": "raw_objective_upper_bound_without_target_fill_pruning",
        "summary": summarize(rows),
        "cases": rows,
        "default_shadow_trials": [evaluate_default_shadow(snapshot) for snapshot in default_shadow_snapshots],
        "limitations": LIMITATIONS,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".allocator-benchmark-", dir=output.parent) as temporary:
        staged = Path(temporary) / "complete"
        staged.mkdir()
        (staged / "protocol.json").write_text(serialized_protocol, encoding="utf-8")
        (staged / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise FileExistsError("Output appeared during evaluation; refusing to overwrite")
        staged.rename(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--linear-cases", type=int, default=300)
    parser.add_argument("--modeled-cases", type=int, default=60)
    parser.add_argument("--threshold-cases", type=int, default=0)
    parser.add_argument("--skip-scale", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero for regressions, missing comparisons or invalid optimality metadata",
    )
    arguments = parser.parse_args()
    report = run_benchmark(
        arguments.output,
        arguments.seed,
        arguments.linear_cases,
        arguments.modeled_cases,
        not arguments.skip_scale,
        threshold_cases=arguments.threshold_cases,
    )
    print("Stipulated synthetic allocation benchmark; no real hiring accuracy is measured.")
    for family, summary in report["summary"].items():
        old = summary["methods"]["legacy_heuristic"]
        new = summary["methods"]["improved_allocator"]
        print(
            f"{family}: old oracle optima {old['oracle_optimum_count']}/{old['oracle_checked']}; "
            f"new {new['oracle_optimum_count']}/{new['oracle_checked']}; "
            f"improved {summary['strict_objective_improvements']}; regressions {summary['objective_regressions']}; "
            f"budget exhaustion old/new {old['budget_exhausted']}/{new['budget_exhausted']}"
        )
    for trial in report["default_shadow_trials"]:
        print(
            f"default shadow {trial['candidate_count']} candidates/{trial['vacancy_count']} vacancies/"
            f"{trial['sparse_edge_count']} edges: completed={trial['completed']}, "
            f"seconds={trial['seconds_including_sidecar_hashing']:.4f}, operations={trial.get('operation_count')}"
        )
    print(f"Report: {arguments.output / 'report.json'}")
    if arguments.check:
        failures = check_report(report)
        for failure in failures:
            print(f"CHECK FAILED: {failure}")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
