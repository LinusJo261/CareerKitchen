"""Retention-aware local orphan inventory; hosted inventories require operator review."""

from datetime import datetime, timedelta
from heapq import nsmallest
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import Attachment, Candidate
from app.db.pact_models import EvidenceClaim
from app.services.common import Actor, digest, emit, lock_scopes, utcnow


def cleanup_local_orphans(
    db: Session,
    *,
    retention_days: int = 7,
    batch_size: int = 100,
    dry_run: bool = True,
    now: datetime | None = None,
    after_key: str = "",
    actor: Actor | None = None,
) -> dict:
    """Delete only old, well-formed, unreferenced opaque objects inside storage root.

    Upload-before-commit orphans are possible. A multi-day grace interval exceeds
    application transaction timeouts, preventing deletion of in-flight uploads.
    References in candidate resumes, evidence and attachments are all checked.
    """
    if not 1 <= retention_days <= 3650 or not 1 <= batch_size <= 1000:
        raise ValueError("retention must be in 1..3650 days and batch size in 1..1000")
    settings = get_settings()
    if settings.storage_backend != "local":
        return {"status": "NEEDS_PROVIDER_INVENTORY_REVIEW", "eligible": 0, "deleted": 0}
    root = settings.local_storage_dir.resolve()
    if not root.exists():
        return {"status": "DRY_RUN" if dry_run else "COMPLETE", "eligible": 0, "deleted": 0}
    cutoff = (now or utcnow()) - timedelta(days=retention_days)
    eligible = deleted = inspected = 0
    inventory = nsmallest(
        batch_size + 1,
        (path for path in root.glob("*/*.enc") if path.relative_to(root).as_posix() > after_key),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    next_key = None
    for path in inventory[:batch_size]:
        inspected += 1
        next_key = path.relative_to(root).as_posix()
        resolved = path.resolve()
        if (
            path.is_symlink()
            or path.parent.is_symlink()
            or path.parent.resolve() != path.parent.absolute()
            or not resolved.is_relative_to(root)
            or not resolved.is_file()
        ):
            continue
        key = path.relative_to(root).as_posix()
        owner, filename = key.split("/")
        try:
            UUID(owner)
            UUID(filename.removesuffix(".enc"))
        except ValueError:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=cutoff.tzinfo)
        if modified >= cutoff:
            continue
        lock_scopes(db, f"storage-object:{key}")
        referenced = (
            db.scalar(select(Candidate.id).where(Candidate.resume_object_ref == key).limit(1))
            or db.scalar(select(EvidenceClaim.id).where(EvidenceClaim.private_object_ref == key).limit(1))
            or db.scalar(select(Attachment.id).where(Attachment.object_ref == key).limit(1))
        )
        if referenced:
            continue
        eligible += 1
        if not dry_run:
            if actor is None:
                from app.workers.runner import worker_actor

                actor = worker_actor(db)
            path.unlink(missing_ok=True)
            emit(
                db,
                actor,
                "storage.orphan_deleted",
                SimpleNamespace(
                    id=str(UUID(filename.removesuffix(".enc"))),
                    version=1,
                    __tablename__="private_storage_object",
                ),
                payload={"object_key_hash": digest(key), "retention_days": retention_days},
            )
            deleted += 1
    return {
        "status": "DRY_RUN" if dry_run else "COMPLETE",
        "inspected": inspected,
        "eligible": eligible,
        "deleted": deleted,
        "next_key": next_key if len(inventory) > batch_size else None,
    }
