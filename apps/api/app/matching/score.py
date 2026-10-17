"""Exact reciprocal legacy formulas for externally supplied, validated predictions."""

from dataclasses import dataclass
from datetime import datetime

from .attention import MarketPrices
from .retrieval import features_eligible
from .types import EstimateKind, SanitizedPairFeatures, Side, aware, probability


@dataclass(frozen=True, slots=True)
class PairEstimate:
    a0: float
    aE: float
    b0: float
    bC: float
    p_interview: float
    p_offer: float
    p_accept: float
    candidate_survival: float
    vacancy_survival: float
    model_version: str
    feature_cutoff: datetime
    epistemic_uncertainty: float | None = None
    target: str = "OFFER_ACCEPTANCE"

    def __post_init__(self) -> None:
        for name in (
            "a0",
            "aE",
            "b0",
            "bC",
            "p_interview",
            "p_offer",
            "p_accept",
            "candidate_survival",
            "vacancy_survival",
        ):
            probability(getattr(self, name), name)
        if self.epistemic_uncertainty is not None:
            probability(self.epistemic_uncertainty, "epistemic_uncertainty")
        aware(self.feature_cutoff, "feature_cutoff")
        if not self.model_version:
            raise ValueError("model version is required")
        if self.target != "OFFER_ACCEPTANCE":
            raise ValueError("legacy funnel target must remain OFFER_ACCEPTANCE, not verified start")


@dataclass(frozen=True, slots=True)
class DirectionScore:
    side: Side
    gross_value: float
    attention_cost: float
    congestion_cost: float
    net_surplus: float


@dataclass(frozen=True, slots=True)
class PairScore:
    candidate_id: str
    vacancy_id: str
    candidate_first: DirectionScore
    employer_first: DirectionScore
    kind: EstimateKind
    model_version: str
    feature_hash: str
    factors: tuple[str, ...]

    @property
    def best(self) -> DirectionScore:
        # Stable candidate-first tie break is recorded and replayable.
        return max((self.candidate_first, self.employer_first), key=lambda value: value.net_surplus)


def score_v1(
    features: SanitizedPairFeatures,
    estimate: PairEstimate,
    prices: MarketPrices,
    now: datetime,
) -> PairScore:
    aware(now, "now")
    if not features_eligible(features):
        raise ValueError("hard eligibility must be true before scoring")
    if estimate.feature_cutoff > now or features.as_of > now:
        raise ValueError("future information is unavailable at scoring time")
    downstream = estimate.p_interview * estimate.p_offer * estimate.p_accept
    survival = estimate.candidate_survival * estimate.vacancy_survival
    gross_ce = estimate.a0 * estimate.bC * downstream * survival
    gross_ec = estimate.b0 * estimate.aE * downstream * survival
    attention_ce = prices.mu_candidate + estimate.a0 * prices.mu_employer
    attention_ec = prices.mu_employer + estimate.b0 * prices.mu_candidate
    congestion_ce = estimate.a0 * prices.job_congestion
    congestion_ec = estimate.b0 * prices.candidate_congestion
    return PairScore(
        features.candidate_id,
        features.vacancy_id,
        DirectionScore(
            Side.CANDIDATE, gross_ce, attention_ce, congestion_ce, gross_ce - attention_ce - congestion_ce
        ),
        DirectionScore(
            Side.EMPLOYER, gross_ec, attention_ec, congestion_ec, gross_ec - attention_ec - congestion_ec
        ),
        EstimateKind.SUPPLIED_MODEL,
        estimate.model_version,
        features.digest,
        ("RECIPROCAL_DIRECTIONAL_MODEL", "LEGACY_ACCEPTANCE_FUNNEL_TARGET"),
    )
