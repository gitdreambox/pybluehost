"""Tests for CLI logging defaults."""
from __future__ import annotations

import logging

from pybluehost.cli._logging import configure_cli_logging


def test_configure_cli_logging_writes_terminal_streams_and_file(tmp_path, capsys):
    log_file = tmp_path / "pybluehost.log"
    configure_cli_logging(log_file=log_file, force=True)

    logger = logging.getLogger("pybluehost.cli.test")
    logger.info("visible info")
    logger.error("visible error")

    captured = capsys.readouterr()
    assert "visible info" in captured.out
    assert "visible error" in captured.err

    text = log_file.read_text(encoding="utf-8")
    assert "INFO pybluehost.cli.test: visible info" in text
    assert "ERROR pybluehost.cli.test: visible error" in text


def test_configure_cli_logging_is_idempotent(tmp_path, capsys):
    log_file = tmp_path / "pybluehost.log"
    configure_cli_logging(log_file=log_file, force=True)
    configure_cli_logging(log_file=log_file)

    logging.getLogger("pybluehost.cli.test").info("once")

    captured = capsys.readouterr()
    assert captured.out.count("once") == 1
    assert log_file.read_text(encoding="utf-8").count("once") == 1
