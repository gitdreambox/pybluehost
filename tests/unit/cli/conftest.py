"""CLI test fixtures."""
from __future__ import annotations

import pytest

from pybluehost.logging_config import configure_logging, reset_logging


@pytest.fixture(autouse=True)
def cli_logging(tmp_path_factory):
    log_dir = tmp_path_factory.mktemp("cli-logs")
    configure_logging(log_file=log_dir / "pybluehost.log")
    yield
    reset_logging()
