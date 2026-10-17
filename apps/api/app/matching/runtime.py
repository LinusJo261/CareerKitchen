"""Cooperative wall-clock and operation limits for pure research planning."""

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from .types import finite


class PlanningBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlannerLimits:
    max_seconds: float = 1.0
    max_operations: int = 100_000
    max_edges: int = 20_000
    exchange_steps: int = 20

    def __post_init__(self) -> None:
        finite(self.max_seconds, "max_seconds")
        if min(self.max_operations, self.max_edges, self.exchange_steps) < 0:
            raise ValueError("planner limits must be nonnegative")


class PlanningBudget:
    def __init__(self, limits: PlannerLimits, clock: Callable[[], float] = monotonic) -> None:
        self.limits = limits
        self.clock = clock
        self.deadline = clock() + limits.max_seconds
        self.operations = 0

    def tick(self) -> None:
        self.operations += 1
        if self.operations > self.limits.max_operations or self.clock() >= self.deadline:
            raise PlanningBudgetExceeded("research planner exceeded budget")
