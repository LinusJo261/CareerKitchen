"""Stipulated correlated scenario models; outputs are never empirical claims."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from math import ceil, isclose, log1p, prod

from .runtime import PlanningBudget, PlanningBudgetExceeded
from .types import probability


@dataclass(frozen=True, slots=True)
class CandidateProbability:
    candidate_id: str
    success: float

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate ID is required")
        probability(self.success, "conditional success")


@dataclass(frozen=True, slots=True)
class RiskScenario:
    scenario_id: str
    weight: float
    candidates: tuple[CandidateProbability, ...]
    job_wide_failure: float
    assumption_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        probability(self.weight, "scenario weight")
        probability(self.job_wide_failure, "job-wide failure")
        if not self.scenario_id or not self.assumption_version:
            raise ValueError("scenario and assumption versions are required")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate scenario candidate")


@dataclass(frozen=True, slots=True)
class ScenarioModel:
    version: str
    scenarios: tuple[RiskScenario, ...]
    conditional_independence_asserted: bool
    target: str = "VERIFIED_START_BY_DEADLINE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenarios", tuple(self.scenarios))
        if not self.version or not self.scenarios:
            raise ValueError("version and nonempty scenarios are required")
        if not isclose(sum(item.weight for item in self.scenarios), 1.0, abs_tol=1e-9, rel_tol=0):
            raise ValueError("scenario weights must sum to one")
        if len({item.scenario_id for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("duplicate scenario ID")
        if self.target != "VERIFIED_START_BY_DEADLINE":
            raise ValueError("research fill model must explicitly target verified starts by deadline")


def model_nonfill_risk(shortlist: Iterable[str], model: ScenarioModel) -> float | None:
    ids = tuple(shortlist)
    if len(set(ids)) != len(ids):
        raise ValueError("shortlist candidates must be distinct")
    if not model.conditional_independence_asserted:
        return None
    risk = 0.0
    for scenario in model.scenarios:
        lookup = {item.candidate_id: item.success for item in scenario.candidates}
        if any(candidate not in lookup for candidate in ids):
            return None  # Missing observations are never assigned invented probabilities.
        none = prod(1 - lookup[candidate] for candidate in ids)
        risk += scenario.weight * (scenario.job_wide_failure + (1 - scenario.job_wide_failure) * none)
    return min(1.0, max(0.0, risk))


def robust_upper_failure(shortlist: Iterable[str], models: tuple[ScenarioModel, ...]) -> float | None:
    ids = tuple(shortlist)
    if not models:
        return None
    values = tuple(model_nonfill_risk(ids, model) for model in models)
    if any(value is None for value in values):
        return None
    return max(value for value in values if value is not None)


def optimistic_feasibility_bound(
    pool: Iterable[str],
    max_n: int,
    models: tuple[ScenarioModel, ...],
) -> float | None:
    """Necessary model feasibility bound: scenario-specific oracle, no competition.

    Values above the allowed failure threshold establish MODEL infeasibility only.
    Values below it do not prove a common shortlist exists across scenarios.
    """
    ids = frozenset(pool)
    if max_n < 0:
        raise ValueError("max_n must be nonnegative")
    if not models:
        return None
    values: list[float] = []
    for model in models:
        if not model.conditional_independence_asserted:
            return None
        risk = 0.0
        for scenario in model.scenarios:
            lookup = {item.candidate_id: item.success for item in scenario.candidates}
            if not ids.issubset(lookup):
                return None
            top = sorted((lookup[candidate] for candidate in ids), reverse=True)[:max_n]
            risk += scenario.weight * (
                scenario.job_wide_failure + (1 - scenario.job_wide_failure) * prod(1 - p for p in top)
            )
        values.append(risk)
    return max(values)


def independent_minimum_n(success: float, target_fill: float = 0.999, hard_limit: int = 10) -> int | None:
    """Illustration under independent equal stipulated p, with explicit cap and rounding."""
    probability(success, "success")
    probability(target_fill, "target_fill")
    if hard_limit < 0:
        raise ValueError("hard_limit must be nonnegative")
    if target_fill == 0:
        return 0
    if success == 0 or hard_limit == 0:
        return None
    if success == 1:
        return 1
    if target_fill == 1:
        return None
    count = ceil(log1p(-target_fill) / log1p(-success) - 1e-12)
    return count if count <= hard_limit else None


@dataclass(frozen=True, slots=True)
class MinimumShortlist:
    candidates: tuple[str, ...]
    risk: float | None
    minimum_proven: bool
    reason: str
    certification_state: str = "CANNOT_CERTIFY"


def minimum_feasible_shortlist(
    pool: Iterable[str],
    models: tuple[ScenarioModel, ...],
    max_n: int,
    budget: PlanningBudget,
    target_fill: float = 0.999,
) -> MinimumShortlist:
    """Exact increasing-cardinality search for small sparse pools, bounded and honest.

    This helper proves minimum cardinality only when all smaller sets were checked.
    The market allocator uses a bounded heuristic and makes no global optimality claim.
    """
    probability(target_fill, "target_fill")
    ids = tuple(sorted(set(pool)))
    if max_n < 0:
        raise ValueError("max_n must be nonnegative")
    bound = optimistic_feasibility_bound(ids, max_n, models)
    if bound is None:
        return MinimumShortlist((), None, False, "MISSING_OR_UNSUPPORTED_MODEL")
    if bound > 1 - target_fill + 1e-12:
        return MinimumShortlist((), bound, False, "MODEL_INFEASIBLE_EVEN_WITH_ORACLE")
    try:
        for size in range(min(max_n, len(ids)) + 1):
            best: tuple[float, tuple[str, ...]] | None = None
            for shortlist in combinations(ids, size):
                budget.tick()
                risk = robust_upper_failure(shortlist, models)
                if risk is not None and risk <= 1 - target_fill + 1e-12:
                    value = (risk, shortlist)
                    if best is None or value < best:
                        best = value
            if best is not None:
                return MinimumShortlist(best[1], best[0], True, "MODEL_THRESHOLD_ONLY")
    except PlanningBudgetExceeded:
        return MinimumShortlist((), None, False, "BUDGET_EXCEEDED")
    return MinimumShortlist((), bound, True, "NO_COMMON_FEASIBLE_SHORTLIST_UNDER_MODELS")
