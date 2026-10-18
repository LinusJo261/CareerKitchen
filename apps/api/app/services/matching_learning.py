"""Consented feedback, immutable outcome capture and transactional model promotion."""

from datetime import datetime, timedelta
from math import isfinite

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import pseudonym
from app.core.settings import get_settings
from app.db.models import (
    Candidate,
    DecisionCard,
    Exposure,
    MatchingLearningState,
    MatchingModel,
    MatchingObservation,
    Organization,
    PairCycle,
    User,
    Vacancy,
)
from app.matching.learning import (
    CURRENT_FEATURE_VERSION,
    EXPANDED_FEATURE_NAMES,
    FEATURE_NAMES,
    LearnedModel,
    validate_artifact,
)
from app.services.common import Actor, emit, load, lock_scopes, require_platform, require_version, utcnow

COORDINATION_SCOPE = "matching-learning-registry"
INPUT_NAMES = {
    "employer_skills": "preferred_skill_coverage",
    "candidate_role": "candidate_role_preference_alignment",
    "candidate_work_mode": "candidate_work_mode_preference_alignment",
    "candidate_employment_type": "candidate_employment_type_preference_alignment",
    "skill_precision": "skill_precision",
    "skill_jaccard": "skill_jaccard",
    "text_relevance": "text_relevance",
}
UNKNOWN_INPUTS = (
    "required_skill_coverage",
    "relevant_experience_years",
    "experience_requirement_coverage",
    "employer_role_preference_alignment",
    "candidate_compensation_preference_alignment",
    "candidate_schedule_preference_alignment",
)


def consent_state(entity: Candidate | Organization) -> dict:
    return {
        "enabled": entity.matching_learning_opt_in,
        "version": entity.version,
        "consent_version": entity.matching_learning_consent_version,
    }


def _learning_state(db: Session) -> MatchingLearningState | None:
    return db.scalar(
        select(MatchingLearningState)
        .where(MatchingLearningState.scope == "GLOBAL")
        .execution_options(populate_existing=True)
    )


def consent_source_version(db: Session) -> str:
    state = _learning_state(db)
    return f"career-kitchen-learning-consent-v{state.version if state else 0}"


def active_model_info(db: Session) -> dict:
    row = db.scalar(select(MatchingModel).where(MatchingModel.status == "ACTIVE"))
    return {
        "active": row is not None,
        "model_id": row.model_key if row else None,
        "version": row.version if row else None,
    }


def _retire(db: Session, actor: Actor, reason: str) -> None:
    for row in db.scalars(select(MatchingModel).where(MatchingModel.status == "ACTIVE")):
        row.status, row.version = "RETIRED", row.version + 1
        emit(db, actor, "matching.model_retired", row, payload={"reason_code": reason})


def set_learning_consent(
    db: Session, actor: Actor, entity: Candidate | Organization, enabled: bool, expected_version: int
) -> dict:
    if type(enabled) is not bool:
        raise AppError(422, "INVALID_CONSENT", "Learning consent must be an explicit boolean")
    scope = "candidate" if isinstance(entity, Candidate) else "organization"
    lock_scopes(db, COORDINATION_SCOPE, f"{scope}:{entity.id}")
    entity = load(db, type(entity), entity.id)
    require_version(entity, expected_version)
    if entity.matching_learning_opt_in != enabled:
        entity.matching_learning_opt_in = enabled
        entity.matching_learning_consent_version += 1
        entity.version += 1
        state = _learning_state(db)
        if state is None:
            state = MatchingLearningState(scope="GLOBAL")
            db.add(state)
        else:
            state.version += 1
        emit(
            db,
            actor,
            "matching.learning_consent_changed",
            entity,
            org_id=entity.id if isinstance(entity, Organization) else None,
            payload={"consent_version": entity.matching_learning_consent_version},
        )
        emit(db, actor, "matching.learning_epoch_changed", state)
        if not enabled:
            # Conservative erasure barrier: never keep using a model after a
            # contributor revokes consent. A fresh export/retrain is required.
            _retire(db, actor, "LEARNING_CONSENT_REVOKED")
    return consent_state(entity)


def retire_current_model(db: Session, actor: Actor, expected_active_model_id: str, reason: str) -> dict:
    require_platform(actor, "RESEARCH_ADMIN", "SYSTEM_WORKER")
    lock_scopes(db, COORDINATION_SCOPE)
    if active_model_info(db)["model_id"] != expected_active_model_id:
        raise AppError(409, "MODEL_VERSION_CONFLICT", "The active model changed")
    _retire(db, actor, "OPERATOR_ROLLBACK")
    return active_model_info(db)


