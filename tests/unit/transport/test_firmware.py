"""Tests for FirmwarePolicy, FirmwareManager, FirmwareNotFoundError."""

import pytest
from pathlib import Path
from unittest.mock import patch

from pybluehost.transport.firmware import (
    FirmwarePolicy,
    FirmwareManager,
    FirmwareNotFoundError,
)


def test_firmware_policy_enum():
    assert FirmwarePolicy.PROMPT == "prompt"
    assert FirmwarePolicy.ERROR == "error"
    assert FirmwarePolicy.AUTO_DOWNLOAD == "auto"


def test_firmware_manager_finds_file(tmp_path):
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    fw_file = fw_dir / "ibt-0040-0041.sfi"
    fw_file.write_bytes(b"\xFF" * 1024)

    mgr = FirmwareManager(vendor="intel", extra_dirs=[fw_dir])
    result = mgr.find("ibt-0040-0041.sfi")
    assert result == fw_file


def test_firmware_manager_missing_raises_on_error_policy():
    mgr = FirmwareManager(vendor="intel", policy=FirmwarePolicy.ERROR)
    with pytest.raises(FirmwareNotFoundError) as exc_info:
        mgr.find("nonexistent-fw-file-12345.sfi")
    assert "nonexistent-fw-file-12345.sfi" in str(exc_info.value)
    assert "pybluehost fw download" in str(exc_info.value)


def test_firmware_manager_prompt_policy():
    mgr = FirmwareManager(vendor="intel", policy=FirmwarePolicy.PROMPT)
    with pytest.raises(FirmwareNotFoundError) as exc_info:
        mgr.find("nonexistent-fw-file-12345.sfi")
    msg = str(exc_info.value)
    # Should contain download instructions
    assert "pybluehost fw download" in msg


def test_firmware_search_priority(tmp_path):
    """Extra dirs take precedence over default dirs (first listed = highest priority)."""
    high_prio = tmp_path / "high"
    low_prio = tmp_path / "low"
    high_prio.mkdir()
    low_prio.mkdir()

    (low_prio / "fw.bin").write_bytes(b"\x01")
    (high_prio / "fw.bin").write_bytes(b"\x02")

    mgr = FirmwareManager(vendor="intel", extra_dirs=[high_prio, low_prio])
    result = mgr.find("fw.bin")
    assert result.read_bytes() == b"\x02"


def test_firmware_manager_data_dir():
    """data_dir returns a platform-specific path."""
    mgr = FirmwareManager(vendor="intel")
    data_dir = mgr.data_dir
    assert isinstance(data_dir, Path)
    assert "pybluehost" in str(data_dir)


def test_firmware_manager_default_policy_is_prompt():
    mgr = FirmwareManager(vendor="intel")
    assert mgr.policy == FirmwarePolicy.PROMPT


def test_firmware_not_found_error_is_runtime_error():
    err = FirmwareNotFoundError("test")
    assert isinstance(err, RuntimeError)


class TestFirmwareManagerAutoDownload:
    def test_find_or_download_finds_existing(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.AUTO_DOWNLOAD)
        (tmp_path / "existing.sfi").write_text("fw")
        path = mgr.find_or_download("existing.sfi")
        assert path == tmp_path / "existing.sfi"

    def test_find_or_download_triggers_auto_download(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.AUTO_DOWNLOAD)

        with patch(
            "pybluehost.transport.firmware.downloader.FirmwareDownloader.download"
        ) as mock_dl:
            mock_dl.return_value = tmp_path / "auto.sfi"
            path = mgr.find_or_download("auto.sfi")

        mock_dl.assert_called_once_with("auto.sfi", "intel", mgr.data_dir)
        assert path == tmp_path / "auto.sfi"

    def test_find_or_download_error_policy_no_download(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.ERROR)
        with pytest.raises(FirmwareNotFoundError):
            mgr.find_or_download("missing.sfi")

    def test_find_or_download_prompt_policy_no_download(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.PROMPT)
        with pytest.raises(FirmwareNotFoundError):
            mgr.find_or_download("missing.sfi")
