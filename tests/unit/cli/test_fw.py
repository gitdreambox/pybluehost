"""Tests for pybluehost fw CLI subcommands."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from pybluehost.cli.tools.fw import (
    fw_list,
    fw_download,
    fw_info,
    fw_clean,
    _download_firmware_files,
)


def test_fw_list_empty(tmp_path):
    """fw_list returns empty list when no firmware installed."""
    result = fw_list(fw_dir=tmp_path)
    assert result == []


def test_fw_list_finds_files(tmp_path):
    """fw_list returns firmware files in directory."""
    (tmp_path / "ibt-0040-0032.sfi").write_bytes(b"\x00" * 100)
    (tmp_path / "rtl8761b_fw").write_bytes(b"\xFF" * 200)
    result = fw_list(fw_dir=tmp_path)
    assert len(result) == 2
    names = [r["name"] for r in result]
    assert "ibt-0040-0032.sfi" in names
    assert "rtl8761b_fw" in names


def test_fw_list_includes_size(tmp_path):
    """fw_list entries include file size."""
    (tmp_path / "fw.bin").write_bytes(b"\x00" * 512)
    result = fw_list(fw_dir=tmp_path)
    assert result[0]["size"] == 512


def test_fw_info_existing_file(tmp_path):
    """fw_info returns metadata for an existing firmware file."""
    fw_file = tmp_path / "ibt-0040-0032.sfi"
    fw_file.write_bytes(b"\x00" * 1024)
    info = fw_info(fw_file)
    assert info["name"] == "ibt-0040-0032.sfi"
    assert info["size"] == 1024
    assert "path" in info


def test_fw_info_nonexistent_raises(tmp_path):
    """fw_info raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        fw_info(tmp_path / "nonexistent.bin")


def test_fw_download_intel(tmp_path):
    """fw_download for intel calls FirmwareDownloader."""
    with patch(
        "pybluehost.transport.firmware.downloader.FirmwareDownloader.download"
    ) as mock_dl:
        mock_dl.return_value = tmp_path / "ibt-0291-0291.sfi"
        fw_download(vendor="intel", fw_dir=tmp_path)
        assert mock_dl.call_count >= 1


def test_fw_download_realtek(tmp_path):
    """fw_download for realtek calls FirmwareDownloader."""
    with patch(
        "pybluehost.transport.firmware.downloader.FirmwareDownloader.download"
    ) as mock_dl:
        mock_dl.return_value = tmp_path / "rtl8761b_fw.bin"
        fw_download(vendor="realtek", fw_dir=tmp_path)
        assert mock_dl.call_count >= 1


def test_fw_download_unknown_vendor_raises(tmp_path):
    """fw_download raises ValueError for unknown vendor."""
    with pytest.raises(ValueError, match="Unknown vendor"):
        fw_download(vendor="qualcomm", fw_dir=tmp_path)


def test_fw_clean_removes_files(tmp_path):
    """fw_clean removes all files from firmware directory."""
    (tmp_path / "fw1.bin").write_bytes(b"\x00")
    (tmp_path / "fw2.bin").write_bytes(b"\x00")
    removed = fw_clean(fw_dir=tmp_path)
    assert removed == 2
    assert list(tmp_path.iterdir()) == []


def test_fw_clean_empty_dir(tmp_path):
    """fw_clean on empty dir returns 0."""
    removed = fw_clean(fw_dir=tmp_path)
    assert removed == 0


class TestDownloadFirmwareFiles:
    def test_download_intel_files(self, tmp_path: Path):
        with patch(
            "pybluehost.transport.firmware.downloader.FirmwareDownloader.download"
        ) as mock_dl:
            mock_dl.side_effect = [
                tmp_path / "ibt-0291-0291.sfi",
                tmp_path / "ibt-0291-0291.ddc",
                tmp_path / "ibt-0040-0041.sfi",
                tmp_path / "ibt-0040-0041.ddc",
            ]
            downloaded = _download_firmware_files("intel", tmp_path)

        assert len(downloaded) == 4
        assert mock_dl.call_count == 4
        calls = [c.args[0] for c in mock_dl.call_args_list]
        assert "ibt-0291-0291.sfi" in calls
        assert "ibt-0291-0291.ddc" in calls
        assert "ibt-0040-0041.sfi" in calls
        assert "ibt-0040-0041.ddc" in calls

    def test_download_realtek_files(self, tmp_path: Path):
        with patch(
            "pybluehost.transport.firmware.downloader.FirmwareDownloader.download"
        ) as mock_dl:
            mock_dl.side_effect = [
                tmp_path / "rtl8761b_fw.bin",
                tmp_path / "rtl8761b_config.bin",
            ]
            downloaded = _download_firmware_files("realtek", tmp_path)

        assert len(downloaded) == 2
        assert mock_dl.call_count == 2
        calls = [c.args[0] for c in mock_dl.call_args_list]
        assert "rtl8761b_fw.bin" in calls
        assert "rtl8761b_config.bin" in calls

    def test_download_unknown_vendor(self, tmp_path: Path):
        with patch(
            "pybluehost.transport.firmware.downloader.FirmwareDownloader.download"
        ) as mock_dl:
            downloaded = _download_firmware_files("qualcomm", tmp_path)

        assert downloaded == []
        assert mock_dl.call_count == 0
