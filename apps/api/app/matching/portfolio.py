"""Sparse global research allocation with fixed commitments and bounded repair.

Assignments are contingent proposals, never live exclusive reservations. The
capacity-one planning constraint prevents counting the same person as an available
fallback for several vacancies. Only a transactional, consented executor may reserve.
"""

from dataclasses import dataclass, replace
from itertools import combinations

from .runtime import PlannerLimits, PlanningBudget
from .scenario import ScenarioModel, optimistic_feasibility_bound, robust_upper_failure
from .types import boolean, finite, probability, stable_hash


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
        for name in ("eligible", "candidate_opted_in", "exclusive_reservation_authorized"):
            boolean(getattr(self, name), name)

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
        if (
            isinstance(self.role_version, bool)
            or not isinstance(self.role_version, int)
            or self.role_version < 1
            or isinstance(self.shortlist_limit, bool)
            or not isinstance(self.shortlist_limit, int)
            or not 0 <= self.shortlist_limit <= 1000
        ):
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
    solver: str = "BOUNDED_GREEDY_EXCHANGE"
    search_complete: bool = False
    numerical_tolerance: float = 1e-12
    planner_version: str = "sparse-portfolio-v2"


def allocate_heuristic(
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
        snapshot.digest,
        tuple(plans),
        objective(allocation),
        exchanges,
        work.operations,
        expected,
        coverage,
        planner_version="greedy-portfolio-v1",
    )


