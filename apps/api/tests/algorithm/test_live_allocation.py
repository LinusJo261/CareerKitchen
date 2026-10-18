"""Independent finite-market oracles for attention allocation, not hiring accuracy."""

from collections import Counter
from itertools import combinations
from random import Random

import pytest
from app.matching.assignment import maximum_weight_assignment
from app.matching.live import AttentionCapacity, LiveProposal, allocate_live
from app.matching.runtime import PlannerLimits, PlanningBudget
from app.matching.types import Side


def budget(operations=2_000_000, edges=20_000):
    return PlanningBudget(
        PlannerLimits(max_seconds=30, max_operations=operations, max_edges=edges), lambda: 0
    )


def feasible(proposals, candidates, vacancies):
    usage = Counter()
    for proposal in proposals:
        usage[(proposal.candidate_id, proposal.first_mover, "candidate")] += 1
        usage[(proposal.vacancy_id, proposal.first_mover, "vacancy")] += 1
    return all(
        count
        <= (
            (
                candidates[key].active_remaining
                if side == Side.CANDIDATE
                else candidates[key].waiting_remaining
            )
            if endpoint == "candidate"
            else (
                vacancies[key].waiting_remaining
                if side == Side.CANDIDATE
                else vacancies[key].active_remaining
            )
        )
        for (key, side, endpoint), count in usage.items()
    )


def test_live_flow_rearranges_greedy_choice_to_improve_total_utility():
    proposals = (
        LiveProposal("a", "x", Side.CANDIDATE, 1),
        LiveProposal("a", "y", Side.CANDIDATE, 0.9),
        LiveProposal("b", "x", Side.CANDIDATE, 0.9),
    )
    result = allocate_live(
        proposals,
        {key: AttentionCapacity(1, 10) for key in ("a", "b")},
        {key: AttentionCapacity(10, 1) for key in ("x", "y")},
        budget=budget(),
    )
    assert result.baseline_objective == 1
    assert result.objective == 1.8
    assert {proposal.pair for proposal in result.proposals} == {("a", "y"), ("b", "x")}
    assert result.search_complete


def test_live_flow_equals_independent_exhaustive_subset_oracle():
    rng = Random(198047)
    for case in range(360):
        candidates = {f"c{i}": AttentionCapacity(rng.randrange(4), rng.randrange(4)) for i in range(3)}
        vacancies = {f"v{i}": AttentionCapacity(rng.randrange(4), rng.randrange(4)) for i in range(3)}
        proposals = tuple(
            LiveProposal(candidate, vacancy, rng.choice(tuple(Side)), rng.randrange(-10, 101) / 100)
            for candidate in candidates
            for vacancy in vacancies
            if rng.random() < 0.8
        )
        oracle = 0.0
        for size in range(len(proposals) + 1):
            for subset in combinations(proposals, size):
                if feasible(subset, candidates, vacancies):
                    oracle = max(oracle, sum(proposal.net_surplus for proposal in subset))
        result = allocate_live(proposals, candidates, vacancies, budget=budget())
        assert result.objective == pytest.approx(oracle), case
        assert result.objective >= result.baseline_objective, case
        assert feasible(result.proposals, candidates, vacancies), case
        assert len({proposal.pair for proposal in result.proposals}) == len(result.proposals)
        assert all(proposal.net_surplus > 0 for proposal in result.proposals)


def test_live_flow_respects_independent_direction_resources_and_cap_above_one():
    proposals = tuple(
        LiveProposal("c", f"v{i}", Side.CANDIDATE if i < 5 else Side.EMPLOYER, 1) for i in range(10)
    )
    result = allocate_live(
        proposals,
        {"c": AttentionCapacity(3, 2)},
        {f"v{i}": AttentionCapacity(1, 1) for i in range(10)},
        budget=budget(),
    )
    assert Counter(p.first_mover for p in result.proposals) == {Side.CANDIDATE: 3, Side.EMPLOYER: 2}
    assert result.objective == 5


def test_live_flow_never_changes_to_weaker_direction_when_best_direction_has_no_capacity():
    result = allocate_live(
        (LiveProposal("c", "v", Side.CANDIDATE, 1),),
        {"c": AttentionCapacity(0, 10)},
        {"v": AttentionCapacity(10, 10)},
        budget=budget(),
    )
    assert result.proposals == ()


