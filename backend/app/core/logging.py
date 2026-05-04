import json
import logging
import sys
from typing import Any

from loguru import logger

from app.core.config import Settings


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def json_sink(message: Any) -> None:
    record = message.record
    payload = {
        "time": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
        "extra": record["extra"],
    }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stdout)


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    logger.remove()
    logger.add(json_sink, level=settings.log_level.upper(), enqueue=True)
