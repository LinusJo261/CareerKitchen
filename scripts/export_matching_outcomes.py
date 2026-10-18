"""Export frozen, consented matching observations using a read-only database session.

Only production exports are marked as observed outcomes. Other environments stay
explicitly fictional. Empty datasets are useful diagnostics, never accuracy proof.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.mutual_matching_features import validate_features

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

TARGET = "mutual_opt_in_within_horizon"
FEATURE_VERSION = "mutual-pair-features-v1"
DATASET = "career-kitchen-consented-introductions"
ROW_KEYS = {
    "cycle_id",
    "candidate_id",
    "vacancy_id",
    "organization_id",
    "candidate_version",
    "vacancy_version",
    "feature_as_of",
    "first_exposed_at",
    "first_mover",
    "policy_version",
    "eligibility",
    "observation_status",
    "observed_at",
    "features",
    "decisions",
}


def _source_kind(environment: str) -> str:
    if environment not in {"development", "test", "staging", "production"}:
        raise ValueError("Export requires a declared application environment")
    return "observed_introduction_outcomes" if environment == "production" else "fictional_fixture"


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Frozen export timestamps must be timezone-aware ISO strings")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Frozen export timestamps must be timezone-aware ISO strings") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Frozen export timestamps must include timezone")
    return result.astimezone(UTC)


def _validate_rows(rows: object, max_rows: int, exported_at: datetime) -> list[dict]:
    """Fail closed on accidental raw identities or extra profile/document fields.

    The service owns consent, provenance and outcome derivation. This boundary
    preserves its frozen rows verbatim and does not reconstruct current profiles.
    """
    if not isinstance(rows, list) or len(rows) > max_rows:
        raise ValueError("Service returned an invalid or oversized observation export")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise ValueError("Service returned an incompatible frozen observation schema")
        for key in ("cycle_id", "candidate_id", "vacancy_id", "organization_id"):
            value = row[key]
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError("Exported identities must be keyed pseudonyms")
        if row["cycle_id"] in seen:
            raise ValueError("Each frozen introduction must appear once")
        seen.add(row["cycle_id"])
        for key in ("candidate_version", "vacancy_version"):
            if type(row[key]) is not int or row[key] < 1:
                raise ValueError("Frozen observation versions must be positive integers")
        if not isinstance(row["policy_version"], str) or not row["policy_version"].strip():
            raise ValueError("Frozen scoring policy version is required")
        as_of, exposed, observed = (
            _timestamp(row[key]) for key in ("feature_as_of", "first_exposed_at", "observed_at")
        )
        if not as_of <= exposed <= observed <= exported_at:
            raise ValueError("Frozen export contains unavailable or future information")
        validate_features(row["features"])
        if row["first_mover"] not in ("candidate", "employer"):
            raise ValueError("Invalid frozen first mover")
        decisions = row["decisions"]
        if not isinstance(decisions, dict) or set(decisions) != {"candidate", "employer"}:
            raise ValueError("Frozen export must declare both decision states")
        for decision in decisions.values():
            if not isinstance(decision, dict) or set(decision) != {"status", "issued_at", "answered_at"}:
                raise ValueError("Incompatible frozen decision schema")
            if decision["status"] not in (
                "NOT_ISSUED",
                "PENDING",
                "INTERESTED",
                "PASSED",
                "EXPIRED",
                "CANCELLED",
            ):
                raise ValueError("Invalid frozen decision status")
            for key in ("issued_at", "answered_at"):
                if decision[key] is not None and not exposed <= _timestamp(decision[key]) <= observed:
                    raise ValueError("Decision timestamp outside frozen observation window")
        if row["eligibility"] not in ("ELIGIBLE", "INELIGIBLE", "NEEDS_CLARIFICATION"):
            raise ValueError("Invalid frozen eligibility state")
        if row["observation_status"] not in ("OBSERVABLE", "CANCELLED", "TERMS_CHANGED", "WITHDRAWN"):
            raise ValueError("Invalid frozen observation status")
    return rows


def _aggregate_diagnostics(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Export diagnostics must contain aggregate counts only")
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError("Invalid aggregate diagnostic name")
        if isinstance(item, dict):
            _aggregate_diagnostics(item)
        elif not (type(item) is bool or type(item) is int and item >= 0):
            raise ValueError("Export diagnostics must contain aggregate counts only")
    return value


def _read_observations(
    engine: Engine, horizon_days: int, max_rows: int, observed_since: datetime | None = None
) -> dict:
    from app.services.matching_learning import export_observations
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '30000ms'"))
        with Session(bind=connection, autoflush=False) as db:
            return export_observations(
                db, horizon_days=horizon_days, max_rows=max_rows, observed_since=observed_since
            )


def export_dataset(
    engine: Engine,
    output: Path,
    *,
    environment: str,
    horizon_days: int = 14,
    max_rows: int = 10_000,
    observed_since: datetime | str | None = None,
) -> dict:
    """Publish a new immutable dataset directory; return paths and aggregate counts.

    The caller supplies the configured backend engine and environment. This is an
    operator helper, not an unscoped application endpoint. No database writes or
    raw connection details are emitted.
    """
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a fresh immutable export output directory")
    source_kind = _source_kind(environment)
    if type(horizon_days) is not int or not 1 <= horizon_days <= 365:
        raise ValueError("Outcome horizon must be an integer in 1..365 days")
    if type(max_rows) is not int or not 1 <= max_rows <= 100_000:
        raise ValueError("Export row limit must be an integer in 1..100000")
    since = None
    if observed_since is not None:
        since = observed_since if isinstance(observed_since, datetime) else _timestamp(observed_since)
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("Observation window must include timezone")
        since = since.astimezone(UTC)
    if engine.dialect.name != "postgresql":
        raise ValueError("Matching outcome export requires PostgreSQL read-only transactions")
    result = (
        _read_observations(engine, horizon_days, max_rows, observed_since=since)
        if since is not None
        else _read_observations(engine, horizon_days, max_rows)
    )
    if not isinstance(result, dict) or set(result) != {"rows", "diagnostics", "consent_source_version"}:
        raise ValueError("Unexpected matching observation export result")
    exported_at = datetime.now(UTC)
    rows = _validate_rows(result["rows"], max_rows, exported_at)
    diagnostics = _aggregate_diagnostics(result["diagnostics"])
    source_version = result["consent_source_version"]
    if not isinstance(source_version, str) or not source_version.strip():
        raise ValueError("A frozen consent source version is required")
    manifest = {
        "schema_version": 1,
        "target": TARGET,
        "feature_version": FEATURE_VERSION,
        "horizon_days": horizon_days,
        "source": {
            "kind": source_kind,
            "dataset": DATASET,
            "source_version": source_version,
            "exported_at": exported_at.isoformat(),
        },
    }
    serialized = {
        "introductions.jsonl": "".join(
            json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows
        ),
        "manifest.json": json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        "diagnostics.json": json.dumps(
            {"exported_rows": len(rows), "counts": diagnostics}, indent=2, sort_keys=True, allow_nan=False
        )
        + "\n",
        "export_window.json": json.dumps(
            {
                "schema_version": 1,
                "observation_created_at_gte": since.isoformat() if since else None,
                "snapshot_exported_at": exported_at.isoformat(),
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve()
    staging = Path(tempfile.mkdtemp(prefix=".matching-export-", dir=parent))
    try:
        for name, content in serialized.items():
            (staging / name).write_text(content, encoding="utf-8", newline="\n")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Choose a fresh immutable export output directory")
        staging.rename(output)
    finally:
        if staging.exists():
            if staging.resolve().parent != parent or not staging.name.startswith(".matching-export-"):
                raise RuntimeError("Refusing cleanup outside the export staging directory")
            shutil.rmtree(staging)
    return {
        "row_count": len(rows),
        "source_kind": source_kind,
        "output": str(output),
        "input_path": str(output / "introductions.jsonl"),
        "manifest_path": str(output / "manifest.json"),
        "diagnostics_path": str(output / "diagnostics.json"),
        "observed_since": since.isoformat() if since else None,
        "window_path": str(output / "export_window.json"),
    }


def main() -> int:
    from app.core.settings import get_settings
    from sqlalchemy import create_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizon-days", type=int, default=14)
    parser.add_argument("--max-rows", type=int, default=10_000)
    parser.add_argument(
        "--observed-since", help="Inclusive timezone-aware lower bound on frozen observation creation time"
    )
    args = parser.parse_args()
    engine = None
    try:
        settings = get_settings()
        engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
        summary = export_dataset(
            engine,
            args.output,
            environment=settings.environment,
            horizon_days=args.horizon_days,
            max_rows=args.max_rows,
            observed_since=args.observed_since,
        )
        print(json.dumps(summary, sort_keys=True))
        return 0
    except Exception as error:
        # Driver and configuration exceptions can contain DSNs or other secrets.
        print(f"Matching outcome export failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
