from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditLog
from app.models.document import Document, DocumentIngestJob


async def mark_dead_letter(
    db: AsyncSession,
    *,
    document: Document,
    job: DocumentIngestJob,
    error: str,
) -> None:
    document.status = "failed"
    job.status = "dead"
    job.last_error = error[:4000]
    db.add(
        AuditLog(
            actor_user_id=document.uploader_id,
            action="ingest.step_failed",
            target_type="document",
            target_id=document.id,
            ip_address="worker",
            user_agent="celery",
            details={"job_id": job.id, "error": error[:1000]},
        )
    )
    await db.flush()