def _interval_improves(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(type(number) in {int, float} and isfinite(number) for number in value)
        and value[0] <= value[1] < 0
    )


def _mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return result


def verify_evaluation(artifact: dict, evaluation: dict, incumbent_id: str | None) -> LearnedModel:
    model = validate_artifact(artifact)
    if (
        not isinstance(evaluation, dict)
        or evaluation.get("schema_version") != model.schema_version
        or evaluation.get("model_id") != model.model_id
        or evaluation.get("source") != artifact["source"]
        or evaluation.get("provenance") != artifact["provenance"]
        or evaluation.get("target") != artifact["target"]
        or evaluation.get("fictional_data") is not False
        or evaluation.get("evidence") != {"eligible_for_review": True, "reasons": []}
    ):
        raise ValueError("model report does not match the evaluated artifact")
    provenance = artifact["provenance"]
    if provenance.get("incumbent_model_id") != incumbent_id:
        raise ValueError("challenger was not compared with the active incumbent")
    selection = _mapping(provenance.get("selection"), "model selection")
    if selection.get("training_converged") is not True:
        raise ValueError("model training has not converged")
    if model.schema_version >= 3 and selection.get("training_has_feature_variation") is not True:
        raise ValueError("model training requires varying pre-exposure inputs")
    split = _mapping(provenance.get("split"), "evaluation split")
    counts = _mapping(split.get("counts"), "evaluation counts")
    if set(counts) != {"train", "validation", "test"} or any(
        type(count) is not int or count < 100 for count in counts.values()
    ):
        raise ValueError("insufficient independent training/evaluation observations")
    class_counts = _mapping(split.get("class_counts"), "evaluation class counts")
    if set(class_counts) != set(counts):
        raise ValueError("all three folds must declare explicit positive/negative counts")
    for name in counts:
        classes = _mapping(class_counts[name], f"{name} class counts")
        if (
            set(classes) != {"positives", "negatives"}
            or any(type(count) is not int or count < 20 for count in classes.values())
            or sum(classes.values()) != counts[name]
        ):
            raise ValueError("each evaluation fold requires consistent explicit class counts")
    train_before = _timestamp(split.get("train_before"), "training cutoff")
    validate_before = _timestamp(split.get("validate_before"), "validation cutoff")
    if not train_before < validate_before <= model.exported_at:
        raise ValueError("evaluation cutoffs must precede the model export")
    overlaps = evaluation.get("organization_overlap")
    if (
        not isinstance(overlaps, dict)
        or set(overlaps) != {"train_validation", "train_test", "validation_test"}
        or any(type(n) is not int or n != 0 for n in overlaps.values())
    ):
        raise ValueError("employer identities must not overlap evaluation folds")
    required = {"training_prevalence", "current_compatibility", "fitted_compatibility"}
    if incumbent_id is not None:
        required.add("incumbent")
    outcomes = _mapping(evaluation.get("evaluation"), "evaluation results")
    for name in ("validation", "test"):
        result = _mapping(outcomes.get(name), f"{name} evaluation")
        challenger = _mapping(result.get("challenger"), f"{name} challenger")
        positives, count = challenger.get("positives"), challenger.get("count")
        if (
            type(count) is not int
            or type(positives) is not int
            or count != counts[name]
            or positives != class_counts[name]["positives"]
            or min(positives, count - positives) < 20
        ):
            raise ValueError("insufficient explicit positive/negative evaluation outcomes")
        comparisons = _mapping(result.get("paired_comparisons"), f"{name} paired comparisons")
        if not required.issubset(comparisons):
            raise ValueError("evaluation baselines are incomplete")
        for baseline in required:
            comparison = _mapping(comparisons[baseline], f"{name} baseline comparison")
            clusters = comparison.get("cluster_count")
            scopes = _mapping(comparison.get("by_scope"), "comparison cluster scopes")
            organization_scope = _mapping(scopes.get("organization_id"), "organization clusters")
            org_clusters = organization_scope.get("cluster_count")
            if (
                type(clusters) is not int
                or clusters < 20
                or type(org_clusters) is not int
                or org_clusters < 20
                or not _interval_improves(comparison.get("log_loss_delta_95"))
                or not _interval_improves(comparison.get("brier_delta_95"))
            ):
                raise ValueError("challenger has not demonstrated a robust held-out improvement")
    return model


