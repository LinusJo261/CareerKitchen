"""A batch must not overpromise the receiving side's remaining attention."""

from datetime import UTC, datetime

import pytest
from app.matching.attention import MarketPrices
from app.matching.baseline import plan_baseline
from app.matching.runtime import PlannerLimits
from app.matching.scenario import RiskScenario, ScenarioModel
from app.matching.types import Capacity, SanitizedPairFeatures, Side

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def feature(candidate, vacancy):
    return SanitizedPairFeatures(candidate, vacancy, "engineering", "fixture-v1", NOW, skill_alignment=1)


def test_candidate_first_batch_reserves_receiving_vacancy_queue():
    pool = tuple(feature(f"c{i}", "v") for i in range(5))
    result = plan_baseline(
        pool,
        {},
        {},
        {f"c{i}": Capacity(f"c{i}") for i in range(5)},
        {"v": Capacity("v", waiting_count=9, waiting_maximum=10)},
        NOW,
        "fictional",
    )
    assert len(result) == 1
    assert result[0].direction == Side.CANDIDATE


def test_employer_first_batch_reserves_receiving_candidate_queue():
    pool = tuple(feature("c", f"v{i}") for i in range(5))
    result = plan_baseline(
        pool,
        {},
        {f"v{i}": MarketPrices(mu_candidate=0.1) for i in range(5)},
        {"c": Capacity("c", waiting_count=9, waiting_maximum=10)},
        {f"v{i}": Capacity(f"v{i}") for i in range(5)},
        NOW,
        "fictional",
    )
    assert len(result) == 1
    assert result[0].direction == Side.EMPLOYER


@pytest.mark.parametrize("invalid", [True, 1.5, -1, float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["active_count", "waiting_count", "waiting_maximum"])
def test_capacity_counts_cannot_create_fractional_or_unbounded_space(field, invalid):
    with pytest.raises(ValueError, match="integers"):
        Capacity("c", **{field: invalid})


@pytest.mark.parametrize("invalid", [True, 1.5, -1, float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["max_operations", "max_edges", "exchange_steps"])
def test_planning_count_limits_are_integer_bounds(field, invalid):
    with pytest.raises(ValueError, match="integers"):
        PlannerLimits(**{field: invalid})


@pytest.mark.parametrize("invalid", ["false", "true", 1, None])
def test_conditional_independence_requires_explicit_boolean(invalid):
    with pytest.raises(ValueError, match="boolean"):
        ScenarioModel("fictional-v1", (RiskScenario("s", 1, (), 0, "fixture-v1"),), invalid)
