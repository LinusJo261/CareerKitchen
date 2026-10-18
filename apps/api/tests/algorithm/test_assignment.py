"""Stipulated optimization oracles; these are not observed hiring outcomes."""

from dataclasses import replace
from itertools import product
from random import Random

import pytest
from app.matching.assignment import maximum_weight_assignment
from app.matching.portfolio import (
    Commitment,
    MarketSnapshot,
    ResearchEdge,
    VacancyResearch,
    allocate_global,
    allocate_heuristic,
)
from app.matching.runtime import PlannerLimits, PlanningBudget, PlanningBudgetExceeded
from app.matching.scenario import CandidateProbability, RiskScenario, ScenarioModel


def budget(operations=2_000_000):
    return PlanningBudget(PlannerLimits(max_seconds=30, max_operations=operations), lambda: 0)


def model(probabilities):
    return ScenarioModel(
        "stipulated-test-v1",
        (
            RiskScenario(
                "z",
                1,
                tuple(CandidateProbability(key, value) for key, value in probabilities.items()),
                0,
                "v1",
            ),
        ),
        True,
    )


def test_sparse_b_matching_equals_independent_exhaustive_oracle():
    rng = Random(81173)
    for size in range(1, 5):
        for _ in range(20):
            weights = {
                (str(candidate), str(job)): rng.randrange(-10, 100) / 100
                for candidate in range(size)
                for job in range(size)
                if rng.random() < 0.7
            }
            capacities = {str(job): rng.randrange(3) for job in range(size)}
            oracle = 0.0
            for assignment in product(range(-1, size), repeat=size):
                if any(assignment.count(job) > capacities[str(job)] for job in range(size)):
                    continue
                pairs = [(str(candidate), str(job)) for candidate, job in enumerate(assignment) if job >= 0]
                if any(pair not in weights for pair in pairs):
                    continue
                oracle = max(oracle, sum(weights[pair] for pair in pairs))
            result = maximum_weight_assignment(weights, capacities, budget())
            assert result.objective == pytest.approx(oracle)
            assert len({candidate for candidate, _ in result.pairs}) == len(result.pairs)
            assert all(sum(role == job for _, role in result.pairs) <= cap for job, cap in capacities.items())


def test_three_job_cycle_escapes_two_job_local_optimum():
    weights = {
        ("0", "0"): 0.14,
        ("0", "1"): 0.92,
        ("0", "2"): 0.86,
        ("1", "0"): 0.83,
        ("1", "1"): 0.97,
        ("1", "2"): 0.41,
        ("2", "0"): 0.07,
        ("2", "2"): 0.36,
    }
    snapshot = MarketSnapshot(
        "stipulated",
        tuple(VacancyResearch(str(job), 1, 1) for job in range(3)),
        tuple(ResearchEdge(candidate, job, value) for (candidate, job), value in weights.items()),
    )
    incumbent = allocate_heuristic(snapshot, budget=budget())
    improved = allocate_global(snapshot, budget=budget())
    assert incumbent.objective == pytest.approx(1.90)
    assert improved.objective == pytest.approx(2.11)
    assert improved.solver == "SPARSE_RESIDUAL_ASSIGNMENT"
    assert improved.search_complete
    assert improved.expected_fills is None
    assert improved.mode == "SHADOW"
    assert all(plan.certification_state == "CANNOT_CERTIFY" for plan in improved.vacancies)


def test_robust_complementary_candidates_searched_jointly():
    snapshot = MarketSnapshot(
        "stipulated",
        (VacancyResearch("j", 1, 2, (model({"a": 1, "b": 0}), model({"a": 0, "b": 1}))),),
        (ResearchEdge("a", "j", 1), ResearchEdge("b", "j", 1)),
    )
    assert allocate_heuristic(snapshot, budget=budget()).vacancies[0].candidates == ()
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].candidates == ("a", "b")
    assert improved.expected_fills == 1
    assert improved.search_complete
    assert improved.solver == "JOINT_ASSIGNMENT_ENUMERATION"


