import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pybluehost.transport.firmware.downloader import FirmwareDownloader, FirmwareDownloadError


class TestFirmwareDownloader:
    def test_download_success(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"fake firmware data"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {"Content-Length": "18"}

        with patch("urllib.request.urlopen", return_value=mock_response):
            path = FirmwareDownloader.download("test.fw", "intel", tmp_path)

        assert path.exists()
        assert path.read_bytes() == b"fake firmware data"

    def test_download_retry_then_success(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"ok"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {}

        calls = [urllib.error.URLError("timeout"), urllib.error.URLError("timeout"), mock_response]

        def side_effect(*args, **kwargs):
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep"):
                path = FirmwareDownloader.download("test.fw", "intel", tmp_path)

        assert path.exists()
        assert path.read_bytes() == b"ok"

    def test_download_all_retries_fail(self, tmp_path: Path):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network down")):
            with patch("time.sleep"):
                with pytest.raises(FirmwareDownloadError) as exc_info:
                    FirmwareDownloader.download("ibt-0291-0291.sfi", "intel", tmp_path)

        err = exc_info.value
        assert "ibt-0291-0291.sfi" in str(err)
        assert "git.kernel.org" in str(err)
        assert "手动下载" in str(err)

    def test_intel_url(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"intel fw"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = mock_response
            FirmwareDownloader.download("ibt-0291-0291.sfi", "intel", tmp_path)

        call_url = mock_urlopen.call_args[0][0]
        assert "linux-firmware.git/plain/intel/ibt-0291-0291.sfi" in call_url

    def test_realtek_url(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"rtk fw"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = mock_response
            FirmwareDownloader.download("rtl8761b_fw.bin", "realtek", tmp_path)

        call_url = mock_urlopen.call_args[0][0]
        assert "linux-firmware.git/plain/rtl_bt/rtl8761b_fw.bin" in call_url
