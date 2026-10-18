"""Export consented outcomes, train an immutable challenger, optionally promote.

This is a one-shot operator command, suitable for an existing job runner. It does
not create a scheduler or invent labels when observed outcomes are unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from scripts.matching_learning import train
from scripts.mutual_matching_research import timestamp


def _read_active(engine) -> dict | None:
    # Database dependencies are intentionally lazy: offline training needs none.
    from app.db.models import MatchingModel
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        row = db.scalar(select(MatchingModel).where(MatchingModel.status == "ACTIVE"))
        if row is None:
            return None
        return {
            "id": row.id,
            "model_key": row.model_key,
            "artifact": json.loads(json.dumps(row.artifact, allow_nan=False)),
        }


def _export_dataset(engine, output: Path, **options) -> dict:
    from scripts.export_matching_outcomes import export_dataset

    return export_dataset(engine, output, **options)


def _promote(engine, artifact: dict, evaluation: dict, expected_active_model_id: str | None):
    from app.services.matching_learning import promote_model
    from app.workers.runner import worker_actor
    from sqlalchemy.orm import Session

    with Session(engine) as db, db.begin():
        result = promote_model(
            db, worker_actor(db), artifact, evaluation, expected_active_model_id=expected_active_model_id
        )
        db.flush()
        if result.get("active") is not True or result.get("model_id") != artifact["model_id"]:
            raise RuntimeError("Registry did not confirm the requested model activation")
        return result


def _write_status(output: Path, status: dict) -> dict:
    serialized = json.dumps(status, indent=2, allow_nan=False) + "\n"
    # A sibling temporary file makes the final status visible in one operation.
    descriptor, temporary = tempfile.mkstemp(prefix=".refresh-status-", suffix=".json", dir=output)
    path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        path.replace(output / "refresh_status.json")
    finally:
        path.unlink(missing_ok=True)
    return status


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", code) else "STEP_FAILED"


def _insufficient_reason(error: ValueError) -> str | None:
    # Error text is matched locally, never published: it can contain source data.
    message = str(error)
    known = {
        "No observed mutual opt-ins": "NO_LABELED_OUTCOMES",
        "Empty evaluation split": "EMPTY_FORWARD_TIME_EVALUATION_SPLIT",
        "Validation must contain both": "INSUFFICIENT_VALIDATION_CLASSES",
        "Logistic fitting requires": "INSUFFICIENT_TRAINING_CLASSES",
        "No known training features": "NO_KNOWN_PRE_EXPOSURE_FEATURES",
        "Freeze incumbent before validation": "INCUMBENT_REQUIRES_LATER_VALIDATION_COHORT",
    }
    return next((code for prefix, code in known.items() if message.startswith(prefix)), None)


def refresh(
    engine,
    output: Path,
    *,
    environment: str,
    train_before: str,
    validate_before: str,
    seed: int = 42,
    bootstrap_replicates: int = 1000,
    promote: bool = False,
    horizon_days: int = 14,
    max_rows: int = 10000,
    observed_since: str | None = None,
) -> dict:
    if environment not in {"development", "test", "staging", "production"}:
        raise ValueError("Unknown environment")
    if promote and environment != "production":
        raise ValueError("Promotion is permitted only for observed production outcomes")
    if timestamp(train_before) >= timestamp(validate_before):
        raise ValueError("train-before must precede validate-before")
    if type(bootstrap_replicates) is not int or bootstrap_replicates < 50:
        raise ValueError("Use at least 50 bootstrap replicates")
    if type(horizon_days) is not int or not 1 <= horizon_days <= 365:
        raise ValueError("horizon-days must be between 1 and 365")
    if type(max_rows) is not int or not 1 <= max_rows <= 100000:
        raise ValueError("max-rows must be between 1 and 100000")
    normalized_since = timestamp(observed_since).isoformat() if observed_since is not None else None
    output.mkdir(parents=True, exist_ok=False)
    status = {
        "schema_version": 1,
        "status": "NOT_TRAINED",
        "environment": environment,
        "promotion_requested": promote,
        "promoted": False,
        "reason_codes": [],
        "observed_since": normalized_since,
    }
    stage = "read_incumbent"
    try:
        active = _read_active(engine)
        status["incumbent_model_id"] = active["model_key"] if active is not None else None
        incumbent = None
        if active is not None:
            incumbent = output / "incumbent_model.json"
            incumbent.write_text(
                json.dumps(active["artifact"], indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
        stage = "export"
        export_options = {"observed_since": normalized_since} if normalized_since is not None else {}
        exported = _export_dataset(
            engine,
            output / "input",
            environment=environment,
            horizon_days=horizon_days,
            max_rows=max_rows,
            **export_options,
        )
        status["source_kind"] = exported["source_kind"]
        status["exported_rows"] = exported["row_count"]
        if exported["row_count"] == 0:
            status["reason_codes"] = ["NO_EXPORTED_OBSERVATIONS"]
            return _write_status(output, status)
        stage = "train"
        try:
            report = train(
                Path(exported["input_path"]),
                Path(exported["manifest_path"]),
                output / "challenger",
                train_before,
                validate_before,
                seed=seed,
                bootstrap_replicates=bootstrap_replicates,
                allow_fictional=exported["source_kind"] == "fictional_fixture",
                incumbent_path=incumbent,
            )
        except ValueError as error:
            reason = _insufficient_reason(error)
            if reason is None:
                raise
            status.update(status="INSUFFICIENT_DATA", reason_codes=[reason])
            return _write_status(output, status)
        prefix = "fictional_" if report["fictional_data"] else "observed_"
        artifact_path = output / "challenger" / f"{prefix}model.json"
        report_path = output / "challenger" / f"{prefix}report.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        status.update(
            status="TRAINED_REVIEW_REQUIRED"
            if report["evidence"]["eligible_for_review"]
            else "CHALLENGER_REJECTED",
            model_id=artifact["model_id"],
            artifact_path=str(artifact_path),
            report_path=str(report_path),
            reason_codes=report["evidence"]["reasons"],
        )
        if "feature_readiness" in report:
            status["feature_readiness"] = report["feature_readiness"]
        if not promote:
            return _write_status(output, status)
        if (
            exported["source_kind"] != "observed_introduction_outcomes"
            or report["fictional_data"]
            or report["evidence"]["eligible_for_review"] is not True
        ):
            status["status"] = "PROMOTION_DECLINED"
            if not status["reason_codes"]:
                status["reason_codes"] = ["OBSERVED_QUALIFIED_EVIDENCE_REQUIRED"]
            return _write_status(output, status)
        stage = "promote"
        promoted = _promote(engine, artifact, report, active["model_key"] if active is not None else None)
        status.update(status="PROMOTED", promoted=True, active_model_id=promoted["model_id"])
        return _write_status(output, status)
    except Exception as error:
        from app.core.errors import AppError

        if status["promoted"]:
            # Promotion has committed. A local status-file error cannot undo it
            # or be reported as a rejected/rolled-back registry transaction.
            raise RuntimeError("Registry promotion completed but refresh status publication failed") from None
        ambiguous = stage == "promote" and not isinstance(error, AppError)
        status.update(
            status="PROMOTION_STATE_UNKNOWN"
            if ambiguous
            else "PROMOTION_REJECTED"
            if stage == "promote"
            else "FAILED",
            promoted=None if ambiguous else False,
            failed_stage=stage,
            reason_codes=[_error_code(error)],
        )
        return _write_status(output, status)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-before", required=True)
    parser.add_argument("--validate-before", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap-replicates", type=int, default=1000)
    parser.add_argument("--horizon-days", type=int, default=14)
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument(
        "--observed-since",
        help="Export only immutable outcome observations created at or after this aware ISO timestamp",
    )
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    try:
        from app.core.settings import get_settings
        from app.db.session import get_engine

        result = refresh(
            get_engine(),
            args.output,
            environment=get_settings().environment,
            train_before=args.train_before,
            validate_before=args.validate_before,
            seed=args.seed,
            bootstrap_replicates=args.bootstrap_replicates,
            promote=args.promote,
            horizon_days=args.horizon_days,
            max_rows=args.max_rows,
            observed_since=args.observed_since,
        )
    except Exception:
        # Never print connection strings, credentials, raw rows, or exception text.
        parser.exit(
            2, "Matching refresh could not complete; inspect registry and output status before retrying.\n"
        )
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["status"] in {"FAILED", "PROMOTION_REJECTED", "PROMOTION_STATE_UNKNOWN"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