def test_fixed_commitments_excluded_from_new_assignments_even_when_over_limit():
    snapshot = MarketSnapshot(
        "stipulated",
        (VacancyResearch("j", 1, 0), VacancyResearch("k", 1, 2)),
        (ResearchEdge("fixed", "k", 100), ResearchEdge("new", "k", 0.5)),
        (Commitment("fixed", "j", "ACTIVE_DECISION"),),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].candidates == ("fixed",)
    assert improved.vacancies[1].candidates == ("new",)
    assert "FIXED_COMMITMENTS_EXCEED_NEW_LIMIT" in improved.vacancies[0].reasons


def test_costs_ineligible_edges_and_nonpositive_filler_excluded():
    snapshot = MarketSnapshot(
        "stipulated",
        (VacancyResearch("j", 1, 10),),
        (
            ResearchEdge("good", "j", 0.8, attention_cost=0.1, delay_cost=0.2),
            ResearchEdge("costly", "j", 0.8, attention_cost=0.9),
            ResearchEdge("zero", "j", 0),
            ResearchEdge("denied", "j", 1, candidate_opted_in=False),
            ResearchEdge("ineligible", "j", 1, eligible=False),
        ),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].candidates == ("good",)
    assert improved.objective == pytest.approx(0.5)


def test_incomplete_model_population_never_changes_objective_units_mid_search():
    snapshot = MarketSnapshot(
        "stipulated",
        (VacancyResearch("j", 1, 1, (model({"known": 0.99}),)),),
        (ResearchEdge("known", "j", 0.1), ResearchEdge("unknown", "j", 0.5)),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].candidates == ("unknown",)
    assert improved.vacancies[0].model_nonfill_risk is None
    assert improved.population_coverage == 0
    assert "INCOMPLETE_MODEL_POPULATION_ROUTING_ONLY" in improved.vacancies[0].reasons


def test_unavailable_fixed_candidate_does_not_disable_other_job_model():
    snapshot = MarketSnapshot(
        "stipulated",
        (VacancyResearch("j", 1, 1, (model({"available": 0.8}),)), VacancyResearch("k", 1, 1)),
        (ResearchEdge("fixed", "j", 1), ResearchEdge("available", "j", 0.1)),
        (Commitment("fixed", "k", "ACTIVE_DECISION"),),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].candidates == ("available",)
    assert improved.vacancies[0].model_nonfill_risk == pytest.approx(0.2)


def test_reduced_cap_fixed_commitment_not_reported_model_infeasible():
    snapshot = MarketSnapshot(
        "stipulated",
        (VacancyResearch("j", 1, 0, (model({"fixed": 1}),)),),
        (),
        (Commitment("fixed", "j", "ACTIVE_DECISION"),),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].modeled_threshold_pass
    assert "MODEL_INFEASIBLE_EVEN_WITH_ORACLE" not in improved.vacancies[0].reasons


