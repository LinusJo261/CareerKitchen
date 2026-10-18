"""Bounded deterministic routing over eligible, scored introduction proposals.

Only the clearing service can execute a plan. Each pair retains its scoring
policy's chosen first mover. Candidate-first and employer-first work therefore
use disjoint active/receiving resources and can be optimized independently.
These objectives are compatibility utility, never hiring probabilities.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from .assignment import NUMERICAL_TOLERANCE, maximum_weight_assignment
from .runtime import PlannerLimits, PlanningBudget, PlanningBudgetExceeded
from .types import Side

ALLOCATOR_VERSION = "directional-attention-flow-v1"


@dataclass(frozen=True, slots=True)
class AttentionCapacity:
    active_remaining: int
    waiting_remaining: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or not 0 <= value <= 10
            for value in (self.active_remaining, self.waiting_remaining)
        ):
            raise ValueError("remaining attention capacities must be integers in 0..10")


@dataclass(frozen=True, slots=True)
class LiveProposal:
    candidate_id: str
    vacancy_id: str
    first_mover: Side
    net_surplus: float

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.vacancy_id:
            raise ValueError("candidate and vacancy IDs are required")
        if self.first_mover not in (Side.CANDIDATE, Side.EMPLOYER):
            raise ValueError("invalid first mover")
        if (
            isinstance(self.net_surplus, bool)
            or not isinstance(self.net_surplus, (int, float))
            or not isfinite(self.net_surplus)
        ):
            raise ValueError("net surplus must be a finite number")

    @property
    def pair(self) -> tuple[str, str]:
        return self.candidate_id, self.vacancy_id


@dataclass(frozen=True, slots=True)
class LiveAllocation:
    proposals: tuple[LiveProposal, ...]
    objective: float
    baseline_objective: float
    search_complete: bool
    solver: str
    fallback_reason: str | None = None
    allocator_version: str = ALLOCATOR_VERSION


def _order(proposal: LiveProposal) -> tuple[float, str, str]:
    return -proposal.net_surplus, proposal.candidate_id, proposal.vacancy_id


def _resources(
    candidates: Mapping[str, AttentionCapacity],
    vacancies: Mapping[str, AttentionCapacity],
    side: Side,
) -> tuple[dict[str, int], dict[str, int]]:
    return (
        {
            key: value.active_remaining if side == Side.CANDIDATE else value.waiting_remaining
            for key, value in candidates.items()
        },
        {
            key: value.waiting_remaining if side == Side.CANDIDATE else value.active_remaining
            for key, value in vacancies.items()
        },
    )


def allocate_live(
    proposals: Sequence[LiveProposal],
    candidates: Mapping[str, AttentionCapacity],
    vacancies: Mapping[str, AttentionCapacity],
    *,
    budget: PlanningBudget | None = None,
) -> LiveAllocation:
    """Optimize supplied pairs, falling back to a complete feasible greedy plan.

    Missing capacity records mean zero space. A pair cannot appear twice even if
    its directions differ. Existing commitments are represented by remaining
    capacity; this planner cannot cancel, move or replace any human decision.
    """
    by_pair = {proposal.pair: proposal for proposal in proposals}
    if len(by_pair) != len(proposals):
        raise ValueError("each candidate-vacancy pair must have exactly one chosen direction")
    usable = tuple(sorted((p for p in proposals if p.net_surplus > NUMERICAL_TOLERANCE), key=_order))
    resources = {side: _resources(candidates, vacancies, side) for side in Side}
    remaining = {
        side: (candidate_caps.copy(), vacancy_caps.copy())
        for side, (candidate_caps, vacancy_caps) in resources.items()
    }
    baseline = []
    for proposal in usable:
        candidate_caps, vacancy_caps = remaining[proposal.first_mover]
        if candidate_caps.get(proposal.candidate_id, 0) and vacancy_caps.get(proposal.vacancy_id, 0):
            baseline.append(proposal)
            candidate_caps[proposal.candidate_id] -= 1
            vacancy_caps[proposal.vacancy_id] -= 1
    baseline_value = sum(proposal.net_surplus for proposal in baseline)
    if not isfinite(baseline_value):
        raise ValueError("aggregate live utility must remain finite")
    baseline_tuple = tuple(baseline)

    def fallback(reason: str) -> LiveAllocation:
        return LiveAllocation(
            baseline_tuple, baseline_value, baseline_value, False, "COMPLETE_GREEDY_FALLBACK", reason
        )

    work = budget if budget is not None else PlanningBudget(PlannerLimits())
    selected: list[LiveProposal] = []
    try:
        work.tick()
        if len(usable) > work.limits.max_edges:
            raise PlanningBudgetExceeded("live proposal edge budget exceeded")
        for side in Side:
            weights = {}
            for proposal in usable:
                work.tick()
                if proposal.first_mover == side:
                    weights[proposal.pair] = proposal.net_surplus
            candidate_caps, vacancy_caps = resources[side]
            result = maximum_weight_assignment(
                weights, vacancy_caps, work, candidate_capacities=candidate_caps
            )
            selected.extend(by_pair[pair] for pair in result.pairs)
    except PlanningBudgetExceeded:
        return fallback("PLANNING_BUDGET_EXCEEDED")
    selected.sort(key=_order)
    objective = sum(proposal.net_surplus for proposal in selected)
    if not isfinite(objective):
        raise ValueError("aggregate live utility must remain finite")
    if objective < baseline_value:
        # Numerical tolerances must never cause regression against the complete
        # feasible incumbent, including markets with almost identical scores.
        return fallback("NUMERICAL_BASELINE_GUARD")
    return LiveAllocation(tuple(selected), objective, baseline_value, True, "DIRECTIONAL_SPARSE_FLOW")
