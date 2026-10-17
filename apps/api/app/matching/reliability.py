"""Fail-closed research claim gate. No self-asserted metadata enables public claims."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClaimContext:
    prospective_approved_trial: bool = False
    independently_verified_starts: bool = False
    defensible_joint_calibration: bool = False
    sufficient_comparable_sample: bool = False
    selection_valid_confidence_interval: bool = False
    full_denominator_coverage: bool = False
    in_validated_population: bool = False
    current_policy_matches: bool = False
    active_drift: bool = True
    independent_compliance_approval: bool = False
    lower_fill_bound: float | None = None


@dataclass(frozen=True, slots=True)
class ReliabilityDecision:
    status: str
    reasons: tuple[str, ...]
    public_statement: str | None = None


def can_issue_reliability_claim(
    context: ClaimContext | None = None, target: float = 0.999
) -> ReliabilityDecision:
    """Deployment deliberately ships without an external validation authority.

    Even all caller booleans plus a model threshold do not authenticate a prospective
    evidence standard. A later independent validation service is required to replace
    this gate; model-only values cannot produce VALIDATED or a public percentage.
    """
    from .types import probability

    probability(target, "target")
    value = context or ClaimContext()
    reasons: list[str] = []
    gates = {
        "NO_PROSPECTIVE_OUTCOMES": value.prospective_approved_trial,
        "NO_INDEPENDENT_VERIFIED_STARTS": value.independently_verified_starts,
        "UNMODELED_CORRELATION": value.defensible_joint_calibration,
        "INSUFFICIENT_COMPARABLE_EVIDENCE": value.sufficient_comparable_sample,
        "INVALID_OR_UNVERIFIED_SELECTION_CI": value.selection_valid_confidence_interval,
        "INCOMPLETE_DENOMINATOR": value.full_denominator_coverage,
        "POPULATION_MISMATCH": value.in_validated_population,
        "POLICY_MISMATCH": value.current_policy_matches,
        "DISTRIBUTION_SHIFT": not value.active_drift,
        "NOT_INDEPENDENTLY_APPROVED": value.independent_compliance_approval,
    }
    reasons.extend(name for name, passed in gates.items() if not passed)
    if value.lower_fill_bound is None:
        reasons.append("NO_VALIDATED_LOWER_BOUND")
    else:
        probability(value.lower_fill_bound, "lower_fill_bound")
        if value.lower_fill_bound < target:
            reasons.append("THRESHOLD_NOT_MET")
    reasons.append("INDEPENDENT_VALIDATION_AUTHORITY_NOT_CONFIGURED")
    return ReliabilityDecision("CANNOT_CERTIFY", tuple(reasons))
