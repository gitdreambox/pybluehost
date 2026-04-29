"""CLI logging configuration for terminal and file output."""
from __future__ import annotations

import logging
import sys
from pathlib import Path


DEFAULT_LOG_FILE = Path("pybluehost.log")
DEFAULT_LOG_LEVEL = "INFO"
_HANDLER_MARKER = "_pybluehost_cli_handler"


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self._max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._max_level


class _DynamicStreamHandler(logging.StreamHandler):
    def __init__(self, stream_name: str) -> None:
        super().__init__()
        self._stream_name = stream_name

    @property
    def stream(self):  # type: ignore[override]
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, value) -> None:  # type: ignore[override]
        pass


def configure_cli_logging(
    *,
    log_file: str | Path | None = DEFAULT_LOG_FILE,
    level: str | int = DEFAULT_LOG_LEVEL,
    force: bool = False,
) -> None:
    """Route PyBlueHost logs to terminal streams and a log file by default."""
    logger = logging.getLogger("pybluehost")
    numeric_level = _coerce_level(level)

    if force:
        _remove_cli_handlers(logger)
    elif any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        logger.setLevel(numeric_level)
        return

    stdout_handler = _DynamicStreamHandler("stdout")
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    setattr(stdout_handler, _HANDLER_MARKER, True)
    logger.addHandler(stdout_handler)

    stderr_handler = _DynamicStreamHandler("stderr")
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter("%(message)s"))
    setattr(stderr_handler, _HANDLER_MARKER, True)
    logger.addHandler(stderr_handler)

    if log_file is not None:
        path = Path(log_file)
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        setattr(file_handler, _HANDLER_MARKER, True)
        logger.addHandler(file_handler)

    logger.setLevel(numeric_level)
    logger.propagate = False


def reset_cli_logging() -> None:
    """Remove CLI handlers and restore propagation for tests or embedded use."""
    logger = logging.getLogger("pybluehost")
    _remove_cli_handlers(logger)
    logger.propagate = True


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, level.upper(), logging.INFO)


def _remove_cli_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()
