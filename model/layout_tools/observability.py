from __future__ import annotations

import logging
import time
from typing import Any, Literal

logger = logging.getLogger(__name__)


def _format(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def log_stage(stage: str, elapsed_ms: float, **fields: Any) -> None:
    payload = " ".join("%s=%s" % (key, _format(value)) for key, value in fields.items())
    message = "阶段 %s 耗时 %.1fms" % (stage, elapsed_ms)
    if payload:
        message = "%s %s" % (message, payload)
    logger.info(message)


class StageTimer:
    def __init__(self, stage: str, **fields: Any) -> None:
        self.stage = stage
        self.fields = dict(fields)
        self._start = 0.0

    def __enter__(self) -> "StageTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        fields = dict(self.fields)
        if exc_type is None:
            fields.setdefault("status", "ok")
        else:
            fields.setdefault("status", "error")
            fields.setdefault("error", getattr(exc_type, "__name__", "Exception"))
        log_stage(
            self.stage,
            (time.perf_counter() - self._start) * 1000,
            **fields,
        )
        return False

    def set(self, **fields: Any) -> None:
        self.fields.update(fields)
