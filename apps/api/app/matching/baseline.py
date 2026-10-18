"""Pure baseline proposals. The service must revalidate and lock before issuing."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from .attention import MarketPrices
from .retrieval import features_eligible
from .score import DirectionScore, PairEstimate, PairScore, score_v1
from .types import Capacity, EstimateKind, SanitizedPairFeatures, Side, finite


@dataclass(frozen=True, slots=True)
class HeuristicConfig:
    skill_weight: float = 0.4
    experience_weight: float = 0.25
    work_mode_weight: float = 0.25
    evidence_weight: float = 0.1
    version: str = "nonprobabilistic-v1"

    def __post_init__(self) -> None:
        weights = (self.skill_weight, self.experience_weight, self.work_mode_weight, self.evidence_weight)
        for weight in weights:
            finite(weight, "heuristic weight")
        if abs(sum(weights) - 1) > 1e-9:
            raise ValueError("heuristic weights must sum to one")


class HeuristicPairScorer:
    """Transparent relevance routing, explicitly not fabricated funnel probabilities.

    Charge one immediate decision plus receiving-side congestion. Without supplied
    response models we cannot estimate the expected second-side cost or funnel.
    """

    def __init__(self, config: HeuristicConfig = HeuristicConfig()) -> None:
        self.config = config

    def score(self, features: SanitizedPairFeatures, prices: MarketPrices) -> PairScore:
        if not features_eligible(features):
            raise ValueError("ineligible pair")
        config = self.config
        relevance = (
            features.skill_alignment * config.skill_weight
            + features.experience_alignment * config.experience_weight
            + features.work_mode_alignment * config.work_mode_weight
            + features.evidence_alignment * config.evidence_weight
        )
        candidate = DirectionScore(
            Side.CANDIDATE,
            relevance,
            prices.mu_candidate,
            prices.job_congestion,
            relevance - prices.mu_candidate - prices.job_congestion,
        )
        employer = DirectionScore(
            Side.EMPLOYER,
            relevance,
            prices.mu_employer,
            prices.candidate_congestion,
            relevance - prices.mu_employer - prices.candidate_congestion,
        )
        factors = tuple(
            name.upper()
            for name in (
                "skill_alignment",
                "experience_alignment",
                "work_mode_alignment",
                "evidence_alignment",
            )
            if getattr(features, name) > 0
        )
        return PairScore(
            features.candidate_id,
            features.vacancy_id,
            candidate,
            employer,
            EstimateKind.NONPROBABILISTIC,
            config.version,
            features.digest,
            factors,
        )


@dataclass(frozen=True, slots=True)
class AllocationProposal:
    candidate_id: str
    vacancy_id: str
    direction: Side
    surplus: float
    score: PairScore
    state_hash: str


def plan_baseline(
    features: Iterable[SanitizedPairFeatures],
    estimates: Mapping[tuple[str, str], PairEstimate],
    prices: Mapping[str, MarketPrices],
    candidate_capacities: Mapping[str, Capacity],
    vacancy_capacities: Mapping[str, Capacity],
    now: datetime,
    state_hash: str,
    active_pairs: frozenset[tuple[str, str]] = frozenset(),
    heuristic: HeuristicPairScorer | None = None,
) -> tuple[AllocationProposal, ...]:
    """Event-scoped greedy allocation with exact original directional choice.

    If the best direction is full, defer instead of silently substituting a weaker
    direction. Existing cards are inputs and are never revoked. No filler is issued.
    """
    scorer = heuristic or HeuristicPairScorer()
    scores: list[PairScore] = []
    seen: set[tuple[str, str]] = set()
    for item in features:
        if item.pair in seen:
            raise ValueError("duplicate pair")
        seen.add(item.pair)
        if item.pair in active_pairs or not features_eligible(item):
            continue
        if item.as_of > now:
            raise ValueError("future feature snapshot")
        market = prices.get(item.vacancy_id, MarketPrices())
        estimate = estimates.get(item.pair)
        score = score_v1(item, estimate, market, now) if estimate else scorer.score(item, market)
        if score.best.net_surplus > 0:
            scores.append(score)
    candidate_free = {key: value.free for key, value in candidate_capacities.items()}
    vacancy_free = {key: value.free for key, value in vacancy_capacities.items()}
    candidate_waiting_free = {
        key: max(0, value.waiting_maximum - value.waiting_count)
        for key, value in candidate_capacities.items()
    }
    vacancy_waiting_free = {
        key: max(0, value.waiting_maximum - value.waiting_count) for key, value in vacancy_capacities.items()
    }
    result: list[AllocationProposal] = []
    for score in sorted(
        scores, key=lambda item: (-item.best.net_surplus, item.candidate_id, item.vacancy_id)
    ):
        candidate = candidate_capacities.get(score.candidate_id)
        vacancy = vacancy_capacities.get(score.vacancy_id)
        if candidate is None or vacancy is None:
            continue  # Unknown capacity is never assumed free.
        if score.best.side == Side.CANDIDATE:
            if candidate_free[score.candidate_id] <= 0 or vacancy_waiting_free[score.vacancy_id] <= 0:
                continue
            candidate_free[score.candidate_id] -= 1
            vacancy_waiting_free[score.vacancy_id] -= 1
        else:
            if vacancy_free[score.vacancy_id] <= 0 or candidate_waiting_free[score.candidate_id] <= 0:
                continue
            vacancy_free[score.vacancy_id] -= 1
            candidate_waiting_free[score.candidate_id] -= 1
        result.append(
            AllocationProposal(
                score.candidate_id,
                score.vacancy_id,
                score.best.side,
                score.best.net_surplus,
                score,
                state_hash,
            )
        )
    return tuple(result)
