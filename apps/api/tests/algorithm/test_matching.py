"""Deterministic stipulated fixtures: these are mathematical tests, not measured outcomes."""

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from math import sqrt
from pathlib import Path

import pytest
from app.matching.action_policy import ActionChoice, ReleaseState, next_release, propose_next_action
from app.matching.attention import DualPrice, MarketPrices, update_congestion, update_price
from app.matching.baseline import HeuristicPairScorer, plan_baseline
from app.matching.calibration import Observation, probability_metrics, temporal_split
from app.matching.portfolio import (
    Commitment,
    MarketSnapshot,
    ResearchEdge,
    VacancyResearch,
    allocate_global,
    allocate_heuristic,
)
from app.matching.reliability import ClaimContext, can_issue_reliability_claim
from app.matching.retrieval import EligibilitySnapshot, EligibilityState, hard_feasible, sparse_retrieve
from app.matching.runtime import PlannerLimits, PlanningBudget
from app.matching.scenario import (
    CandidateProbability,
    RiskScenario,
    ScenarioModel,
    independent_minimum_n,
    minimum_feasible_shortlist,
    model_nonfill_risk,
    optimistic_feasibility_bound,
    robust_upper_failure,
)
from app.matching.score import PairEstimate, score_v1
from app.matching.shadow_adapter import run_shadow
from app.matching.types import Capacity, EstimateKind, SanitizedPairFeatures, Side
from app.matching.witness import (
    DependencyDAG,
    InterventionBudget,
    Prerequisite,
    PrerequisiteKind,
    RoleScope,
    WitnessCertificate,
    WitnessOutcome,
    compile_witnesses,
    score_witness_bundle,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def features(candidate="c", job="j", **kwargs):
    return SanitizedPairFeatures(
        candidate,
        job,
        "engineering",
        "test-v1",
        NOW,
        skill_alignment=1,
        work_mode_alignment=1,
        experience_alignment=1,
        evidence_alignment=1,
        **kwargs,
    )


def model(probabilities, failure=0.0, version="stipulated-test-v1"):
    return ScenarioModel(
        version,
        (
            RiskScenario(
                "z",
                1,
                tuple(CandidateProbability(key, value) for key, value in probabilities.items()),
                failure,
                "test-assumptions",
            ),
        ),
        True,
    )


def budget(operations=100_000):
    return PlanningBudget(PlannerLimits(max_seconds=30, max_operations=operations), lambda: 0)


def estimate(**kwargs):
    values = dict(
        a0=0.4,
        aE=0.7,
        b0=0.5,
        bC=0.8,
        p_interview=0.6,
        p_offer=0.3,
        p_accept=0.9,
        candidate_survival=0.9,
        vacancy_survival=0.8,
        model_version="supplied-test",
        feature_cutoff=NOW,
    )
    values.update(kwargs)
    return PairEstimate(**values)


def proposals(count=1, candidate_cap=10):
    return plan_baseline(
        tuple(features("c", f"j{index}") for index in range(count)),
        {},
        {},
        {"c": Capacity("c", candidate_cap)},
        {f"j{index}": Capacity(f"j{index}") for index in range(count)},
        NOW,
        "state",
    )


def test_sanitized_features_immutable_and_no_generic_sensitive_dictionary():
    item = features()
    with pytest.raises(FrozenInstanceError):
        item.skill_alignment = 0
    with pytest.raises(TypeError):
        features(payment_amount=1)
    with pytest.raises(ValueError):
        replace(item, skill_alignment=float("nan"))
    assert features().digest == item.digest
    assert "compensation_floor" not in item.__dataclass_fields__


@pytest.mark.parametrize("invalid", [0, 11, -1, True, 1.5])
def test_user_cap_validation(invalid):
    with pytest.raises(ValueError):
        Capacity("c", invalid)


def test_essential_eligibility_and_ambiguity_are_distinct():
    result = hard_feasible(EligibilitySnapshot(essential_requirements_met=False))
    assert result.state == EligibilityState.INELIGIBLE
    assert (
        hard_feasible(EligibilitySnapshot(ambiguous_requirement=True)).state
        == EligibilityState.NEEDS_HUMAN_CLARIFICATION
    )
    assert hard_feasible(EligibilitySnapshot()).eligible
    assert not hard_feasible(EligibilitySnapshot(blocked=True)).eligible


def test_retrieval_bounded_no_duplicate_or_ineligible_edges():
    pool = [features("a"), features("b"), features("c", candidate_active=False)]
    assert [item.candidate_id for item in sparse_retrieve(pool, 1)] == ["a"]
    with pytest.raises(ValueError, match="duplicate"):
        sparse_retrieve([features(), features()], 2)


def test_exact_legacy_reciprocal_value_attention_and_congestion():
    supplied = estimate()
    price = MarketPrices(0.01, 0.02, 0.03, 0.04)
    score = score_v1(features(), supplied, price, NOW)
    downstream = 0.6 * 0.3 * 0.9
    assert score.candidate_first.gross_value == pytest.approx(0.4 * 0.8 * downstream * 0.9 * 0.8)
    assert score.employer_first.gross_value == pytest.approx(0.5 * 0.7 * downstream * 0.9 * 0.8)
    assert score.candidate_first.net_surplus == pytest.approx(
        0.4 * 0.8 * downstream * 0.9 * 0.8 - (0.01 + 0.4 * 0.02) - 0.4 * 0.03
    )
    assert score.employer_first.net_surplus == pytest.approx(
        0.5 * 0.7 * downstream * 0.9 * 0.8 - (0.02 + 0.5 * 0.01) - 0.5 * 0.04
    )
    assert score.kind == EstimateKind.SUPPLIED_MODEL


def test_direction_is_not_permanently_candidate_first():
    score = score_v1(features(), estimate(a0=0.1, aE=0.9, b0=0.9, bC=0.1), MarketPrices(), NOW)
    assert score.best.side == Side.EMPLOYER
    reverse = score_v1(features(), estimate(a0=0.9, aE=0.1, b0=0.1, bC=0.9), MarketPrices(), NOW)
    assert reverse.best.side == Side.CANDIDATE


@pytest.mark.parametrize("value", [-0.1, 1.1, float("inf"), float("nan")])
def test_invalid_model_predictions_rejected(value):
    with pytest.raises(ValueError):
        estimate(a0=value)


def test_future_information_and_noneligible_pair_rejected():
    with pytest.raises(ValueError, match="future"):
        score_v1(features(), estimate(feature_cutoff=NOW + timedelta(seconds=1)), MarketPrices(), NOW)
    with pytest.raises(ValueError, match="eligibility"):
        score_v1(features(essential_requirements_met=False), estimate(), MarketPrices(), NOW)


def test_dual_attention_and_congestion_original_formula_with_clamps():
    value = update_price(DualPrice(0.1, 2), observed_load=6, capacity=4)
    assert value.gradient_sum_sq == 2.25
    assert value.price == pytest.approx(0.1 + 0.5 / sqrt(3.25))
    assert update_congestion(DualPrice(), 100, 0, maximum=0.2).price == 0.2
    assert update_price(DualPrice(0.1), 0, 100).price == 0


def test_no_generated_probabilities_in_cold_start_and_positive_surplus_only():
    score = HeuristicPairScorer().score(features(), MarketPrices())
    assert score.kind == EstimateKind.NONPROBABILISTIC
    assert not hasattr(score, "p_candidate_cold")
    plan = plan_baseline(
        [features()], {}, {"j": MarketPrices(2, 2)}, {"c": Capacity("c")}, {"j": Capacity("j")}, NOW, "state"
    )
    assert plan == ()


def test_baseline_respects_selected_lower_cap_and_retains_current_slots():
    assert len(proposals(20, candidate_cap=3)) == 3
    assert len(proposals(20)) == 10
    plan = plan_baseline([features()], {}, {}, {"c": Capacity("c", 1, 1)}, {"j": Capacity("j")}, NOW, "state")
    assert plan == ()


def test_baseline_respects_vacancy_cap_and_waiting_bounds():
    pool = [features(str(index)) for index in range(20)]
    plan = plan_baseline(
        pool,
        {},
        {"j": MarketPrices(0.5, 0)},
        {str(index): Capacity(str(index)) for index in range(20)},
        {"j": Capacity("j", 2)},
        NOW,
        "state",
    )
    assert len(plan) == 2
    assert all(item.direction == Side.EMPLOYER for item in plan)
    blocked = plan_baseline(
        [features()], {}, {}, {"c": Capacity("c")}, {"j": Capacity("j", waiting_count=10)}, NOW, "state"
    )
    assert blocked == ()


def test_platform_ten_is_concurrent_cap_not_lifetime_delivery_or_forced_quota():
    assert len(proposals(1)) == 1
    assert independent_minimum_n(0.5) == 10
    assert independent_minimum_n(0.9) == 3
    assert independent_minimum_n(0.5, hard_limit=9) is None
    assert independent_minimum_n(0.1, hard_limit=100) == 66


def test_correlation_common_failure_floor_blocks_research_threshold():
    supplied = model({str(index): 1 for index in range(20)}, failure=0.005)
    assert model_nonfill_risk(tuple(str(index) for index in range(20)), supplied) == 0.005
    assert optimistic_feasibility_bound(tuple(str(index) for index in range(20)), 10, (supplied,)) == 0.005
    result = minimum_feasible_shortlist(tuple(str(index) for index in range(20)), (supplied,), 10, budget())
    assert result.reason == "MODEL_INFEASIBLE_EVEN_WITH_ORACLE"
    assert result.certification_state == "CANNOT_CERTIFY"


def test_correlated_scenarios_select_complementary_failure_modes():
    supplied = ScenarioModel(
        "stipulated",
        (
            RiskScenario(
                "shared-a",
                0.5,
                (CandidateProbability("a", 1), CandidateProbability("b", 1), CandidateProbability("c", 0)),
                0,
                "v1",
            ),
            RiskScenario(
                "shared-b",
                0.5,
                (CandidateProbability("a", 0), CandidateProbability("b", 0), CandidateProbability("c", 1)),
                0,
                "v1",
            ),
        ),
        True,
    )
    assert model_nonfill_risk(("a", "b"), supplied) == 0.5
    assert model_nonfill_risk(("a", "c"), supplied) == 0
    result = minimum_feasible_shortlist(("a", "b", "c"), (supplied,), 2, budget())
    assert result.candidates == ("a", "c")
    assert result.minimum_proven


def test_unknown_probability_or_unmodeled_dependence_never_independence_fallback():
    supplied = model({"a": 0.9999})
    assert model_nonfill_risk(("missing",), supplied) is None
    assert robust_upper_failure(("a",), ()) is None
    assert model_nonfill_risk(("a",), replace(supplied, conditional_independence_asserted=False)) is None
    assert robust_upper_failure(("a",), (supplied, model({"a": 0.5}))) == 0.5


def test_invalid_scenario_weights_and_probabilities_rejected():
    with pytest.raises(ValueError):
        CandidateProbability("a", float("nan"))
    with pytest.raises(ValueError, match="sum"):
        ScenarioModel("bad", (RiskScenario("z", 0.8, (), 0, "v1"),), True)


def test_exact_minimum_search_honestly_abstains_on_budget():
    supplied = model({str(index): 0.5 for index in range(10)})
    result = minimum_feasible_shortlist(tuple(str(index) for index in range(10)), (supplied,), 10, budget(1))
    assert result.reason == "BUDGET_EXCEEDED"
    assert not result.minimum_proven


def competition_market():
    return MarketSnapshot(
        "state",
        (
            VacancyResearch("a", 1, 1, (model({"x": 0.9, "y": 0.8}),)),
            VacancyResearch("b", 1, 1, (model({"x": 0.89}),)),
        ),
        (ResearchEdge("x", "a", 0.9), ResearchEdge("y", "a", 0.8), ResearchEdge("x", "b", 0.89)),
    )


def test_competition_counterexample_repaired_by_augmenting_exchange():
    snapshot = competition_market()
    initial = allocate_heuristic(snapshot, PlannerLimits(exchange_steps=0), budget())
    assert initial.expected_fills == pytest.approx(0.9)
    improved = allocate_global(snapshot, budget=budget())
    assert improved.expected_fills == pytest.approx(1.69)
    assert improved.solver == "JOINT_ASSIGNMENT_ENUMERATION"
    assert improved.search_complete
    assert [(item.vacancy_id, item.candidates) for item in improved.vacancies] == [
        ("a", ("y",)),
        ("b", ("x",)),
    ]
    assert len({candidate for item in improved.vacancies for candidate in item.candidates}) == 2


def test_fixed_active_decisions_preserved_during_exchange():
    snapshot = replace(competition_market(), commitments=(Commitment("x", "a", "ACTIVE_DECISION"),))
    result = allocate_global(snapshot, budget=budget())
    assert result.vacancies[0].candidates == ("x",)
    assert result.vacancies[0].fixed_candidates == ("x",)
    assert result.vacancies[1].candidates == ()


def test_candidate_exclusive_reservations_conflict_and_not_implicitly_created():
    snapshot = competition_market()
    with pytest.raises(ValueError, match="exclusive"):
        replace(
            snapshot,
            commitments=(
                Commitment("x", "a", "CONSENTED_EXCLUSIVE"),
                Commitment("x", "b", "CONSENTED_EXCLUSIVE"),
            ),
        )
    result = allocate_global(snapshot, budget=budget())
    assert result.mode == "SHADOW"
    assert not any(edge.exclusive_reservation_authorized for edge in snapshot.edges)
    assert snapshot.commitments == ()


def test_unknown_models_and_empty_jobs_remain_in_coverage_denominator():
    snapshot = MarketSnapshot(
        "s", (VacancyResearch("a", 1, 2), VacancyResearch("b", 1, 2)), (ResearchEdge("x", "a", 0.5),)
    )
    result = allocate_global(snapshot, budget=budget())
    assert len(result.vacancies) == 2
    assert result.expected_fills is None
    assert result.population_coverage == 0
    assert all(item.certification_state == "CANNOT_CERTIFY" for item in result.vacancies)


def test_shared_fixed_soft_commitments_do_not_double_count_available_hires():
    snapshot = replace(
        competition_market(),
        commitments=(Commitment("x", "a", "ACTIVE_DECISION"), Commitment("x", "b", "ACTIVE_DECISION")),
    )
    result = allocate_global(snapshot, budget=budget())
    assert all("x" in item.fixed_candidates for item in result.vacancies)
    assert all(item.model_nonfill_risk is None for item in result.vacancies)
    assert result.expected_fills is None
    assert all("SHARED_LIVE_COMMITMENT_COMPETITION_UNMODELED" in item.reasons for item in result.vacancies)


def test_redundant_candidates_pruned_to_useful_minimum():
    probabilities = {str(index): 0.9 for index in range(10)}
    snapshot = MarketSnapshot(
        "s",
        (VacancyResearch("a", 1, 10, (model(probabilities),)),),
        tuple(ResearchEdge(key, "a", value) for key, value in probabilities.items()),
    )
    result = allocate_global(snapshot, budget=budget())
    assert len(result.vacancies[0].candidates) == 3
    assert result.vacancies[0].modeled_threshold_pass
    assert result.vacancies[0].certification_state == "CANNOT_CERTIFY"


def witness_fixture(denied=False):
    role = RoleScope("a", 1)
    employer = Prerequisite(
        "approval",
        PrerequisiteKind.EMPLOYER_CLARIFICATION,
        (role,),
        employer_attention=0.02,
        employer_question_opt_in=True,
        requirement_class="AMBIGUOUS",
    )
    consent = Prerequisite(
        "consent",
        PrerequisiteKind.CANDIDATE_CONSENT,
        (role,),
        all_of=("approval",),
        candidate_attention=0.02,
        candidate_id="c",
        recipient_org_id="org",
        evidence_claim_id="claim",
    )
    check = Prerequisite(
        "proof",
        PrerequisiteKind.EVIDENCE_CHECK,
        (role,),
        all_of=("consent",),
        candidate_attention=0.02,
        candidate_id="c",
        recipient_org_id="org",
        evidence_claim_id="claim",
    )
    dag = DependencyDAG((employer, consent, check), ("approval", "consent", "proof"))
    outcome = (
        WitnessOutcome(1, ("approval",), frozenset(), 0.2)
        if denied
        else WitnessOutcome(
            1, ("approval", "consent", "proof"), frozenset(("approval", "consent", "proof")), 1
        )
    )
    return WitnessCertificate("w", "state", (role,), dag, (outcome,), 0.2), role


def test_complementary_prerequisites_jointly_scored_and_denial_charged():
    certificate, role = witness_fixture()
    assert not certificate.dag.unlocked(frozenset({"approval"}))
    assert not certificate.dag.unlocked(frozenset({"consent", "proof"}))
    result = score_witness_bundle(certificate, InterventionBudget(1, 1, 1), budget(), "state", (role,))
    assert result.conservative_advantage == pytest.approx(0.74)
    assert result.proposal_allowed
    denied, role = witness_fixture(denied=True)
    result = score_witness_bundle(denied, InterventionBudget(1, 1, 1), budget(), "state", (role,))
    assert result.expected_advantage == pytest.approx(-0.02)
    assert result.expected_cost == 0.02
    assert not result.proposal_allowed


def test_witness_sensitive_evidence_cannot_precede_recipient_consent():
    role = RoleScope("a", 1)
    check = Prerequisite(
        "proof",
        PrerequisiteKind.EVIDENCE_CHECK,
        (role,),
        candidate_id="c",
        recipient_org_id="org",
        evidence_claim_id="claim",
    )
    with pytest.raises(ValueError, match="consent"):
        DependencyDAG((check,), ("proof",))
    with pytest.raises(ValueError, match="essential"):
        Prerequisite("relax", PrerequisiteKind.EMPLOYER_CLARIFICATION, (role,), requirement_class="ESSENTIAL")


def test_witness_or_alternatives_preserve_other_mandatory_prerequisites():
    role = RoleScope("a", 1)
    steps = (
        Prerequisite("terms", PrerequisiteKind.CANDIDATE_TERMS, (role,)),
        Prerequisite("option_a", PrerequisiteKind.CANDIDATE_TERMS, (role,)),
        Prerequisite("option_b", PrerequisiteKind.CANDIDATE_TERMS, (role,)),
    )
    dag = DependencyDAG(steps, ("terms",), ("option_a", "option_b"))
    assert dag.unlocked(frozenset({"terms", "option_b"}))
    assert not dag.unlocked(frozenset({"option_a", "option_b"}))
    assert not dag.unlocked(frozenset({"terms"}))


def test_witness_cycle_denied_dependency_stale_scope_and_cost_budget():
    certificate, role = witness_fixture()
    with pytest.raises(ValueError, match="cycle"):
        DependencyDAG(
            (replace(certificate.dag.steps[0], all_of=("proof",)),) + certificate.dag.steps[1:], ("proof",)
        )
    with pytest.raises(ValueError, match="denial"):
        replace(
            certificate, outcomes=(WitnessOutcome(1, ("approval", "consent"), frozenset({"consent"}), 0.2),)
        )
    result = score_witness_bundle(certificate, InterventionBudget(0.01, 1, 1), budget(), "state", (role,))
    assert "PATH_EXCEEDS_INTERVENTION_BUDGET" in result.reasons
    result = score_witness_bundle(
        certificate, InterventionBudget(1, 1, 1), budget(), "stale", (replace(role, role_version=2),)
    )
    assert "STALE_STATE_OR_ROLE_SCOPE" in result.reasons
    compiled = compile_witnesses((certificate,), InterventionBudget(1, 1, 1), budget(), "state", (role,))
    assert compiled[0][1].proposal_allowed


def test_shadow_parity_disabled_enabled_timeout_and_no_mutation():
    snapshot = competition_market()
    before = snapshot.digest
    baseline = proposals()
    off = run_shadow(snapshot, baseline)
    on = run_shadow(snapshot, baseline, enabled=True)
    timeout = run_shadow(snapshot, baseline, enabled=True, limits=PlannerLimits(max_operations=0))
    assert off.baseline_proposal_hash == on.baseline_proposal_hash == timeout.baseline_proposal_hash
    assert off.baseline_proposals == on.baseline_proposals == timeout.baseline_proposals == baseline
    assert on.advanced_plan is not None
    assert timeout.advanced_plan is None
    assert "BUDGET_EXCEEDED_BASELINE_PRESERVED" in timeout.reasons
    assert off.side_effect_count == on.side_effect_count == timeout.side_effect_count == 0
    assert snapshot.digest == before


def test_wall_clock_budget_uses_safe_fallback():
    ticks = iter((0, 0, 2, 2))
    result = run_shadow(
        competition_market(), proposals(), True, PlannerLimits(max_seconds=1), lambda: next(ticks)
    )
    assert result.advanced_plan is None
    assert result.baseline_proposals == proposals()


def test_adaptive_policy_flags_and_scopes_cannot_bypass_baseline():
    baseline = proposals()[0]
    action = ActionChoice("w", "QUESTION", 1, "state", True, True)
    assert propose_next_action(baseline, True, (action,), "state", "SHADOW") == baseline
    assert propose_next_action(baseline, True, (action,), "state", "PILOT") == action
    assert (
        propose_next_action(baseline, True, (replace(action, pilot_authorized=False),), "state", "PILOT")
        == baseline
    )
    assert propose_next_action(baseline, False, (), "state") is None


def test_adaptive_release_checks_deadline_caps_consent_and_stale_state():
    proposal = proposals()[0]
    state = ReleaseState("state", "state", NOW, NOW + timedelta(days=1), True, 1, frozenset(), 1)
    allowed = frozenset({("c", "j0")})
    assert next_release((proposal,), state, {"c": Capacity("c")}, Capacity("j0"), allowed) == proposal
    assert next_release((proposal,), state, {"c": Capacity("c", 1, 1)}, Capacity("j0"), allowed) is None
    assert next_release((proposal,), state, {"c": Capacity("c")}, Capacity("j0"), frozenset()) is None
    assert (
        next_release(
            (proposal,), replace(state, now=state.deadline), {"c": Capacity("c")}, Capacity("j0"), allowed
        )
        is None
    )
    assert (
        next_release(
            (proposal,),
            replace(state, current_state_hash="changed"),
            {"c": Capacity("c")},
            Capacity("j0"),
            allowed,
        )
        is None
    )


def test_public_reliability_claim_fails_closed_even_with_model_threshold_and_self_asserted_flags():
    result = can_issue_reliability_claim()
    assert result.status == "CANNOT_CERTIFY"
    all_true = ClaimContext(True, True, True, True, True, True, True, True, False, True, 1)
    result = can_issue_reliability_claim(all_true)
    assert result.status == "CANNOT_CERTIFY"
    assert result.public_statement is None
    assert "INDEPENDENT_VALIDATION_AUTHORITY_NOT_CONFIGURED" in result.reasons


def test_temporal_split_and_metrics_do_not_confuse_offer_proxy_with_start():
    record = Observation(NOW, NOW - timedelta(days=1), "PRE_INTRODUCTION", 0.8, True, "OFFER_ACCEPTANCE")
    with pytest.raises(ValueError, match="verified"):
        replace(record, target="VERIFIED_START")
    with pytest.raises(ValueError, match="leakage"):
        replace(record, feature_as_of=NOW + timedelta(seconds=1))
    late = replace(record, observed_at=NOW + timedelta(days=2))
    excluded = replace(record, earliest_stage="INTERVIEW")
    train, calibration, test = temporal_split(
        (record, late, excluded), NOW + timedelta(days=1), NOW + timedelta(days=2)
    )
    assert train == (record,) and calibration == () and test == (late,)
    assert probability_metrics((record,))["brier"] == pytest.approx(0.04)


def test_matching_package_has_no_database_billing_or_network_dependencies():
    directory = Path(__file__).parents[2] / "app" / "matching"
    for source in directory.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                name = node.module or ""
                assert not any(
                    part in name.split(".")
                    for part in ("db", "billing", "protected_audit", "httpx", "requests")
                )
