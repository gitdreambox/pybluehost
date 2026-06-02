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


async def test_btsnoop_tap_preserves_order_and_drains_on_close(tmp_path: Path):
    """多条 PDU 后台串行写入,close() 确保全部落盘且保持入队顺序。"""
    path = tmp_path / "multi.btsnoop"
    tap = BtsnoopCaptureTap(path)
    for i in range(5):
        await tap.on_pdu(RelayDirection.PHONE_TO_TARGET, 0x40,
                         bytes([0x01, 0x00, 0x04, 0x00, 0xA0 + i]))
    await tap.close()

    raw = path.read_bytes()
    # 5 条 payload 末字节按入队顺序出现
    positions = [raw.find(bytes([0xA0 + i])) for i in range(5)]
    assert all(p != -1 for p in positions)        # 全部落盘
    assert positions == sorted(positions)         # 顺序保持


async def test_on_pdu_after_close_is_noop(tmp_path: Path):
    tap = BtsnoopCaptureTap(tmp_path / "c.btsnoop")
    await tap.close()
    # close 后再 on_pdu 不应抛异常,也不写入
    await tap.on_pdu(RelayDirection.PHONE_TO_TARGET, 0x40, bytes([0x01, 0x00, 0x04, 0x00, 0x99]))