def test_large_mixed_population_keeps_incomplete_job_routing_objective():
    candidates = tuple(str(index) for index in range(15))
    snapshot = MarketSnapshot(
        "stipulated",
        (
            VacancyResearch("complete", 1, 1, (model({candidate: 0.9 for candidate in candidates}),)),
            VacancyResearch("incomplete", 1, 1, (model({"0": 0.99}),)),
        ),
        tuple(
            ResearchEdge(candidate, job, 0.4 if job == "complete" else (0.1 if candidate == "0" else 0.5))
            for candidate in candidates
            for job in ("complete", "incomplete")
        ),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.solver == "BOUNDED_EXCHANGE_WITH_COMPLEMENTARY_PAIRS"
    assert improved.objective == pytest.approx(1.4)
    assert improved.vacancies[1].candidates != ("0",)
    assert improved.vacancies[1].model_nonfill_risk is None


def test_large_modeled_population_uses_bounded_complementary_pair_repair():
    probabilities = {str(index): 0 for index in range(15)}
    first = model(dict(probabilities, a=1, b=0))
    second = model(dict(probabilities, a=0, b=1))
    # More than 20,000 assignments disables exact enumeration. Keep the useful
    # complementary pair inside the explicitly bounded candidate neighborhood.
    snapshot = MarketSnapshot(
        "stipulated",
        (VacancyResearch("j", 1, 2, (first, second)),),
        tuple(ResearchEdge(candidate, "j", 1) for candidate in ("a", "b", *probabilities)),
    )
    # Pair candidates are sorted deterministically, so use IDs which sort first.
    translated = {"a": "00a", "b": "00b"}
    snapshot = replace(
        snapshot,
        vacancies=(
            replace(
                snapshot.vacancies[0],
                models=tuple(
                    model(
                        {translated.get(candidate, candidate): value for candidate, value in values.items()}
                    )
                    for values in (dict(probabilities, a=1, b=0), dict(probabilities, a=0, b=1))
                ),
            ),
        ),
        edges=tuple(
            replace(edge, candidate_id=translated.get(edge.candidate_id, edge.candidate_id))
            for edge in snapshot.edges
        ),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].candidates == ("00a", "00b")
    assert improved.solver == "BOUNDED_EXCHANGE_WITH_COMPLEMENTARY_PAIRS"
    assert not improved.search_complete


def test_joint_search_compares_utility_after_threshold_release():
    snapshot = MarketSnapshot(
        "stipulated-threshold-policy",
        (
            VacancyResearch(
                "j",
                1,
                3,
                (model({"c0": 1, "c1": 1, "c2": 0.5}), model({"c0": 1, "c1": 0.25, "c2": 1})),
                target_fill=0.5,
            ),
        ),
        tuple(
            ResearchEdge(candidate, "j", 0.5, attention_cost=cost)
            for candidate, cost in (("c0", 0.2), ("c1", 0.05), ("c2", 0.05))
        ),
    )
    incumbent = allocate_heuristic(snapshot, budget=budget())
    improved = allocate_global(snapshot, budget=budget())
    assert incumbent.objective == pytest.approx(0.8)
    assert improved.objective == pytest.approx(0.8)
    assert improved.vacancies[0].candidates == ("c0",)
    # The unconstrained optimum c1+c2 has utility .9, but release policy turns it
    # into c2 alone, worth .45. Do not claim a raw-utility optimum after policy.
    assert improved.solver == "JOINT_ASSIGNMENT_ENUMERATION_THRESHOLD_POLICY"
    assert not improved.search_complete


def test_zero_target_vacancy_cannot_starve_another_vacancy_before_release():
    snapshot = MarketSnapshot(
        "stipulated-zero-target",
        (
            VacancyResearch("a", 1, 1, (model({"candidate": 1}),), target_fill=0),
            VacancyResearch("b", 1, 1, (model({"candidate": 0.8}),), target_fill=1),
        ),
        (ResearchEdge("candidate", "a", 0.5), ResearchEdge("candidate", "b", 0.5)),
    )
    improved = allocate_global(snapshot, budget=budget())
    assert improved.vacancies[0].candidates == ()
    assert improved.vacancies[1].candidates == ("candidate",)
    assert improved.objective == pytest.approx(0.8)


def test_large_bundle_repair_rejects_gain_destroyed_by_threshold_release():
    probabilities = {f"z{index:02d}": 0 for index in range(15)}
    snapshot = MarketSnapshot(
        "stipulated-bounded-threshold-policy",
        (
            VacancyResearch(
                "j",
                1,
                3,
                (
                    model(dict(probabilities, a=0.8, b=1, c=0.5)),
                    model(dict(probabilities, a=0.8, b=0.25, c=1)),
                ),
                target_fill=0.5,
            ),
        ),
        tuple(
            ResearchEdge(candidate, "j", 0.5, attention_cost=cost)
            for candidate, cost in (("a", 0), ("b", 0.05), ("c", 0.1))
        )
        + tuple(ResearchEdge(candidate, "j", 0.5) for candidate in probabilities),
    )
    incumbent = allocate_heuristic(snapshot, budget=budget())
    improved = allocate_global(snapshot, budget=budget())
    assert incumbent.objective == pytest.approx(0.8)
    assert improved.objective == pytest.approx(0.8)
    assert improved.vacancies[0].candidates == ("a",)
    assert improved.solver == "BOUNDED_EXCHANGE_WITH_COMPLEMENTARY_PAIRS"
    assert not improved.search_complete


def test_varied_model_targets_never_degrade_policy_stable_legacy_incumbent():
    rng = Random(49137)
    for case in range(200):
        candidates = tuple(f"c{index}" for index in range(rng.randrange(2, 6)))
        vacancies = tuple(
            VacancyResearch(
                f"j{job}",
                1,
                rng.randrange(4),
                tuple(
                    model({candidate: rng.choice((0, 0.25, 0.5, 0.75, 1)) for candidate in candidates})
                    for _ in range(rng.randrange(1, 4))
                ),
                target_fill=rng.choice((0, 0.5, 0.8, 0.95, 0.999, 1)),
            )
            for job in range(rng.randrange(1, 4))
        )
        edges = tuple(
            ResearchEdge(candidate, job.vacancy_id, 0.5, attention_cost=rng.randrange(5) / 20)
            for candidate in candidates
            for job in vacancies
            if rng.random() < 0.8
        )
        snapshot = MarketSnapshot(f"stipulated-policy-{case}", vacancies, edges)
        incumbent = allocate_heuristic(snapshot, budget=budget())
        improved = allocate_global(snapshot, budget=budget())
        assert improved.objective >= incumbent.objective - 1e-12, case


def test_sparse_assignment_deterministic_and_cooperatively_bounded():
    weights = {("b", "j"): 1, ("a", "k"): 1, ("a", "j"): 1, ("b", "k"): 1}
    first = maximum_weight_assignment(weights, {"j": 1, "k": 1}, budget())
    second = maximum_weight_assignment(dict(reversed(tuple(weights.items()))), {"k": 1, "j": 1}, budget())
    assert first == second
    with pytest.raises(PlanningBudgetExceeded):
        maximum_weight_assignment(weights, {"j": 1, "k": 1}, budget(1))


def test_snapshot_preparation_obeys_budget_before_scanning_large_population():
    snapshot = MarketSnapshot(
        "stipulated",
        tuple(VacancyResearch(str(index), 1, 1) for index in range(5_000)),
        tuple(ResearchEdge(str(index), str(index), 1) for index in range(5_000)),
    )
    work = budget(1)
    with pytest.raises(PlanningBudgetExceeded):
        allocate_global(snapshot, budget=work)
    assert work.operations == 2
    expired = PlanningBudget(PlannerLimits(max_seconds=0), lambda: 0)
    with pytest.raises(PlanningBudgetExceeded):
        allocate_global(snapshot, budget=expired)
    assert expired.operations == 1


@pytest.mark.parametrize("invalid", [1.5, True, float("nan"), float("inf")])
def test_research_shortlist_and_role_versions_require_strict_integers(invalid):
    with pytest.raises(ValueError):
        VacancyResearch("j", 1, invalid)
    with pytest.raises(ValueError):
        VacancyResearch("j", invalid, 1)
    with pytest.raises(ValueError):
        maximum_weight_assignment({("a", "j"): 1}, {"j": invalid}, budget())


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), "1"])
def test_sparse_solver_rejects_nonfinite_or_nonnumeric_weights(invalid):
    with pytest.raises(ValueError):
        maximum_weight_assignment({("a", "j"): invalid}, {"j": 1}, budget())


@pytest.mark.parametrize("name", ["eligible", "candidate_opted_in", "exclusive_reservation_authorized"])
@pytest.mark.parametrize("invalid", ["false", 1, None])
def test_research_edge_consent_and_eligibility_require_booleans(name, invalid):
    with pytest.raises(ValueError):
        ResearchEdge("a", "j", 1, **{name: invalid})