@pytest.mark.parametrize("operations", [0, 1, 10, 30, 60])
def test_live_budget_exhaustion_returns_whole_feasible_baseline(operations):
    proposals = tuple(
        LiveProposal(f"c{i}", f"v{j}", rng_side, 1 - i / 100 - j / 1000)
        for i in range(8)
        for j in range(5)
        for rng_side in (Side.CANDIDATE if i % 2 else Side.EMPLOYER,)
    )
    result = allocate_live(
        proposals,
        {f"c{i}": AttentionCapacity(2, 3) for i in range(8)},
        {f"v{j}": AttentionCapacity(2, 3) for j in range(5)},
        budget=budget(operations),
    )
    assert not result.search_complete
    assert result.fallback_reason == "PLANNING_BUDGET_EXCEEDED"
    assert result.objective == result.baseline_objective
    assert len(result.proposals) > 1
    assert feasible(
        result.proposals,
        {f"c{i}": AttentionCapacity(2, 3) for i in range(8)},
        {f"v{j}": AttentionCapacity(2, 3) for j in range(5)},
    )


def test_live_edge_budget_falls_back_without_releasing_partial_plan():
    proposal = LiveProposal("c", "v", Side.CANDIDATE, 1)
    result = allocate_live(
        (proposal,), {"c": AttentionCapacity(1, 1)}, {"v": AttentionCapacity(1, 1)}, budget=budget(edges=0)
    )
    assert result.proposals == (proposal,)
    assert result.fallback_reason == "PLANNING_BUDGET_EXCEEDED"


def test_live_allocation_is_deterministic_and_unknown_capacity_fails_closed():
    proposals = tuple(LiveProposal(c, v, Side.CANDIDATE, 1) for c in ("b", "a") for v in ("y", "x"))
    candidates = {key: AttentionCapacity(1, 1) for key in ("a", "b")}
    vacancies = {key: AttentionCapacity(1, 1) for key in ("x", "y")}
    assert allocate_live(proposals, candidates, vacancies, budget=budget()) == allocate_live(
        tuple(reversed(proposals)),
        dict(reversed(tuple(candidates.items()))),
        dict(reversed(tuple(vacancies.items()))),
        budget=budget(),
    )
    assert allocate_live(proposals, {}, vacancies, budget=budget()).proposals == ()
    assert allocate_live(proposals, candidates, {}, budget=budget()).proposals == ()


def test_duplicate_pair_with_conflicting_directions_is_rejected():
    with pytest.raises(ValueError, match="exactly one"):
        allocate_live(tuple(LiveProposal("c", "v", side, 1) for side in Side), {}, {})


@pytest.mark.parametrize("invalid", [True, -1, 11, 1.5, float("nan"), float("inf"), "1"])
def test_live_attention_capacity_requires_bounded_integer_counts(invalid):
    with pytest.raises(ValueError):
        AttentionCapacity(invalid, 1)
    with pytest.raises(ValueError):
        AttentionCapacity(1, invalid)


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), "1"])
def test_live_proposal_requires_finite_numeric_utility(invalid):
    with pytest.raises(ValueError):
        LiveProposal("c", "v", Side.CANDIDATE, invalid)


@pytest.mark.parametrize("invalid", [True, -1, 1.5, float("nan"), float("inf")])
def test_generalized_assignment_validates_candidate_capacities(invalid):
    with pytest.raises(ValueError):
        maximum_weight_assignment({("c", "v"): 1}, {"v": 1}, budget(), candidate_capacities={"c": invalid})


def test_generalized_assignment_explicit_candidate_capacity_is_not_research_capacity_one():
    weights = {("c", f"v{i}"): 1 for i in range(5)}
    vacancies = {f"v{i}": 1 for i in range(5)}
    assert len(maximum_weight_assignment(weights, vacancies, budget()).pairs) == 1
    assert (
        len(maximum_weight_assignment(weights, vacancies, budget(), candidate_capacities={"c": 3}).pairs) == 3
    )
    assert maximum_weight_assignment(weights, vacancies, budget(), candidate_capacities={}).pairs == ()


def test_finite_individual_weights_cannot_overflow_total_utility():
    with pytest.raises(ValueError, match="aggregate"):
        maximum_weight_assignment({("a", "x"): 1e308, ("b", "y"): 1e308}, {"x": 1, "y": 1}, budget())
    with pytest.raises(ValueError, match="aggregate"):
        allocate_live(
            (LiveProposal("a", "x", Side.CANDIDATE, 1e308), LiveProposal("b", "y", Side.EMPLOYER, 1e308)),
            {key: AttentionCapacity(1, 1) for key in ("a", "b")},
            {key: AttentionCapacity(1, 1) for key in ("x", "y")},
            budget=budget(),
        )
