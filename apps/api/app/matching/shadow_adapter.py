"""Read-only bounded sidecar. The baseline is supplied after its transaction commits."""

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from .baseline import AllocationProposal
from .portfolio import GlobalPlan, MarketSnapshot, allocate_global
from .runtime import PlannerLimits, PlanningBudget, PlanningBudgetExceeded
from .types import stable_hash


@dataclass(frozen=True, slots=True)
class ShadowResult:
    snapshot_hash: str
    baseline_proposal_hash: str
    baseline_proposals: tuple[AllocationProposal, ...]
    advanced_plan: GlobalPlan | None
    reasons: tuple[str, ...]
    elapsed_seconds: float
    side_effect_count: int = 0


def run_shadow(
    snapshot: MarketSnapshot,
    baseline_proposals: tuple[AllocationProposal, ...],
    enabled: bool = False,
    limits: PlannerLimits = PlannerLimits(),
    clock: Callable[[], float] = monotonic,
) -> ShadowResult:
    """Never acquires a repository, transaction, notifier or execution capability.

    Any invalid model, budget failure or planner exception preserves exactly the
    original baseline output. Errors are minimized to class names to avoid PII logs.
    """
    started = clock()
    state_hash = snapshot.digest
    baseline = tuple(baseline_proposals)
    baseline_hash = stable_hash(baseline)
    plan = None
    reasons: tuple[str, ...] = ("SHADOW_DISABLED",)
    if enabled:
        try:
            budget = PlanningBudget(limits, clock)
            plan = allocate_global(snapshot, limits, budget)
            if snapshot.digest != state_hash:
                raise RuntimeError("immutable snapshot changed")
            reasons = ("RESEARCH_ONLY_NO_EXECUTION",)
        except PlanningBudgetExceeded:
            reasons = ("BUDGET_EXCEEDED_BASELINE_PRESERVED",)
        except Exception as error:
            reasons = ("PLANNER_FAILED_BASELINE_PRESERVED", type(error).__name__)
    return ShadowResult(state_hash, baseline_hash, baseline, plan, reasons, max(0, clock() - started))
