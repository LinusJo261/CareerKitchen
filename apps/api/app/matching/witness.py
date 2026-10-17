"""Conditional, cost-aware WITNESS certificates. Nothing here asks or approves."""

from dataclasses import dataclass
from enum import StrEnum
from math import isclose

from .portfolio import GlobalPlan
from .runtime import PlanningBudget
from .types import finite, probability


class PrerequisiteKind(StrEnum):
    EMPLOYER_CLARIFICATION = "EMPLOYER_CLARIFICATION"
    CANDIDATE_CONSENT = "CANDIDATE_CONSENT"
    EVIDENCE_CHECK = "EVIDENCE_CHECK"
    CANDIDATE_TERMS = "CANDIDATE_TERMS"


@dataclass(frozen=True, slots=True)
class RoleScope:
    vacancy_id: str
    role_version: int

    def __post_init__(self) -> None:
        if not self.vacancy_id or self.role_version < 1:
            raise ValueError("exact vacancy ID and role version required")


@dataclass(frozen=True, slots=True)
class Prerequisite:
    step_id: str
    kind: PrerequisiteKind
    scopes: tuple[RoleScope, ...]
    all_of: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    candidate_attention: float = 0.0
    employer_attention: float = 0.0
    delay_cost: float = 0.0
    opportunity_cost: float = 0.0
    irreversible_cost: float = 0.0
    lawful_to_ask: bool = True
    employer_question_opt_in: bool = False
    requirement_class: str | None = None
    candidate_id: str | None = None
    recipient_org_id: str | None = None
    evidence_claim_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("scopes", "all_of", "any_of"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.step_id or not self.scopes:
            raise ValueError("prerequisite ID and exact role scopes required")
        for name in (
            "candidate_attention",
            "employer_attention",
            "delay_cost",
            "opportunity_cost",
            "irreversible_cost",
        ):
            finite(getattr(self, name), name)
        if self.kind == PrerequisiteKind.EMPLOYER_CLARIFICATION and self.requirement_class == "ESSENTIAL":
            raise ValueError("WITNESS cannot relax an essential requirement")
        if self.kind in (PrerequisiteKind.CANDIDATE_CONSENT, PrerequisiteKind.EVIDENCE_CHECK):
            if not all((self.candidate_id, self.recipient_org_id, self.evidence_claim_id)):
                raise ValueError("evidence action requires candidate, recipient and exact claim")

    @property
    def total_cost(self) -> float:
        return (
            self.candidate_attention
            + self.employer_attention
            + self.delay_cost
            + self.opportunity_cost
            + self.irreversible_cost
        )


@dataclass(frozen=True, slots=True)
class DependencyDAG:
    steps: tuple[Prerequisite, ...]
    unlock_all: tuple[str, ...]
    unlock_any: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("steps", "unlock_all", "unlock_any"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        steps = {step.step_id: step for step in self.steps}
        if len(steps) != len(self.steps):
            raise ValueError("duplicate prerequisite ID")
        references = set(self.unlock_all + self.unlock_any)
        for step in self.steps:
            references.update(step.all_of + step.any_of)
        if not references.issubset(steps):
            raise ValueError("unknown prerequisite reference")
        # Also rejects cycles through OR alternatives: conservative, deterministic DAG.
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("prerequisite cycle")
            if key in visited:
                return
            visiting.add(key)
            for parent in steps[key].all_of + steps[key].any_of:
                visit(parent)
            visiting.remove(key)
            visited.add(key)

        for key in steps:
            visit(key)
        # Sensitive checks must explicitly depend on a recipient-scoped consent.
        for step in self.steps:
            if step.kind == PrerequisiteKind.EVIDENCE_CHECK:
                valid_consent = any(
                    steps[parent].kind == PrerequisiteKind.CANDIDATE_CONSENT
                    and steps[parent].candidate_id == step.candidate_id
                    and steps[parent].recipient_org_id == step.recipient_org_id
                    and steps[parent].evidence_claim_id == step.evidence_claim_id
                    and set(step.scopes).issubset(steps[parent].scopes)
                    for parent in step.all_of
                )
                if not valid_consent:
                    raise ValueError("evidence check needs preceding exact recipient consent")

    def can_attempt(self, key: str, succeeded: frozenset[str]) -> bool:
        step = next(item for item in self.steps if item.step_id == key)
        return set(step.all_of).issubset(succeeded) and (
            not step.any_of or bool(set(step.any_of) & succeeded)
        )

    def unlocked(self, succeeded: frozenset[str]) -> bool:
        return set(self.unlock_all).issubset(succeeded) and (
            not self.unlock_any or bool(set(self.unlock_any) & succeeded)
        )


@dataclass(frozen=True, slots=True)
class WitnessOutcome:
    weight: float
    attempted: tuple[str, ...]
    succeeded: frozenset[str]
    future_value: float  # supplied modeled continuation value, never observed hiring

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempted", tuple(self.attempted))
        object.__setattr__(self, "succeeded", frozenset(self.succeeded))
        probability(self.weight, "outcome weight")
        finite(self.future_value, "future_value")


@dataclass(frozen=True, slots=True)
class WitnessCertificate:
    witness_id: str
    state_hash: str
    role_scopes: tuple[RoleScope, ...]
    dag: DependencyDAG
    outcomes: tuple[WitnessOutcome, ...]
    baseline_continuation_value: float
    uncertainty_penalty: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_scopes", tuple(self.role_scopes))
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        finite(self.baseline_continuation_value, "baseline_continuation_value")
        finite(self.uncertainty_penalty, "uncertainty_penalty")
        if not self.outcomes or not isclose(
            sum(item.weight for item in self.outcomes), 1, abs_tol=1e-9, rel_tol=0
        ):
            raise ValueError("complete supplied outcome probabilities must sum to one")
        if any(not set(step.scopes).issubset(self.role_scopes) for step in self.dag.steps):
            raise ValueError("prerequisite outside exact certificate role scopes")
        lookup = {step.step_id: step for step in self.dag.steps}
        for outcome in self.outcomes:
            if len(set(outcome.attempted)) != len(outcome.attempted):
                raise ValueError("action attempted twice")
            if not outcome.succeeded.issubset(outcome.attempted) or not set(outcome.attempted).issubset(
                lookup
            ):
                raise ValueError("invalid supplied outcome actions")
            prior: set[str] = set()
            for key in outcome.attempted:
                if not self.dag.can_attempt(key, frozenset(prior)):
                    raise ValueError("outcome violates prerequisite order or denial")
                if key in outcome.succeeded:
                    prior.add(key)
            if (
                not self.dag.unlocked(outcome.succeeded)
                and outcome.future_value > self.baseline_continuation_value
            ):
                raise ValueError("cannot claim edge lift when complementary prerequisites did not pass")


@dataclass(frozen=True, slots=True)
class InterventionBudget:
    candidate_attention: float
    employer_attention: float
    total_cost: float

    def __post_init__(self) -> None:
        for name in ("candidate_attention", "employer_attention", "total_cost"):
            finite(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class WitnessScore:
    witness_id: str
    expected_advantage: float | None
    conservative_advantage: float | None
    expected_cost: float
    proposal_allowed: bool
    reasons: tuple[str, ...]


def score_witness_bundle(
    certificate: WitnessCertificate,
    budget: InterventionBudget,
    planning: PlanningBudget,
    current_state_hash: str,
    current_roles: tuple[RoleScope, ...],
) -> WitnessScore:
    reasons: list[str] = []
    if certificate.state_hash != current_state_hash or not set(certificate.role_scopes).issubset(
        current_roles
    ):
        reasons.append("STALE_STATE_OR_ROLE_SCOPE")
    steps = {step.step_id: step for step in certificate.dag.steps}
    for step in steps.values():
        if not step.lawful_to_ask:
            reasons.append("NOT_LAWFULLY_ASKABLE")
        if step.kind == PrerequisiteKind.EMPLOYER_CLARIFICATION:
            if not step.employer_question_opt_in or step.requirement_class not in ("PREFERENCE", "AMBIGUOUS"):
                reasons.append("MISSING_SCOPED_EMPLOYER_QUESTION_OPT_IN")
    costs = future = 0.0
    for outcome in certificate.outcomes:
        planning.tick()
        actions = [steps[key] for key in outcome.attempted]
        candidate_cost = sum(step.candidate_attention for step in actions)
        employer_cost = sum(step.employer_attention for step in actions)
        total = sum(step.total_cost for step in actions)
        if (
            candidate_cost > budget.candidate_attention
            or employer_cost > budget.employer_attention
            or total > budget.total_cost
        ):
            reasons.append("PATH_EXCEEDS_INTERVENTION_BUDGET")
        costs += outcome.weight * total
        future += outcome.weight * outcome.future_value
    if reasons:
        return WitnessScore(certificate.witness_id, None, None, costs, False, tuple(sorted(set(reasons))))
    advantage = future - certificate.baseline_continuation_value - costs
    lower = advantage - certificate.uncertainty_penalty
    return WitnessScore(
        certificate.witness_id,
        advantage,
        lower,
        costs,
        lower > 0,
        ("CONDITIONAL_PROPOSAL_ONLY",) if lower > 0 else ("NO_POSITIVE_CONSERVATIVE_ADVANTAGE",),
    )


def detect_bottlenecks(plan: GlobalPlan) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Diagnose sparse-market gaps without inferring anyone's permission or outcome."""
    result = []
    for vacancy in plan.vacancies:
        reasons = []
        if not vacancy.candidates:
            reasons.append("NO_AVAILABLE_PROPOSAL")
        if vacancy.optimistic_failure_bound is not None and vacancy.optimistic_failure_bound > 0.001:
            reasons.append("MODEL_ORACLE_CANNOT_MEET_RESEARCH_TARGET")
        if vacancy.model_nonfill_risk is None:
            reasons.append("MODEL_GAP")
        elif not vacancy.modeled_threshold_pass:
            reasons.append("RESIDUAL_MODELED_FAILURE")
        if reasons:
            result.append((vacancy.vacancy_id, tuple(reasons)))
    return tuple(result)


def compile_witnesses(
    certificates: tuple[WitnessCertificate, ...],
    budget: InterventionBudget,
    planning: PlanningBudget,
    current_state_hash: str,
    roles: tuple[RoleScope, ...],
    limit: int = 10,
) -> tuple[tuple[WitnessCertificate, WitnessScore], ...]:
    """Rank complete caller-enumerated AND/OR bundles; never auto-send a question."""
    if not 0 <= limit <= 100:
        raise ValueError("witness output limit must be in 0..100")
    scores = [
        (item, score_witness_bundle(item, budget, planning, current_state_hash, roles))
        for item in certificates
    ]
    return tuple(
        sorted(scores, key=lambda item: (-(item[1].conservative_advantage or 0), item[0].witness_id))[:limit]
    )