def promote_model(
    db: Session, actor: Actor, artifact: dict, evaluation: dict, expected_active_model_id: str | None
) -> dict:
    require_platform(actor, "RESEARCH_ADMIN", "SYSTEM_WORKER")
    lock_scopes(db, COORDINATION_SCOPE)
    current = db.scalar(
        select(MatchingModel)
        .where(MatchingModel.status == "ACTIVE")
        .execution_options(populate_existing=True)
    )
    candidate_id = artifact.get("model_id")
    if current and current.model_key == candidate_id and current.artifact == artifact:
        return active_model_info(db)  # Same immutable activation is idempotent.
    current_id = current.model_key if current else None
    if current_id != expected_active_model_id:
        raise AppError(409, "MODEL_VERSION_CONFLICT", "The active model changed during training")
    if db.scalar(select(MatchingModel.id).where(MatchingModel.model_key == candidate_id)):
        raise AppError(
            409,
            "MODEL_REACTIVATION_FORBIDDEN",
            "A retired artifact requires a fresh evaluation and model version",
        )
    try:
        model = verify_evaluation(artifact, evaluation, current_id)
        if artifact["source"]["source_version"] != consent_source_version(db):
            raise ValueError("learning consent changed after the dataset export")
        if model.exported_at > utcnow():
            raise ValueError("model data export is in the future")
        start = _timestamp(artifact["provenance"]["split"]["train_before"], "training cutoff")
        for old in db.scalars(select(MatchingModel)):
            previous = validate_artifact(old.artifact)
            if start < previous.exported_at:
                raise ValueError(
                    "new validation/test cohorts must follow every previously registered model export"
                )
            if (
                old.artifact.get("provenance", {}).get("test_cohort_sha256")
                == artifact["provenance"]["test_cohort_sha256"]
            ):
                raise ValueError("this final test cohort has already been used for promotion")
    except (ValueError, KeyError, TypeError) as error:
        raise AppError(422, "MODEL_NOT_QUALIFIED", str(error)) from error
    _retire(db, actor, "QUALIFIED_REPLACEMENT")
    row = MatchingModel(
        model_key=model.model_id,
        artifact=artifact,
        evaluation=evaluation,
        status="ACTIVE",
        activated_by=actor.user_id,
    )
    db.add(row)
    emit(db, actor, "matching.model_activated", row, payload={"model_id": model.model_id})
    return active_model_info(db)


def current_scoring_model(db: Session) -> tuple[LearnedModel | None, str]:
    row = db.scalar(select(MatchingModel).where(MatchingModel.status == "ACTIVE"))
    if row is None:
        return None, "NO_QUALIFIED_OBSERVED_MODEL"
    try:
        model = validate_artifact(row.artifact)
        now = utcnow()
        if model.exported_at > now:
            return None, "FUTURE_MODEL_DETERMINISTIC_FALLBACK"
        if now - model.exported_at > timedelta(days=get_settings().matching_model_max_age_days):
            return None, "STALE_MODEL_DETERMINISTIC_FALLBACK"
        return model, "OBSERVED_MODEL_ACTIVE"
    except (ValueError, TypeError, KeyError):
        return None, "INVALID_MODEL_DETERMINISTIC_FALLBACK"


def capture_learning_consent(trace: dict, candidate: Candidate, organization: Organization) -> dict:
    learning_snapshot = trace.get("learning_snapshot")
    native_snapshot = trace.get("features")
    has_text = any(
        isinstance(snapshot, dict) and snapshot.get("text_relevance") is not None
        for snapshot in (learning_snapshot, native_snapshot)
    )
    if has_text:
        planned = trace.get("learning_planned_consent")
        versions = {
            "candidate_consent_version": candidate.matching_learning_consent_version,
            "organization_consent_version": organization.matching_learning_consent_version,
        }
        if (
            not isinstance(learning_snapshot, dict)
            or not candidate.matching_learning_opt_in
            or not organization.matching_learning_opt_in
            or not isinstance(planned, dict)
            or set(planned) != set(versions)
            or any(
                type(planned[name]) is not int or planned[name] != version
                for name, version in versions.items()
            )
        ):
            # Issuance holds the registry lock. A revocation or re-opt-in after
            # planning cannot authorize persistence of the old text feature.
            raise AppError(
                409, "LEARNING_CONSENT_CONFLICT", "Learning consent changed; recompute text features"
            )
    if not isinstance(learning_snapshot, dict):
        return trace
    return {
        **trace,
        "learning_consent": {
            "candidate_opt_in": candidate.matching_learning_opt_in,
            "organization_opt_in": organization.matching_learning_opt_in,
            "candidate_consent_version": candidate.matching_learning_consent_version,
            "organization_consent_version": organization.matching_learning_consent_version,
        },
    }


