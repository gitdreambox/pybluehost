from pathlib import Path

from pybluehost.cli.app.mitm.acl import RelayDirection
from pybluehost.cli.app.mitm.capture import BtsnoopCaptureTap, NullTap


async def test_null_tap_is_noop():
    tap = NullTap()
    await tap.on_pdu(RelayDirection.PHONE_TO_TARGET, 0x40, b"\x00\x01")
    await tap.close()  # 不抛异常即可


async def test_btsnoop_tap_writes_records(tmp_path: Path):
    path = tmp_path / "cap.btsnoop"
    tap = BtsnoopCaptureTap(path)
    await tap.on_pdu(RelayDirection.TARGET_TO_PHONE, 0x40,
                     bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00]))
    await tap.close()

    raw = path.read_bytes()
    assert raw.startswith(b"btsnoop\x00")        # 文件头
    assert len(raw) > 16                          # 头之外有记录
    assert bytes([0x0A, 0x03, 0x00]) in raw       # ATT payload 落盘
