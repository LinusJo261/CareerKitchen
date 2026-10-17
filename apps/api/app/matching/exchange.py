"""Bounded local exchanges on the supplied sparse graph, never live commitments."""

from collections.abc import Callable

from .runtime import PlanningBudget


def improve_allocation(
    allocation,
    edges,
    jobs,
    fixed,
    fixed_candidates,
    objective: Callable[[dict[str, set[str]]], float],
    budget: PlanningBudget,
    max_steps: int,
):
    """Try moves, swaps and one refill (augmenting paths involving at most two jobs).

    Search is cooperative-budgeted; the shadow adapter catches exhaustion and
    returns the unchanged baseline, rather than exposing a partial research plan.
    """
    exchanges = 0
    for _ in range(max_steps):
        initial = objective(allocation)
        best_value = initial
        best = None
        owner = {
            candidate: job
            for job, members in allocation.items()
            for candidate in members
            if candidate not in fixed_candidates
        }
        occupied = {candidate for members in allocation.values() for candidate in members}
        for candidate, target in sorted(edges):
            budget.tick()
            if candidate in fixed_candidates or candidate in allocation[target]:
                continue
            source = owner.get(candidate)
            # Make target room only by releasing a nonfixed proposal.
            removals = [None] if len(allocation[target]) < jobs[target].shortlist_limit else []
            removals += [member for member in sorted(allocation[target]) if (member, target) not in fixed]
            for displaced in removals:
                trial = {job: set(members) for job, members in allocation.items()}
                if source is not None:
                    trial[source].remove(candidate)
                if displaced is not None:
                    trial[target].remove(displaced)
                trial[target].add(candidate)
                refills = [None]
                if source is not None and len(trial[source]) < jobs[source].shortlist_limit:
                    refills += [
                        other
                        for other, job in sorted(edges)
                        if job == source
                        and other not in fixed_candidates
                        and other != candidate
                        and (other not in occupied or other == displaced)
                    ]
                for refill in refills:
                    budget.tick()
                    variation = {job: set(members) for job, members in trial.items()}
                    if refill is not None:
                        variation[source].add(refill)
                    value = objective(variation)
                    if value > best_value + 1e-12:
                        best_value, best = value, variation
        if best is None:
            break
        allocation = best
        exchanges += 1
    return allocation, exchanges