def _consented(trace: dict, candidate: Candidate, org: Organization) -> bool:
    if not isinstance(trace, dict):
        return False
    consent = trace.get("learning_consent", {})
    return (
        isinstance(consent, dict)
        and candidate.matching_learning_opt_in
        and org.matching_learning_opt_in
        and consent.get("candidate_opt_in") is True
        and consent.get("organization_opt_in") is True
        and type(consent.get("candidate_consent_version")) is int
        and type(consent.get("organization_consent_version")) is int
        and consent.get("candidate_consent_version") == candidate.matching_learning_consent_version
        and consent.get("organization_consent_version") == org.matching_learning_consent_version
    )


def record_observation(db: Session, actor: Actor, cycle: PairCycle) -> None:
    # Answer execution already owns the pair locks. Keep the same ordering for
    # explicit callers, then serialize consent checks with model/consent changes.
    lock_scopes(db, f"candidate:{cycle.candidate_id}", f"vacancy:{cycle.vacancy_id}")
    first = db.scalar(
        select(Exposure)
        .where(Exposure.pair_cycle_id == cycle.id)
        .order_by(Exposure.created_at, Exposure.id)
        .limit(1)
    )
    if first is None:
        return
    frozen_consent = (
        first.score_trace.get("learning_consent") if isinstance(first.score_trace, dict) else None
    )
    if (
        not isinstance(frozen_consent, dict)
        or frozen_consent.get("candidate_opt_in") is not True
        or frozen_consent.get("organization_opt_in") is not True
    ):
        # Immutable historical refusal can never become consent through a later
        # opt-in. Ordinary decisions therefore do not serialize on the registry.
        return
    lock_scopes(db, COORDINATION_SCOPE)
    if db.scalar(select(MatchingObservation.id).where(MatchingObservation.pair_cycle_id == cycle.id)):
        return
    candidate, vacancy = load(db, Candidate, cycle.candidate_id), load(db, Vacancy, cycle.vacancy_id)
    org = load(db, Organization, vacancy.org_id)
    if not _consented(first.score_trace, candidate, org):
        return
    values = first.score_trace.get("learning_snapshot", {})
    snapshot = first.score_trace.get("features", {})
    feature_version = first.score_trace.get("learning_feature_version", "reciprocal-structured-v1")
    expected_names = (
        {
            "reciprocal-structured-v1": FEATURE_NAMES,
            CURRENT_FEATURE_VERSION: EXPANDED_FEATURE_NAMES,
        }.get(feature_version)
        if isinstance(feature_version, str)
        else None
    )
    if (
        not isinstance(values, dict)
        or expected_names is None
        or set(values) != set(expected_names)
        or not isinstance(snapshot, dict)
        or type(snapshot.get("candidate_version")) is not int
        or snapshot["candidate_version"] < 1
        or snapshot.get("candidate_id") != cycle.candidate_id
        or snapshot.get("vacancy_id") != cycle.vacancy_id
        or snapshot.get("vacancy_version") != cycle.role_version
        or any(
            value is not None
            and (type(value) not in {int, float} or not isfinite(value) or not 0 <= value <= 1)
            for value in values.values()
        )
    ):
        return
    try:
        as_of = _timestamp(snapshot.get("as_of"), "feature observation")
    except (ValueError, TypeError):
        return
    if as_of > first.created_at:
        return
    lineage = first.score_trace.get("learning_feature_provenance", {"text_relevance_model_id": None})
    if not isinstance(lineage, dict) or set(lineage) != {"text_relevance_model_id"}:
        return
    extractor_id = lineage["text_relevance_model_id"]
    if extractor_id is not None and (
        not isinstance(extractor_id, str)
        or len(extractor_id) != 64
        or any(c not in "0123456789abcdef" for c in extractor_id)
    ):
        return
    if (values.get("text_relevance") is None) != (extractor_id is None):
        return
    if extractor_id is not None and snapshot.get("text_relevance_model_id") != extractor_id:
        return
    cards = list(db.scalars(select(DecisionCard).where(DecisionCard.pair_cycle_id == cycle.id)))
    if not (
        any(card.status == "PASSED" for card in cards)
        or len(cards) == 2
        and all(card.status == "INTERESTED" for card in cards)
    ):
        return
    first_card = min(cards, key=lambda card: (card.created_at, card.id))
    features = {name: None for name in UNKNOWN_INPUTS}
    # Historical snapshots keep newly introduced signals unknown. Never rebuild
    # them from today's edited profiles or today's relevance model.
    features.update({INPUT_NAMES[name]: None for name in EXPANDED_FEATURE_NAMES})
    features.update({INPUT_NAMES[name]: value for name, value in values.items()})
    decisions = {
        side: {"status": "NOT_ISSUED", "issued_at": None, "answered_at": None}
        for side in ("candidate", "employer")
    }
    for card in cards:
        decisions[card.side.lower()] = {
            "status": "PENDING" if card.status == "ACTIVE" else card.status,
            "issued_at": card.created_at.isoformat(),
            "answered_at": card.answered_at.isoformat() if card.answered_at else None,
        }
    row = {
        "cycle_id": cycle.id,
        "candidate_id": candidate.id,
        "vacancy_id": vacancy.id,
        "organization_id": vacancy.org_id,
        "candidate_version": snapshot["candidate_version"],
        "vacancy_version": cycle.role_version,
        "feature_as_of": snapshot["as_of"],
        "first_exposed_at": first_card.created_at.isoformat(),
        "first_mover": cycle.first_mover.lower(),
        "policy_version": (
            first.score_trace.get("allocation", {}).get("allocator_version", cycle.model_version)
            if isinstance(first.score_trace.get("allocation", {}), dict)
            else cycle.model_version
        ),
        "eligibility": "ELIGIBLE",
        "observation_status": "OBSERVABLE",
        "observed_at": utcnow().isoformat(),
        "features": features,
        "feature_provenance": {"text_relevance_model_id": extractor_id},
        "decisions": decisions,
    }
    observation = MatchingObservation(
        pair_cycle_id=cycle.id, candidate_id=candidate.id, vacancy_id=vacancy.id, observation=row
    )
    db.add(observation)
    emit(db, actor, "matching.outcome_observed", observation, org_id=vacancy.org_id)


