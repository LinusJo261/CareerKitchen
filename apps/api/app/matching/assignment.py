"""Cooperative sparse maximum-weight assignment for immutable scored inputs.

Successive shortest residual paths can reroute any number of existing proposals.
There are no database, execution, consent or prediction capabilities here. Results
optimize supplied floating-point utilities within the declared tolerance only.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from heapq import heappop, heappush
from math import inf, isfinite

from .runtime import PlanningBudget, PlanningBudgetExceeded

NUMERICAL_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class SparseAssignment:
    pairs: tuple[tuple[str, str], ...]
    objective: float
    augmentations: int
    numerical_tolerance: float = NUMERICAL_TOLERANCE


@dataclass(slots=True)
class _Arc:
    target: int
    reverse: int
    capacity: int
    cost: float


def maximum_weight_assignment(
    weights: Mapping[tuple[str, str], float],
    vacancy_capacities: Mapping[str, int],
    budget: PlanningBudget,
    *,
    candidate_capacities: Mapping[str, int] | None = None,
) -> SparseAssignment:
    """Maximize positive sparse utility with explicit endpoint capacities.

    Candidate capacity defaults to one for the research allocation contract.
    An incomplete search raises PlanningBudgetExceeded; callers preserve their
    complete baseline. No partial assignment escapes on exhaustion.
    Zero/negative utility edges are never filler. Stable IDs settle numerical ties.
    """
    budget.tick()
    if len(weights) > budget.limits.max_edges:
        raise PlanningBudgetExceeded("sparse edge budget exceeded")
    for capacity in (*vacancy_capacities.values(), *(candidate_capacities or {}).values()):
        budget.tick()
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
            raise ValueError("assignment capacities must be nonnegative integers")
    usable = {}
    for pair, weight in sorted(weights.items()):
        budget.tick()
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not isfinite(weight):
            raise ValueError("assignment weights must be finite numbers")
        candidate_capacity = 1 if candidate_capacities is None else candidate_capacities.get(pair[0], 0)
        if weight > NUMERICAL_TOLERANCE and vacancy_capacities.get(pair[1], 0) > 0 and candidate_capacity > 0:
            usable[pair] = weight
    if not isfinite(sum(usable.values())):
        raise ValueError("aggregate assignment utility must remain finite")
    candidates = sorted({candidate for candidate, _ in usable})
    vacancies = sorted({vacancy for _, vacancy in usable})
    source, sink = 0, 1
    candidate_nodes = {candidate: index + 2 for index, candidate in enumerate(candidates)}
    vacancy_nodes = {vacancy: index + 2 + len(candidates) for index, vacancy in enumerate(vacancies)}
    graph: list[list[_Arc]] = [[] for _ in range(2 + len(candidates) + len(vacancies))]

    def connect(origin: int, target: int, capacity: int, cost: float) -> _Arc:
        forward = _Arc(target, len(graph[target]), capacity, cost)
        reverse = _Arc(origin, len(graph[origin]), 0, -cost)
        graph[origin].append(forward)
        graph[target].append(reverse)
        return forward

    for candidate in candidates:
        budget.tick()
        capacity = 1 if candidate_capacities is None else candidate_capacities.get(candidate, 0)
        connect(source, candidate_nodes[candidate], capacity, 0)
    for vacancy in vacancies:
        budget.tick()
        connect(vacancy_nodes[vacancy], sink, vacancy_capacities[vacancy], 0)
    pair_arcs = {}
    potentials = [0.0] * len(graph)
    for pair, weight in usable.items():
        budget.tick()
        candidate, vacancy = pair
        pair_arcs[pair] = connect(candidate_nodes[candidate], vacancy_nodes[vacancy], 1, -weight)
        potentials[vacancy_nodes[vacancy]] = min(potentials[vacancy_nodes[vacancy]], -weight)
    potentials[sink] = min(potentials, default=0.0)
    augmentations = 0
    while True:
        budget.tick()
        distances = [inf] * len(graph)
        predecessors: list[tuple[int, int] | None] = [None] * len(graph)
        distances[source] = 0
        queue = [(0.0, source)]
        while queue:
            distance, origin = heappop(queue)
            if distance > distances[origin] + NUMERICAL_TOLERANCE:
                continue
            if origin == sink:
                break
            for index, arc in enumerate(graph[origin]):
                budget.tick()
                if not arc.capacity:
                    continue
                # Feasible shortest-path potentials make reduced costs nonnegative;
                # floating-point cancellation may leave a tiny negative remainder.
                reduced = max(0.0, arc.cost + potentials[origin] - potentials[arc.target])
                value = distance + reduced
                if value < distances[arc.target] - NUMERICAL_TOLERANCE:
                    distances[arc.target] = value
                    predecessors[arc.target] = (origin, index)
                    heappush(queue, (value, arc.target))
        if predecessors[sink] is None:
            break
        path_cost = distances[sink] + potentials[sink] - potentials[source]
        if path_cost >= -NUMERICAL_TOLERANCE:
            break
        for node, distance in enumerate(distances):
            # Capping every update at the settled sink distance preserves feasible
            # reduced costs for unsettled/unreachable nodes after early stopping.
            potentials[node] += min(distance, distances[sink])
        node = sink
        while node != source:
            budget.tick()
            previous = predecessors[node]
            assert previous is not None
            origin, index = previous
            arc = graph[origin][index]
            arc.capacity -= 1
            graph[node][arc.reverse].capacity += 1
            node = origin
        augmentations += 1
    pairs = tuple(pair for pair, arc in pair_arcs.items() if arc.capacity == 0)
    return SparseAssignment(pairs, sum(usable[pair] for pair in pairs), augmentations)
