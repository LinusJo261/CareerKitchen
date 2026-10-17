"""Sparse global research allocation with fixed commitments and bounded repair.

Assignments are contingent proposals, never live exclusive reservations. The
capacity-one planning constraint prevents counting the same person as an available
fallback for several vacancies. Only a transactional, consented executor may reserve.
"""

from dataclasses import dataclass

from .runtime import PlannerLimits, PlanningBudget
from .scenario import ScenarioModel, optimistic_feasibility_bound, robust_upper_failure
from .types import finite, probability, stable_hash


@dataclass(frozen=True, slots=True)
class ResearchEdge:
    candidate_id: str
    vacancy_id: str
    routing_value: float
    attention_cost: float = 0.0
    delay_cost: float = 0.0
    eligible: bool = True
    candidate_opted_in: bool = True
    exclusive_reservation_authorized: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.vacancy_id:
            raise ValueError("edge IDs required")
        for name in ("routing_value", "attention_cost", "delay_cost"):
            finite(getattr(self, name), name)

    @property
    def pair(self) -> tuple[str, str]:
        return self.candidate_id, self.vacancy_id


@dataclass(frozen=True, slots=True)
class VacancyResearch:
    vacancy_id: str
    role_version: int
    shortlist_limit: int
    models: tuple[ScenarioModel, ...] = ()
    target_fill: float = 0.999

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", tuple(self.models))
        probability(self.target_fill, "target_fill")
        if self.role_version < 1 or not 0 <= self.shortlist_limit <= 1000:
            raise ValueError("role version >= 1 and explicit shortlist limit in 0..1000 required")


