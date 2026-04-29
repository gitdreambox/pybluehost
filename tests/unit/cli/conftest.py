"""CLI test fixtures."""
from __future__ import annotations

import pytest

from pybluehost.cli._logging import configure_cli_logging, reset_cli_logging


@pytest.fixture(autouse=True)
def cli_logging(tmp_path_factory):
    log_dir = tmp_path_factory.mktemp("cli-logs")
    configure_cli_logging(log_file=log_dir / "pybluehost.log", force=True)
    yield
    reset_cli_logging()
