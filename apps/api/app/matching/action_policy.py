"""Adaptive timing and proposal choice; no contacts, allocations or implicit consent."""

from dataclasses import dataclass
from datetime import datetime

from .baseline import AllocationProposal
from .types import Capacity, Side, aware


@dataclass(frozen=True, slots=True)
class ActionChoice:
    action_id: str
    kind: str
    lower_advantage_over_baseline: float
    state_hash: str
    permitted: bool
    pilot_authorized: bool

    def __post_init__(self) -> None:
        if not isinstance(self.lower_advantage_over_baseline, (float, int)):
            raise ValueError("advantage must be numeric")
        from math import isfinite

        if not isfinite(self.lower_advantage_over_baseline):
            raise ValueError("advantage must be finite")
        if self.kind not in ("INTRODUCTION", "QUESTION", "WAIT"):
            raise ValueError("unknown action kind")


def propose_next_action(
    baseline: AllocationProposal | None,
    baseline_valid: bool,
    alternatives: tuple[ActionChoice, ...],
    current_state_hash: str,
    mode: str = "BASELINE",
) -> ActionChoice | AllocationProposal | None:
    """Positive robust advantage is necessary; SHADOW can never replace baseline."""
    if mode not in ("BASELINE", "SHADOW", "PILOT"):
        raise ValueError("invalid controller mode")
    if mode == "PILOT":
        allowed = [
            item
            for item in alternatives
            if item.permitted
            and item.pilot_authorized
            and item.state_hash == current_state_hash
            and item.lower_advantage_over_baseline > 0
        ]
        if allowed:
            return min(allowed, key=lambda item: (-item.lower_advantage_over_baseline, item.action_id))
    return baseline if baseline_valid and baseline and baseline.state_hash == current_state_hash else None


@dataclass(frozen=True, slots=True)
class ReleaseState:
    plan_state_hash: str
    current_state_hash: str
    now: datetime
    deadline: datetime
    vacancy_open: bool
    openings_remaining: int
    distinct_delivered: frozenset[str]
    release_budget_remaining: int
    verified_start: bool = False

    def __post_init__(self) -> None:
        aware(self.now, "now")
        aware(self.deadline, "deadline")
        object.__setattr__(self, "distinct_delivered", frozenset(self.distinct_delivered))
        if min(self.openings_remaining, self.release_budget_remaining) < 0:
            raise ValueError("remaining capacity must be nonnegative")


def next_release(
    ordered_proposals: tuple[AllocationProposal, ...],
    state: ReleaseState,
    candidate_capacities: dict[str, Capacity],
    vacancy_capacity: Capacity,
    currently_eligible_and_consented: frozenset[tuple[str, str]],
) -> AllocationProposal | None:
    """One contingent release after a fresh event snapshot; total delivered may exceed 10.

    The executor records delivery only when employer visibility actually commits.
    A candidate-side card alone must not increase distinct_delivered.
    """
    if (
        state.plan_state_hash != state.current_state_hash
        or not state.vacancy_open
        or state.now >= state.deadline
        or state.openings_remaining == 0
        or state.verified_start
        or state.release_budget_remaining == 0
    ):
        return None
    for proposal in ordered_proposals:
        if (
            proposal.state_hash != state.current_state_hash
            or proposal.surplus <= 0
            or proposal.vacancy_id != vacancy_capacity.scope_id
            or proposal.candidate_id in state.distinct_delivered
            or (proposal.candidate_id, proposal.vacancy_id) not in currently_eligible_and_consented
        ):
            continue
        candidate = candidate_capacities.get(proposal.candidate_id)
        if candidate is None:
            continue
        if (
            proposal.direction == Side.CANDIDATE
            and candidate.free > 0
            and vacancy_capacity.waiting_count < vacancy_capacity.waiting_maximum
        ):
            return proposal
        if (
            proposal.direction == Side.EMPLOYER
            and vacancy_capacity.free > 0
            and candidate.waiting_count < candidate.waiting_maximum
        ):
            return proposal
    return None
