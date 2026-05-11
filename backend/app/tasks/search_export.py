from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import zipfile
from pathlib import Path

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.auth import User
from app.models.search_export import SearchExportJob
from app.services.rag.search_service import SearchService


@celery_app.task(name="search.export_generate", bind=True, acks_late=True)
def export_generate(self: object, *, job_id: str, user_id: str) -> dict[str, object]:
    return asyncio.run(_run_export(job_id, user_id))


async def _run_export(job_id: str, user_id: str) -> dict[str, object]:
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        job = await db.get(SearchExportJob, job_id)
        if job is None:
            return {"error": "job not found"}

        job.status = "running"
        await db.commit()

        try:
            user = await db.get(User, user_id)
            if user is None:
                raise RuntimeError("user not found")

            svc = SearchService(db)
            filters = dict(job.filters_json or {})
            query_value = filters.pop("query", "")
            query = query_value if isinstance(query_value, str) else str(query_value)
            kb_id = filters.pop("kb_id", None)
            filters = {k: v for k, v in filters.items() if v not in (None, "")}

            results, total = await svc.search(
                user=user,
                query=query,
                kb_id=kb_id if isinstance(kb_id, str) and kb_id else None,
                filters=filters,
                page=1,
                page_size=10000,
                sort_by="relevance",
            )

            export_dir = Path(settings.export_dir)
            export_dir.mkdir(parents=True, exist_ok=True)
            zip_path = export_dir / f"{job_id}.zip"

            metadata = {
                "job_id": job_id,
                "query": query,
                "filters": job.filters_json,
                "result_count": total,
                "format": job.format,
            }

            with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

                if job.format == "csv":
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow(
                        [
                            "index",
                            "chunk_id",
                            "document_id",
                            "document_title",
                            "knowledge_base_id",
                            "section_path",
                            "page_start",
                            "page_end",
                            "snippet",
                            "score",
                        ]
                    )
                    for idx, r in enumerate(results, 1):
                        writer.writerow(
                            [
                                idx,
                                r.chunk_id,
                                r.document_id,
                                r.document_title,
                                r.knowledge_base_id,
                                " > ".join(r.section_path),
                                r.page_start,
                                r.page_end,
                                r.snippet,
                                f"{r.score:.4f}",
                            ]
                        )
                    zf.writestr("results.csv", buf.getvalue())
                else:
                    hits = []
                    for idx, r in enumerate(results, 1):
                        hits.append(
                            {
                                "index": idx,
                                "chunk_id": r.chunk_id,
                                "document_id": r.document_id,
                                "document_title": r.document_title,
                                "knowledge_base_id": r.knowledge_base_id,
                                "section_path": r.section_path,
                                "section_text": r.section_text,
                                "page_start": r.page_start,
                                "page_end": r.page_end,
                                "bbox": r.bbox,
                                "snippet": r.snippet,
                                "score": r.score,
                            }
                        )
                    zf.writestr("results.json", json.dumps(hits, ensure_ascii=False, indent=2))

            file_size = os.path.getsize(str(zip_path))
            job.status = "succeeded"
            job.file_path = str(zip_path)
            job.file_size = file_size
            job.result_count = total
            await db.commit()
            return {"status": "succeeded", "result_count": total}

        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)[:2000]
            await db.commit()
            return {"status": "failed", "error": str(exc)}
