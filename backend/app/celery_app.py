from celery import Celery
from kombu import Queue

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("zhongmei", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_queues=(
        Queue("default"),
        Queue("ingest"),
        Queue("rag"),
        Queue("plan"),
        Queue("docx"),
    ),
    task_routes={
        "ingest.*": {"queue": "ingest"},
        "rag.*": {"queue": "rag"},
        "plan.*": {"queue": "plan"},
        "docx.*": {"queue": "docx"},
    },
    timezone="Asia/Shanghai",
)


@celery_app.task(name="default.ping")
def ping() -> dict[str, str]:
    return {"status": "pong"}
