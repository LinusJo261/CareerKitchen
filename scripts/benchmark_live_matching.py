"""Independent synthetic attention-allocation checks for the current live planner.

This measures supplied routing utility and native attention feasibility. It does
not measure matching, mutual interest, hiring, or employment prediction accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.matching.live import AttentionCapacity, LiveProposal, allocate_live  # noqa: E402
from app.matching.runtime import PlannerLimits  # noqa: E402
from app.matching.types import Side  # noqa: E402

TOLERANCE = 1e-10
DEFAULT_SEED = 20261018


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def feasible(selected, proposals, candidates, vacancies) -> bool:
    """Independent resource accounting; never calls planner allocation helpers."""
    supplied = {proposal.pair: proposal for proposal in proposals}
    if len({proposal.pair for proposal in selected}) != len(selected):
        return False
    usage: Counter[tuple[str, str, str]] = Counter()
    for proposal in selected:
        if supplied.get(proposal.pair) != proposal:
            return False
        candidate, vacancy = candidates.get(proposal.candidate_id), vacancies.get(proposal.vacancy_id)
        if candidate is None or vacancy is None:
            return False
        candidate_resource = (
            "active_remaining" if proposal.first_mover == Side.CANDIDATE else "waiting_remaining"
        )
        vacancy_resource = (
            "waiting_remaining" if proposal.first_mover == Side.CANDIDATE else "active_remaining"
        )
        usage[("candidate", proposal.candidate_id, candidate_resource)] += 1
        usage[("vacancy", proposal.vacancy_id, vacancy_resource)] += 1
        if usage[("candidate", proposal.candidate_id, candidate_resource)] > getattr(
            candidate, candidate_resource
        ) or usage[("vacancy", proposal.vacancy_id, vacancy_resource)] > getattr(vacancy, vacancy_resource):
            return False
    return True


def complete_greedy(proposals, candidates, vacancies) -> tuple:
    """Consume every positive proposal in descending utility, without early exit."""
    chosen: list[LiveProposal] = []
    candidate_usage: Counter[tuple[str, Side]] = Counter()
    vacancy_usage: Counter[tuple[str, Side]] = Counter()
    for proposal in sorted(proposals, key=lambda row: (-row.net_surplus, row.candidate_id, row.vacancy_id)):
        if proposal.net_surplus <= 1e-12:
            continue
        candidate, vacancy = candidates.get(proposal.candidate_id), vacancies.get(proposal.vacancy_id)
        if candidate is None or vacancy is None:
            continue
        candidate_limit = (
            candidate.active_remaining
            if proposal.first_mover == Side.CANDIDATE
            else candidate.waiting_remaining
        )
        vacancy_limit = (
            vacancy.waiting_remaining if proposal.first_mover == Side.CANDIDATE else vacancy.active_remaining
        )
        candidate_key, vacancy_key = (
            (proposal.candidate_id, proposal.first_mover),
            (proposal.vacancy_id, proposal.first_mover),
        )
        if candidate_usage[candidate_key] < candidate_limit and vacancy_usage[vacancy_key] < vacancy_limit:
            chosen.append(proposal)
            candidate_usage[candidate_key] += 1
            vacancy_usage[vacancy_key] += 1
    return tuple(chosen)


def exhaustive_oracle(proposals, candidates, vacancies) -> tuple[float, int]:
    if len(proposals) > 16:
        raise ValueError("Exhaustive oracle is bounded to 16 supplied edges")
    best, valid_subsets = 0.0, 0
    for mask in range(1 << len(proposals)):
        selected = tuple(proposal for index, proposal in enumerate(proposals) if mask & (1 << index))
        if feasible(selected, proposals, candidates, vacancies):
            valid_subsets += 1
            best = max(best, math.fsum(proposal.net_surplus for proposal in selected))
    return best, valid_subsets


def known_greedy_trap():
    return (
        (
            LiveProposal("c0", "v0", Side.CANDIDATE, 1),
            LiveProposal("c0", "v1", Side.CANDIDATE, 0.9),
            LiveProposal("c1", "v0", Side.CANDIDATE, 0.9),
        ),
        {name: AttentionCapacity(1, 10) for name in ("c0", "c1")},
        {name: AttentionCapacity(10, 1) for name in ("v0", "v1")},
    )


def small_market(rng: random.Random):
    values = (0, 1, 1, 2, 3, 10)
    candidates = {
        f"c{index}": AttentionCapacity(rng.choice(values), rng.choice(values)) for index in range(3)
    }
    vacancies = {f"v{index}": AttentionCapacity(rng.choice(values), rng.choice(values)) for index in range(3)}
    proposals = tuple(
        LiveProposal(candidate, vacancy, rng.choice(tuple(Side)), rng.randrange(-20, 101) / 100)
        for candidate in candidates
        for vacancy in vacancies
        if rng.random() < 0.85
    )
    return proposals, candidates, vacancies


def scale_market(rng: random.Random, edges: int):
    candidates = {
        f"c{index:03d}": AttentionCapacity(rng.randint(1, 4), rng.randint(1, 4)) for index in range(100)
    }
    vacancies = {
        f"v{index:02d}": AttentionCapacity(rng.randint(1, 7), rng.randint(1, 7)) for index in range(20)
    }
    pairs = rng.sample([(candidate, vacancy) for candidate in candidates for vacancy in vacancies], edges)
    proposals = tuple(
        LiveProposal(candidate, vacancy, rng.choice(tuple(Side)), rng.randrange(-10, 1001) / 1000)
        for candidate, vacancy in pairs
    )
    return proposals, candidates, vacancies


def _serialize(case_id, market, oracle):
    proposals, candidates, vacancies = market
    return {
        "case_id": case_id,
        "oracle": oracle,
        "proposals": [asdict(row) for row in proposals],
        "candidates": {key: asdict(value) for key, value in candidates.items()},
        "vacancies": {key: asdict(value) for key, value in vacancies.items()},
    }


def evaluate(case_id: str, market, *, oracle: bool) -> dict:
    proposals, candidates, vacancies = market
    start = perf_counter()
    greedy = complete_greedy(proposals, candidates, vacancies)
    greedy_seconds = perf_counter() - start
    start = perf_counter()
    result = allocate_live(proposals, candidates, vacancies)
    live_seconds = perf_counter() - start
    greedy_value = math.fsum(proposal.net_surplus for proposal in greedy)
    optimum, valid_subsets = exhaustive_oracle(proposals, candidates, vacancies) if oracle else (None, None)
    return {
        "case_id": case_id,
        "candidate_count": len(candidates),
        "vacancy_count": len(vacancies),
        "edge_count": len(proposals),
        "greedy_objective": greedy_value,
        "live_objective": result.objective,
        "objective_gain": result.objective - greedy_value,
        "relative_gain": (result.objective / greedy_value - 1) if greedy_value > 0 else None,
        "greedy_selected": len(greedy),
        "live_selected": len(result.proposals),
        "greedy_feasible": feasible(greedy, proposals, candidates, vacancies),
        "live_feasible": feasible(result.proposals, proposals, candidates, vacancies),
        "live_positive_only": all(row.net_surplus > 0 for row in result.proposals),
        "reported_baseline_matches_independent_greedy": abs(result.baseline_objective - greedy_value)
        <= TOLERANCE,
        "oracle_objective": optimum,
        "oracle_feasible_subsets": valid_subsets,
        "live_oracle_optimum": abs(result.objective - optimum) <= TOLERANCE if optimum is not None else None,
        "greedy_oracle_optimum": abs(greedy_value - optimum) <= TOLERANCE if optimum is not None else None,
        "search_complete": result.search_complete,
        "solver": result.solver,
        "fallback_reason": result.fallback_reason,
        "greedy_seconds": greedy_seconds,
        "live_seconds": live_seconds,
    }


def check_report(report: dict) -> list[str]:
    failures = []
    for result in report["cases"]:
        for name in (
            "greedy_feasible",
            "live_feasible",
            "live_positive_only",
            "reported_baseline_matches_independent_greedy",
        ):
            if result[name] is not True:
                failures.append(f"{result['case_id']}: {name}")
        if result["objective_gain"] < -TOLERANCE:
            failures.append(f"{result['case_id']}: objective regressed")
        if result["oracle_objective"] is not None and result["live_oracle_optimum"] is not True:
            failures.append(f"{result['case_id']}: missed independent exhaustive optimum")
    return failures


def run_benchmark(
    output: Path, seed: int = DEFAULT_SEED, small_cases: int = 1000, include_scale: bool = True
) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a fresh immutable benchmark directory")
    if type(seed) is not int or type(small_cases) is not int or not 1 <= small_cases <= 100000:
        raise ValueError("Use an integer seed and 1..100000 small cases")
    rng = random.Random(seed)
    markets = [("known-greedy-trap", known_greedy_trap(), True)]
    markets.extend((f"seeded-small-{index:05d}", small_market(rng), True) for index in range(1, small_cases))
    if include_scale:
        markets.extend((f"scale-{edges}-edges", scale_market(rng, edges), False) for edges in (400, 2000))
    serialized_inputs = "".join(
        _json(_serialize(case_id, market, oracle)) + "\n" for case_id, market, oracle in markets
    )
    cases = [evaluate(case_id, market, oracle=oracle) for case_id, market, oracle in markets]
    small = [case for case in cases if case["oracle_objective"] is not None]
    source_paths = [
        "scripts/benchmark_live_matching.py",
        "apps/api/app/matching/live.py",
        "apps/api/app/matching/assignment.py",
        "apps/api/app/matching/runtime.py",
        "apps/api/app/matching/types.py",
    ]
    report = {
        "schema_version": 1,
        "benchmark_kind": "synthetic_live_attention_allocation",
        "seed": seed,
        "small_case_count": small_cases,
        "include_scale": include_scale,
        "objective_kind": "supplied_routing_utility",
        "hiring_accuracy": None,
        "comparison_tolerance": TOLERANCE,
        "production_planner_limits": asdict(PlannerLimits()),
        "input_sha256": hashlib.sha256(serialized_inputs.encode()).hexdigest(),
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in source_paths
        },
        "summary": {
            "comparisons": len(cases),
            "strict_improvements": sum(case["objective_gain"] > TOLERANCE for case in cases),
            "regressions": sum(case["objective_gain"] < -TOLERANCE for case in cases),
            "live_feasible_plans": sum(case["live_feasible"] for case in cases),
            "greedy_feasible_plans": sum(case["greedy_feasible"] for case in cases),
            "oracle_checked": len(small),
            "live_oracle_optima": sum(case["live_oracle_optimum"] for case in small),
            "greedy_oracle_optima": sum(case["greedy_oracle_optimum"] for case in small),
            "complete_searches": sum(case["search_complete"] for case in cases),
        },
        "cases": cases,
        "limitations": [
            "Synthetic supplied utility measures allocation quality, not real matching or hiring accuracy.",
            "Business eligibility, consent, tenant isolation and transactional issuance are tested separately in PostgreSQL integration tests.",
            "Each synthetic proposal has one fixed preselected first mover; both native active and receiving attention resources are checked independently.",
            "The complete greedy comparator uses the same supplied proposals/capacities; it does not reproduce old retrieval omissions.",
            "Only small markets have independent exhaustive-subset optima; scale cases have no optimality certificate.",
            "Actual default production planning limits apply; timings depend on host load and do not enter correctness assertions.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve()
    staging = Path(tempfile.mkdtemp(prefix=".live-benchmark-", dir=parent))
    try:
        (staging / "inputs.jsonl").write_text(serialized_inputs, encoding="utf-8")
        (staging / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        if output.exists() or output.is_symlink():
            raise FileExistsError("Benchmark output appeared during evaluation")
        staging.rename(output)
    finally:
        if staging.exists():
            if staging.resolve().parent != parent or not staging.name.startswith(".live-benchmark-"):
                raise RuntimeError("Refusing cleanup outside the benchmark staging directory")
            shutil.rmtree(staging)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--small-cases", type=int, default=1000)
    parser.add_argument("--skip-scale", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(args.output, args.seed, args.small_cases, not args.skip_scale)
    print("Synthetic live-allocation utility benchmark; real hiring accuracy is unmeasured.")
    print(json.dumps(report["summary"], sort_keys=True))
    for case in report["cases"]:
        if case["oracle_objective"] is None:
            print(json.dumps(case, sort_keys=True))
    failures = check_report(report)
    for failure in failures:
        print("CHECK FAILED: " + failure)
    return int(args.check and bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
