"""Repeat consented outcome learning with fresh cohorts and qualified promotion.

Run as a separate supervised operator process, never inside an API transaction.
The controller waits for new immutable resolutions and a fresh forward-time
evaluation window. It cannot invent outcomes or override the registry gates.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

LOCK_SCOPE = "career-kitchen:continual-matching-learning:v1"
STATE_KEYS = {"schema_version", "last_evaluation_at", "resolution_count_at_evaluation"}


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Controller timestamps require an explicit timezone")
    return result.astimezone(UTC)


def _atomic_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".learning-controller-", suffix=".json", dir=path.parent)
    pending = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def _read_state(path: Path) -> dict:
    if not path.exists() and not path.is_symlink():
        return {"schema_version": 1, "last_evaluation_at": None, "resolution_count_at_evaluation": 0}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Controller state must be a bounded regular JSON file")
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or set(state) != STATE_KEYS
        or type(state["schema_version"]) is not int
        or state["schema_version"] != 1
        or type(state["resolution_count_at_evaluation"]) is not int
        or state["resolution_count_at_evaluation"] < 0
    ):
        raise ValueError("Invalid continual-learning controller state")
    if state["last_evaluation_at"] is not None:
        _timestamp(state["last_evaluation_at"])
    return state


@contextmanager
def _lease(engine):
    from sqlalchemy import text

    # Session advisory locking survives the tiny individual read transactions,
    # releases on process death, and excludes other controllers on this database.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(hashtextextended(:scope, 0))"), {"scope": LOCK_SCOPE}
            )
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:scope, 0))"), {"scope": LOCK_SCOPE}
                )


def _source_state(engine) -> dict:
    from app.db.models import MatchingLearningState, MatchingModel, MatchingObservation
    from sqlalchemy import func, select, text
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        count = db.scalar(select(func.count()).select_from(MatchingObservation)) or 0
        epoch = db.scalar(
            select(MatchingLearningState.version).where(MatchingLearningState.scope == "GLOBAL")
        )
        exports = []
        # Include retired history: retirement must never reopen an old holdout.
        registered_artifacts: list[dict] = list(db.scalars(select(MatchingModel.artifact)))
        for artifact in registered_artifacts:
            exports.append(_timestamp(artifact["source"]["exported_at"]))
        return {
            "stored_resolutions": count,
            "consent_epoch": epoch or 0,
            "latest_registered_export_at": max(exports).isoformat() if exports else None,
        }


def _refresh(engine, output: Path, **options) -> dict:
    from scripts.refresh_matching_learning import refresh

    return refresh(engine, output, **options)


def run_once(
    engine,
    output_root: Path,
    *,
    environment: str,
    promote: bool = False,
    now: datetime | None = None,
    min_new_resolutions: int = 100,
    validation_days: int = 30,
    test_days: int = 30,
    horizon_days: int = 14,
    training_window_days: int = 365,
    max_rows: int = 10000,
) -> dict:
    if environment not in {"development", "test", "staging", "production"}:
        raise ValueError("Unknown environment")
    if type(promote) is not bool or promote and environment != "production":
        raise ValueError("Automatic promotion requires an explicit production request")
    for value, low, high in (
        (min_new_resolutions, 100, 100000),
        (validation_days, 1, 365),
        (test_days, 1, 365),
        (horizon_days, 1, 365),
        (training_window_days, 1, 3650),
        (max_rows, 100, 100000),
    ):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Controller windows and row limits must be bounded positive integers")
    if training_window_days <= validation_days + test_days + horizon_days:
        raise ValueError("Training window must precede both held-out windows and the resolution horizon")
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Controller time must include a timezone")
    clock = clock.astimezone(UTC)
    midnight = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    train_before = midnight - timedelta(days=validation_days + test_days + horizon_days)
    validate_before = train_before + timedelta(days=validation_days)
    output_root.mkdir(parents=True, exist_ok=True)
    with _lease(engine) as acquired:
        if not acquired:
            return {"status": "ANOTHER_REFRESH_RUNNING", "promoted": False}
        state_path = output_root / "controller_state.json"
        state = _read_state(state_path)
        source = _source_state(engine)
        status = {
            "schema_version": 1,
            "status": "WAITING_FOR_NEW_OUTCOMES",
            "checked_at": clock.isoformat(),
            "promoted": False,
            "production_accuracy": None,
            "train_before": train_before.isoformat(),
            "validate_before": validate_before.isoformat(),
            "source": source,
            "new_resolution_count": max(
                0, source["stored_resolutions"] - state["resolution_count_at_evaluation"]
            ),
            "minimum_new_resolutions": min_new_resolutions,
            "count_is_not_a_qualification_gate": True,
        }
        consumed = [
            _timestamp(value)
            for value in (state["last_evaluation_at"], source["latest_registered_export_at"])
            if value is not None
        ]
        if consumed and train_before <= max(consumed):
            status.update(
                status="WAITING_FOR_FRESH_COHORTS",
                earliest_next_window_after=(
                    max(consumed) + timedelta(days=validation_days + test_days + horizon_days + 1)
                ).isoformat(),
            )
        elif status["new_resolution_count"] >= min_new_resolutions:
            # Reserve before any labels are exported/read. Rejected and crashed
            # attempts consume this window too: repeated testing cannot shop for
            # a favorable result. Keep this state on one shared persistent volume.
            _atomic_json(
                state_path,
                {
                    "schema_version": 1,
                    "last_evaluation_at": clock.isoformat(),
                    "resolution_count_at_evaluation": source["stored_resolutions"],
                },
            )
            run_directory = output_root / "runs" / (clock.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex)
            try:
                result = _refresh(
                    engine,
                    run_directory,
                    environment=environment,
                    promote=promote,
                    train_before=train_before.isoformat(),
                    validate_before=validate_before.isoformat(),
                    horizon_days=horizon_days,
                    max_rows=max_rows,
                    observed_since=(midnight - timedelta(days=training_window_days)).isoformat(),
                )
                promotion = result.get("promoted")
                if promotion is not None and type(promotion) is not bool:
                    raise ValueError("Invalid refresh promotion status")
                status.update(
                    status="REFRESH_STATE_UNKNOWN" if promotion is None else "REFRESH_COMPLETED",
                    promoted=promotion,
                    refresh=result,
                )
                if result.get("status") in {"NOT_TRAINED", "INSUFFICIENT_DATA"}:
                    # These explicit early exits calculate no model test metrics.
                    # Wait for another batch without consuming months of future
                    # holdout time merely because classes/cohorts were missing.
                    _atomic_json(
                        state_path,
                        {**state, "resolution_count_at_evaluation": source["stored_resolutions"]},
                    )
            except Exception:
                # Never leak database URLs, raw outcomes, tokens or exception text.
                # Promotion may have committed before a local status failure;
                # consult the registry rather than reporting a false rollback.
                status.update(
                    status="REFRESH_STATE_UNKNOWN", promoted=None, reason_code="REFRESH_STEP_FAILED"
                )
        _atomic_json(output_root / "controller_status.json", status)
        return status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=86400)
    parser.add_argument("--min-new-resolutions", type=int, default=100)
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--horizon-days", type=int, default=14)
    parser.add_argument("--training-window-days", type=int, default=365)
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    if not 60 <= args.poll_seconds <= 604800:
        parser.error("poll-seconds must be between 60 and 604800")
    try:
        from app.core.settings import get_settings
        from app.db.session import get_engine

        while True:
            result = run_once(
                get_engine(),
                args.output_root,
                environment=get_settings().environment,
                promote=args.promote,
                min_new_resolutions=args.min_new_resolutions,
                validation_days=args.validation_days,
                test_days=args.test_days,
                horizon_days=args.horizon_days,
                training_window_days=args.training_window_days,
                max_rows=args.max_rows,
            )
            print(json.dumps(result, allow_nan=False), flush=True)
            if args.once:
                break
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return
    except Exception:
        parser.exit(
            2,
            "Continual learning could not complete; inspect the configured database and controller state.\n",
        )


if __name__ == "__main__":
    main()
