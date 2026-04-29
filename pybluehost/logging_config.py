"""Global logging configuration for PyBlueHost entry points."""
from __future__ import annotations

import __main__
import copy
import logging
import logging.config
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml


DEFAULT_LOG_FILE = Path("pybluehost.log")
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_CONFIG = files("pybluehost.config").joinpath("log_config.yaml")


class MaxLevelFilter(logging.Filter):
    """Allow only records at or below a configured level."""

    def __init__(self, max_level: str | int) -> None:
        super().__init__()
        self._max_level = _coerce_level(max_level)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._max_level


class DynamicStreamHandler(logging.StreamHandler):
    """Resolve stdout/stderr at emit time so pytest capture keeps working."""

    def __init__(self, stream_name: str) -> None:
        super().__init__()
        self._stream_name = stream_name

    @property
    def stream(self):  # type: ignore[override]
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, value) -> None:  # type: ignore[override]
        pass


def configure_logging(
    *,
    log_file: str | Path | None = DEFAULT_LOG_FILE,
    level: str | int = DEFAULT_LOG_LEVEL,
    config_path: str | Path | None = None,
) -> None:
    """Configure PyBlueHost logging from log_config.yaml."""
    path = Path(config_path) if config_path is not None else DEFAULT_LOG_CONFIG
    config = _load_config(path)
    _apply_runtime_overrides(config, log_file=log_file, level=level)
    logging.config.dictConfig(config)


def reset_logging() -> None:
    """Remove handlers installed on the PyBlueHost logger."""
    logger = logging.getLogger("pybluehost")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = True


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"logging config must be a mapping: {path}")
    return copy.deepcopy(data)


def _apply_runtime_overrides(
    config: dict[str, Any],
    *,
    log_file: str | Path | None,
    level: str | int,
) -> None:
    numeric_level = logging.getLevelName(_coerce_level(level))
    handlers = config.get("handlers", {})
    loggers = config.get("loggers", {})
    pybluehost_logger = loggers.get("pybluehost", {})

    pybluehost_logger["level"] = numeric_level
    for handler_name in pybluehost_logger.get("handlers", []):
        handler = handlers.get(handler_name)
        if isinstance(handler, dict):
            if handler_name == "stdout":
                handler["level"] = numeric_level
            elif handler_name == "file":
                handler["level"] = "DEBUG"

    if log_file is None:
        pybluehost_logger["handlers"] = [
            handler for handler in pybluehost_logger.get("handlers", []) if handler != "file"
        ]
        handlers.pop("file", None)
    else:
        file_path = Path(log_file)
        if file_path.parent != Path("."):
            file_path.parent.mkdir(parents=True, exist_ok=True)
        __main__.log_name = str(file_path)


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, level.upper(), logging.INFO)