@dataclass(frozen=True, slots=True)
class Commitment:
    candidate_id: str
    vacancy_id: str
    kind: str  # ACTIVE_DECISION, MUTUAL, or CONSENTED_EXCLUSIVE

    def __post_init__(self) -> None:
        if self.kind not in ("ACTIVE_DECISION", "MUTUAL", "CONSENTED_EXCLUSIVE"):
            raise ValueError("unknown commitment kind")


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    state_version: str
    vacancies: tuple[VacancyResearch, ...]
    edges: tuple[ResearchEdge, ...]
    commitments: tuple[Commitment, ...] = ()

    def __post_init__(self) -> None:
        for name in ("vacancies", "edges", "commitments"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.state_version:
            raise ValueError("state version required")
        jobs = {item.vacancy_id for item in self.vacancies}
        if len(jobs) != len(self.vacancies):
            raise ValueError("duplicate vacancy")
        if len({item.pair for item in self.edges}) != len(self.edges):
            raise ValueError("duplicate sparse edge")
        if any(item.vacancy_id not in jobs for item in self.edges + self.commitments):
            raise ValueError("edge or commitment references unknown vacancy")
        exclusive: set[str] = set()
        for item in self.commitments:
            if item.kind == "CONSENTED_EXCLUSIVE":
                if item.candidate_id in exclusive:
                    raise ValueError("candidate has multiple exclusive commitments")
                exclusive.add(item.candidate_id)
        if len({(item.candidate_id, item.vacancy_id) for item in self.commitments}) != len(self.commitments):
            raise ValueError("duplicate fixed pair")

    @property
    def digest(self) -> str:
        return stable_hash(self)


@dataclass(frozen=True, slots=True)
class VacancyPlan:
    vacancy_id: str
    candidates: tuple[str, ...]
    fixed_candidates: tuple[str, ...]
    model_nonfill_risk: float | None
    optimistic_failure_bound: float | None
    modeled_threshold_pass: bool
    reasons: tuple[str, ...]
    certification_state: str = "CANNOT_CERTIFY"
    mode: str = "RESEARCH_ONLY"


@dataclass(frozen=True, slots=True)
class GlobalPlan:
    snapshot_hash: str
    vacancies: tuple[VacancyPlan, ...]
    objective: float
    exchange_count: int
    operation_count: int
    expected_fills: float | None
    population_coverage: float
    mode: str = "SHADOW"


def allocate_global(
    snapshot: MarketSnapshot,
    limits: PlannerLimits = PlannerLimits(),
    budget: PlanningBudget | None = None,
) -> GlobalPlan:
    """Greedy marginal fill followed by single move / 2-job augmenting exchanges.

    This is a bounded heuristic, not a global optimum certificate. Missing scenario
    models route on caller-supplied nonprobabilistic values and report unknown risk.
    Every enrolled vacancy remains present, including empty and infeasible ones.
    """
    from .exchange import improve_allocation

    work = budget or PlanningBudget(limits)
    if len(snapshot.edges) > limits.max_edges:
        from .runtime import PlanningBudgetExceeded

        raise PlanningBudgetExceeded("sparse edge budget exceeded")
    jobs = {item.vacancy_id: item for item in snapshot.vacancies}
    edges = {item.pair: item for item in snapshot.edges if item.eligible and item.candidate_opted_in}
    fixed = frozenset((item.candidate_id, item.vacancy_id) for item in snapshot.commitments)
    allocation: dict[str, set[str]] = {key: set() for key in jobs}
    fixed_candidates = {item.candidate_id for item in snapshot.commitments}
    commitment_roles: dict[str, set[str]] = {}
    for item in snapshot.commitments:
        commitment_roles.setdefault(item.candidate_id, set()).add(item.vacancy_id)
    competition_unknown_jobs = {job for roles in commitment_roles.values() if len(roles) > 1 for job in roles}
    for candidate, job in fixed:
        allocation[job].add(candidate)

    def job_value(job_id: str, members: set[str]) -> float:
        work.tick()
        risk = (
            None
            if job_id in competition_unknown_jobs
            else robust_upper_failure(sorted(members), jobs[job_id].models)
        )
        costs = sum(
            edges[(candidate, job_id)].attention_cost + edges[(candidate, job_id)].delay_cost
            for candidate in members
            if (candidate, job_id) in edges and (candidate, job_id) not in fixed
        )
        if risk is not None:
            return 1 - risk - costs
        return (
            sum(
                edges[(candidate, job_id)].routing_value
                for candidate in members
                if (candidate, job_id) in edges
            )
            - costs
        )

    def objective(state: dict[str, set[str]]) -> float:
        return sum(job_value(job, members) for job, members in state.items())

    used = set(fixed_candidates)
    while True:
        best: tuple[float, str, str] | None = None
        for candidate, job in sorted(edges):
            work.tick()
            if candidate in used or len(allocation[job]) >= jobs[job].shortlist_limit:
                continue
            before = job_value(job, allocation[job])
            gain = job_value(job, allocation[job] | {candidate}) - before
            choice = (gain, job, candidate)
            if gain > 1e-12 and (best is None or gain > best[0] + 1e-12):
                best = choice
        if best is None:
            break
        gain, job, candidate = best
        allocation[job].add(candidate)
        used.add(candidate)

    allocation, exchanges = improve_allocation(
        allocation, edges, jobs, fixed, fixed_candidates, objective, work, limits.exchange_steps
    )
    # Remove redundant contingent members once the model target is retained. Fixed
    # human commitments remain even if they exceed a subsequently reduced limit.
    for job in sorted(jobs):
        for candidate in sorted(allocation[job]):
            work.tick()
            if (candidate, job) in fixed:
                continue
            reduced = allocation[job] - {candidate}
            risk = robust_upper_failure(sorted(reduced), jobs[job].models)
            if risk is not None and risk <= 1 - jobs[job].target_fill + 1e-12:
                allocation[job] = reduced
    plans: list[VacancyPlan] = []
    modeled_fills: list[float] = []
    for job, definition in sorted(jobs.items()):
        work.tick()
        # Greedy marginal modeled gain determines contingent release order.
        remaining = set(allocation[job])
        ordered: list[str] = []
        while remaining:
            work.tick()
            priorities: list[tuple[float, str]] = []
            for candidate in remaining:
                candidate_risk = robust_upper_failure(ordered + [candidate], definition.models)
                value = (
                    1 - candidate_risk
                    if candidate_risk is not None
                    else edges.get((candidate, job), ResearchEdge(candidate, job, 0)).routing_value
                )
                priorities.append((-value, candidate))
            next_candidate = min(priorities)[1]
            ordered.append(next_candidate)
            remaining.remove(next_candidate)
        members = tuple(ordered)
        risk = None if job in competition_unknown_jobs else robust_upper_failure(members, definition.models)
        bound = optimistic_feasibility_bound(
            (candidate for candidate, role in edges if role == job),
            definition.shortlist_limit,
            definition.models,
        )
        reasons = ["RESEARCH_MODEL_ONLY"]
        if risk is None:
            reasons.append("MISSING_OR_UNSUPPORTED_MODEL")
        if job in competition_unknown_jobs:
            reasons.append("SHARED_LIVE_COMMITMENT_COMPETITION_UNMODELED")
        if risk is not None:
            modeled_fills.append(1 - risk)
        if bound is not None and bound > 1 - definition.target_fill + 1e-12:
            reasons.append("MODEL_INFEASIBLE_EVEN_WITH_ORACLE")
        if not members:
            reasons.append("NO_POSITIVE_VALUE_AVAILABLE_EDGE")
        if len(members) > definition.shortlist_limit:
            reasons.append("FIXED_COMMITMENTS_EXCEED_NEW_LIMIT")
        plans.append(
            VacancyPlan(
                job,
                members,
                tuple(sorted(candidate for candidate, role in fixed if role == job)),
                risk,
                bound,
                risk is not None and risk <= 1 - definition.target_fill + 1e-12,
                tuple(reasons),
            )
        )
    expected = sum(modeled_fills) if len(modeled_fills) == len(jobs) else None
    coverage = len(modeled_fills) / len(jobs) if jobs else 0.0
    return GlobalPlan(
        snapshot.digest, tuple(plans), objective(allocation), exchanges, work.operations, expected, coverage
    )
