import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        # Merge any extra fields injected via log_event
        extra = getattr(record, "_extra", None)
        if extra:
            obj.update(extra)

        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(obj)


def setup_logging() -> None:
    level = logging.INFO if os.getenv("FLY_APP_NAME") else logging.DEBUG

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())

    root = logging.getLogger()
    root.setLevel(level)

    # Replace any existing handlers so we don't get duplicate lines
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: str,
    event: str,
    **kwargs: Any,
) -> None:
    log_fn = getattr(logger, level.lower(), logger.info)
    extra = {"event": event, **kwargs}

    # Attach extra fields so _JSONFormatter can pick them up
    record_extra = {"_extra": extra}
    log_fn(event, extra=record_extra)