def export_observations(
    db: Session,
    horizon_days: int = 14,
    max_rows: int = 10000,
    observed_since: datetime | str | None = None,
) -> dict:
    from datetime import UTC

    if (
        type(horizon_days) is not int
        or not 1 <= horizon_days <= 365
        or type(max_rows) is not int
        or not 1 <= max_rows <= 100000
    ):
        raise ValueError("bounded outcome horizon and export row limit required")
    since = None
    if observed_since is not None:
        since = (
            observed_since
            if isinstance(observed_since, datetime)
            else _timestamp(observed_since, "observation window")
        )
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("observation window must include a timezone")
        since = since.astimezone(UTC)
    query = select(MatchingObservation)
    if since is not None:
        query = query.where(MatchingObservation.created_at >= since)
    observations = list(
        db.scalars(query.order_by(MatchingObservation.created_at, MatchingObservation.id).limit(max_rows + 1))
    )
    if len(observations) > max_rows:
        raise ValueError("export exceeds declared maximum; use a reviewed bounded export window")
    rows = []
    skipped = 0
    for observation in observations:
        candidate = db.get(Candidate, observation.candidate_id)
        vacancy = db.get(Vacancy, observation.vacancy_id)
        if candidate is None or vacancy is None:
            skipped += 1
            continue
        org = db.get(Organization, vacancy.org_id)
        first = db.scalar(
            select(Exposure)
            .where(Exposure.pair_cycle_id == observation.pair_cycle_id)
            .order_by(Exposure.created_at, Exposure.id)
            .limit(1)
        )
        user = db.get(User, candidate.user_id)
        if (
            org is None
            or first is None
            or user is None
            or user.status != "ACTIVE"
            or candidate.state != "ACTIVE"
            or not candidate.terms_accepted
            or not candidate.privacy_accepted
            or not candidate.confirmed_at
            or not _consented(first.score_trace, candidate, org)
        ):
            skipped += 1
            continue
        row = dict(observation.observation)
        for name in ("cycle_id", "candidate_id", "vacancy_id", "organization_id"):
            row[name] = pseudonym(f"matching-learning:{name}:{row[name]}")
        rows.append(row)
    exposures = db.scalar(select(func.count()).select_from(PairCycle)) or 0
    stored = db.scalar(select(func.count()).select_from(MatchingObservation)) or 0
    return {
        "rows": rows,
        "consent_source_version": consent_source_version(db),
        "diagnostics": {
            "stored_immutable_resolutions": stored,
            "stored_window_resolutions": len(observations),
            "outside_observation_window": max(0, stored - len(observations)),
            "exported_resolutions": len(rows),
            "excluded_current_consent_or_account": skipped,
            "all_introductions": exposures,
            "without_frozen_resolution": max(0, exposures - stored),
        },
    }