def allocate_global(
    snapshot: MarketSnapshot,
    limits: PlannerLimits = PlannerLimits(),
    budget: PlanningBudget | None = None,
) -> GlobalPlan:
    """Optimize sparse research proposals while preserving every live commitment.

    Linear routing markets use arbitrary-length residual augmenting paths. Small
    modeled markets search joint assignments, including complementary bundles
    whose individual worst-model gain is zero. Larger modeled markets retain the
    bounded heuristic and try complementary pairs. Numerical/model optima never
    establish empirical reliability or authorize execution.
    """
    from .assignment import NUMERICAL_TOLERANCE, maximum_weight_assignment
    from .runtime import PlanningBudgetExceeded

    work = budget or PlanningBudget(limits)
    if len(snapshot.edges) > limits.max_edges:
        raise PlanningBudgetExceeded("sparse edge budget exceeded")
    work.tick()
    jobs = {}
    allocation: dict[str, set[str]] = {}
    for definition in snapshot.vacancies:
        work.tick()
        jobs[definition.vacancy_id] = definition
        allocation[definition.vacancy_id] = set()
    edges = {}
    for edge in snapshot.edges:
        work.tick()
        if edge.eligible and edge.candidate_opted_in:
            edges[edge.pair] = edge
    fixed_pairs = set()
    fixed_candidates = set()
    roles: dict[str, set[str]] = {}
    for commitment in snapshot.commitments:
        work.tick()
        candidate, job = commitment.candidate_id, commitment.vacancy_id
        fixed_pairs.add((candidate, job))
        fixed_candidates.add(candidate)
        allocation[job].add(candidate)
        roles.setdefault(candidate, set()).add(job)
    fixed = frozenset(fixed_pairs)
    competition_unknown = set()
    for assigned in roles.values():
        work.tick()
        if len(assigned) > 1:
            competition_unknown.update(assigned)
    residual = {}
    available_sets = {}
    for job, definition in jobs.items():
        work.tick()
        residual[job] = max(0, definition.shortlist_limit - len(allocation[job]))
        available_sets[job] = set(allocation[job])
    for candidate, job in edges:
        work.tick()
        if candidate not in fixed_candidates and residual[job] > 0:
            available_sets[job].add(candidate)
    available = {}
    for job, available_candidates in available_sets.items():
        work.tick()
        available[job] = tuple(sorted(available_candidates))
    # Do not let adding a candidate with missing probabilities switch the objective
    # from modeled fill to unrelated routing utility mid-search. An incomplete
    # job model is unknown for this optimization population, throughout the run.
    supported = set()
    for job, definition in jobs.items():
        work.tick()
        if (
            job not in competition_unknown
            and robust_upper_failure(available[job], definition.models) is not None
        ):
            supported.add(job)
    value_cache: dict[tuple[str, frozenset[str]], float] = {}

    def job_value(job: str, members: set[str]) -> float:
        work.tick()
        key = (job, frozenset(members))
        if key not in value_cache:
            risk = robust_upper_failure(sorted(members), jobs[job].models) if job in supported else None
            gross = (
                1 - risk
                if risk is not None
                else sum(
                    edges[(candidate, job)].routing_value
                    for candidate in members
                    if (candidate, job) in edges
                )
            )
            cost = sum(
                edges[(candidate, job)].attention_cost + edges[(candidate, job)].delay_cost
                for candidate in members
                if (candidate, job) in edges and (candidate, job) not in fixed
            )
            value_cache[key] = gross - cost
        return value_cache[key]

    def objective(state: dict[str, set[str]]) -> float:
        return sum(job_value(job, members) for job, members in state.items())

    release_cache: dict[tuple[str, frozenset[str]], frozenset[str]] = {}

    def release_redundant(job: str, members: set[str]) -> frozenset[str]:
        """Apply the established threshold policy before comparing alternatives.

        Optimizing a larger bundle and only then releasing its members can lose
        the bundle's utility and unnecessarily occupy a candidate needed elsewhere.
        Score the final, policy-stable members instead, without changing units.
        """
        work.tick()
        key = (job, frozenset(members))
        if key not in release_cache:
            retained = set(members)
            if job in supported:
                for candidate in sorted(members):
                    work.tick()
                    if (candidate, job) in fixed:
                        continue
                    reduced = retained - {candidate}
                    risk = robust_upper_failure(sorted(reduced), jobs[job].models)
                    if risk is not None and risk <= 1 - jobs[job].target_fill + NUMERICAL_TOLERANCE:
                        retained = reduced
            release_cache[key] = frozenset(retained)
        return release_cache[key]

    movable_edges = {}
    for pair, edge in sorted(edges.items()):
        work.tick()
        if pair[0] not in fixed_candidates and residual[pair[1]] > 0:
            movable_edges[pair] = edge
    exchanges = 0
    search_complete = False
    if not supported:
        weights = {}
        for pair, edge in movable_edges.items():
            work.tick()
            weights[pair] = edge.routing_value - edge.attention_cost - edge.delay_cost
        result = maximum_weight_assignment(weights, residual, work)
        for candidate, job in result.pairs:
            allocation[job].add(candidate)
        exchanges = result.augmentations
        solver = "SPARSE_RESIDUAL_ASSIGNMENT"
        search_complete = True
    else:
        options: dict[str, list[str]] = {}
        for candidate, job in movable_edges:
            work.tick()
            options.setdefault(candidate, []).append(job)
        states = 1
        for choices in options.values():
            work.tick()
            states *= len(choices) + 1
            if states > 20_000:
                break
        if states <= 20_000:
            candidate_order = tuple(sorted(options))
            best = {job: set(members) for job, members in allocation.items()}
            best_value = objective(best)
            raw_best_value = best_value

            def search(index: int) -> None:
                nonlocal best, best_value, raw_best_value
                work.tick()
                if index == len(candidate_order):
                    raw_best_value = max(raw_best_value, objective(allocation))
                    released = {
                        job: set(release_redundant(job, members)) for job, members in allocation.items()
                    }
                    value = objective(released)
                    if value > best_value + NUMERICAL_TOLERANCE:
                        best_value = value
                        best = released
                    return
                candidate = candidate_order[index]
                search(index + 1)
                for job in options[candidate]:
                    if len(allocation[job]) >= jobs[job].shortlist_limit:
                        continue
                    allocation[job].add(candidate)
                    search(index + 1)
                    allocation[job].remove(candidate)

            search(0)
            allocation = best
            solver = "JOINT_ASSIGNMENT_ENUMERATION"
            search_complete = best_value >= raw_best_value - NUMERICAL_TOLERANCE
            if not search_complete:
                solver += "_THRESHOLD_POLICY"
        else:
            normalized = replace(
                snapshot,
                vacancies=tuple(
                    definition if job in supported else replace(definition, models=())
                    for job, definition in jobs.items()
                ),
            )
            incumbent = allocate_heuristic(normalized, limits, work)
            allocation = {plan.vacancy_id: set(plan.candidates) for plan in incumbent.vacancies}
            exchanges = incumbent.exchange_count
            solver = "BOUNDED_EXCHANGE_WITH_COMPLEMENTARY_PAIRS"
            # Worst-case model envelopes are not necessarily submodular. A pair
            # can create value even when neither singleton creates any value.
            for _ in range(min(limits.exchange_steps, 5)):
                work.tick()
                occupied = {candidate for members in allocation.values() for candidate in members}
                best_gain = NUMERICAL_TOLERANCE
                best_replacement: tuple[str, set[str]] | None = None
                for job in sorted(jobs):
                    if len(allocation[job]) + 2 > jobs[job].shortlist_limit:
                        continue
                    candidates = [candidate for candidate in available[job] if candidate not in occupied][:16]
                    before = job_value(job, allocation[job])
                    for pair in combinations(candidates, 2):
                        released = set(release_redundant(job, allocation[job] | set(pair)))
                        gain = job_value(job, released) - before
                        if gain > best_gain:
                            best_gain, best_replacement = gain, (job, released)
                if best_replacement is None:
                    break
                job, retained = best_replacement
                allocation[job] = retained
                exchanges += 1

    # Retain the established research policy of releasing redundant proposals
    # once the stipulated model threshold survives. Fixed human decisions remain.
    pruned = False
    for job in sorted(supported):
        released = set(release_redundant(job, allocation[job]))
        if released != allocation[job]:
            allocation[job] = released
            pruned = True
    if pruned:
        # Post-search threshold pruning is a separate policy; never describe its
        # resulting utility as the unconstrained maximum found by the solver.
        solver += "_THRESHOLD_PRUNED"
        search_complete = False
    plans = []
    modeled_fills = []
    for job, definition in sorted(jobs.items()):
        work.tick()
        remaining = set(allocation[job])
        ordered: list[str] = []
        while remaining:
            work.tick()
            priorities = []
            for candidate in sorted(remaining):
                members = set(ordered) | {candidate}
                priorities.append((-job_value(job, members), candidate))
            candidate = min(priorities)[1]
            ordered.append(candidate)
            remaining.remove(candidate)
        shortlist_members = tuple(ordered)
        risk = robust_upper_failure(shortlist_members, definition.models) if job in supported else None
        bound = (
            optimistic_feasibility_bound(
                available[job],
                max(definition.shortlist_limit, len(allocation[job] & fixed_candidates)),
                definition.models,
            )
            if job in supported
            else None
        )
        reasons = ["RESEARCH_MODEL_ONLY"]
        if risk is None:
            reasons.append("MISSING_OR_UNSUPPORTED_MODEL")
        if job in competition_unknown:
            reasons.append("SHARED_LIVE_COMMITMENT_COMPETITION_UNMODELED")
        if definition.models and job not in supported and job not in competition_unknown:
            reasons.append("INCOMPLETE_MODEL_POPULATION_ROUTING_ONLY")
        if risk is not None:
            modeled_fills.append(1 - risk)
        if bound is not None and bound > 1 - definition.target_fill + NUMERICAL_TOLERANCE:
            reasons.append("MODEL_INFEASIBLE_EVEN_WITH_ORACLE")
        if not shortlist_members:
            reasons.append("NO_POSITIVE_VALUE_AVAILABLE_EDGE")
        if len(shortlist_members) > definition.shortlist_limit:
            reasons.append("FIXED_COMMITMENTS_EXCEED_NEW_LIMIT")
        plans.append(
            VacancyPlan(
                job,
                shortlist_members,
                tuple(sorted(candidate for candidate, role in fixed if role == job)),
                risk,
                bound,
                risk is not None and risk <= 1 - definition.target_fill + NUMERICAL_TOLERANCE,
                tuple(reasons),
            )
        )
    return GlobalPlan(
        snapshot.digest,
        tuple(plans),
        objective(allocation),
        exchanges,
        work.operations,
        sum(modeled_fills) if len(modeled_fills) == len(jobs) else None,
        len(modeled_fills) / len(jobs) if jobs else 0.0,
        solver=solver,
        search_complete=search_complete,
        numerical_tolerance=NUMERICAL_TOLERANCE,
    )
