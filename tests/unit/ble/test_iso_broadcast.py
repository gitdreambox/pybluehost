"""IsoBroadcastManager — the broadcaster half of the isochronous channels
(LE_Create_BIG → LE BIG Complete → LE_Setup_ISO_Data_Path → ISO SDUs).

Drives PTS GAP/BIS/BBM/BV-01-C via BTP CREATE_BIG (0x2d) / BIS_BROADCAST
(0x2e). Wire contracts pinned against Zephyr's ``bt_hci_cp_le_create_big`` /
``bt_hci_cp_le_setup_iso_path`` / ``bt_hci_evt_le_big_complete`` (authoritative
reference IUT) and Core Vol 4 Part E §5.4.5 for the ISO SDU framing.
"""
from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace

import pytest

from pybluehost.ble.gap import PERIODIC_ADV_HANDLE, IsoBroadcastManager
from pybluehost.hci.constants import (
    HCI_LE_CREATE_BIG,
    HCI_LE_SETUP_ISO_DATA_PATH,
    HCI_LE_TERMINATE_BIG,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCICommand

BIG_COMPLETE_TIMEOUT_S = 0.5


class _FakeHCI:
    def __init__(self) -> None:
        self.commands: list[tuple[int, bytes]] = []
        self.iso_packets: list[tuple[int, bytes, int, int]] = []

    async def send_command(self, cmd: HCICommand):
        self.commands.append((cmd.opcode, bytes(cmd.parameters)))
        return SimpleNamespace(status=0)

    async def send_iso_data(self, handle, data, *, pb_flag=0, ts_flag=0):
        self.iso_packets.append((handle, bytes(data), pb_flag, ts_flag))


def _big_complete_event(
    handles: list[int], *, status: int = 0x00, big_handle: int = 0x00,
) -> HCI_LE_Meta_Event:
    params = struct.pack(
        "<BB3s3sBBBBBHHB",
        status, big_handle,
        b"\x01\x02\x03",           # Sync_Delay
        b"\x04\x05\x06",           # Latency
        0x02,                      # PHY
        0x02,                      # NSE
        0x01,                      # BN
        0x00,                      # PTO
        0x01,                      # IRC
        0x00FB,                    # Max_PDU
        0x0168,                    # ISO_Interval
        len(handles),
    ) + b"".join(struct.pack("<H", h) for h in handles)
    return HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_CREATE_BIG_COMPLETE,
        subevent_parameters=params,
    )


async def _run_create_big(mgr: IsoBroadcastManager, hci: _FakeHCI, **kwargs):
    handles = kwargs.pop("handles", [0x0E01])
    task = asyncio.ensure_future(mgr.create_big(**kwargs))
    await asyncio.sleep(0)  # let the command go out
    await mgr.on_hci_event(_big_complete_event(handles))
    return await task


# ---------------------------------------------------------------------------
# LE_Create_BIG (0x2068)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_big_sends_the_le_create_big_command():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    await _run_create_big(
        mgr, hci,
        big_handle=0, adv_handle=PERIODIC_ADV_HANDLE, num_bis=1,
        sdu_interval_us=10000, max_sdu=251, max_transport_latency_ms=20,
        rtn=2, phy=0x02, packing=0, framing=0, encryption=0,
        broadcast_code=None,
    )

    assert hci.commands[0][0] == HCI_LE_CREATE_BIG
    body = hci.commands[0][1]
    # §7.8.99: Big_Handle(1) Adv_Handle(1) Num_BIS(1) SDU_Interval(3)
    # Max_SDU(2) Max_Transport_Latency(2) RTN(1) PHY(1) Packing(1) Framing(1)
    # Encryption(1) Broadcast_Code(16) — 31 octets.
    assert len(body) == 31
    big_handle, adv_handle, num_bis = body[0], body[1], body[2]
    sdu_interval = int.from_bytes(body[3:6], "little")
    max_sdu, max_latency = struct.unpack_from("<HH", body, 6)
    rtn, phy, packing, framing, encryption = body[10:15]
    assert (big_handle, adv_handle, num_bis) == (0, PERIODIC_ADV_HANDLE, 1)
    assert sdu_interval == 10000
    assert (max_sdu, max_latency) == (251, 20)
    assert (rtn, phy, packing, framing, encryption) == (2, 0x02, 0, 0, 0)
    assert body[15:] == bytes(16)


@pytest.mark.asyncio
async def test_create_big_with_encryption_carries_the_broadcast_code():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    code = bytes(range(16))
    await _run_create_big(
        mgr, hci, num_bis=1, encryption=1, broadcast_code=code,
    )
    body = hci.commands[0][1]
    assert body[14] == 1  # Encryption byte
    assert body[15:] == code


@pytest.mark.asyncio
async def test_create_big_reports_one_handle_per_bis():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    handles = await _run_create_big(mgr, hci, num_bis=2, handles=[0x0E01, 0x0E02])
    assert handles == {0: 0x0E01, 1: 0x0E02}


# ---------------------------------------------------------------------------
# LE_Setup_ISO_Data_Path (0x206E)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_big_complete_sets_up_the_hci_data_path_per_bis():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    await _run_create_big(mgr, hci, num_bis=1, handles=[0x0E01])

    assert hci.commands[1][0] == HCI_LE_SETUP_ISO_DATA_PATH
    body = hci.commands[1][1]
    # §7.8.107: Conn_Handle(2) Data_Path_Direction(1) Data_Path_ID(1)
    # Coding_Format(1) Company_ID(2) VS_Codec_ID(2) Controller_Delay(3)
    # Codec_Config_Length(1) — 13 octets for an empty config.
    assert len(body) == 13
    conn_handle, = struct.unpack_from("<H", body, 0)
    direction, path_id, coding_format = body[2], body[3], body[4]
    company_id, vs_codec_id = struct.unpack_from("<HH", body, 5)
    controller_delay = int.from_bytes(body[9:12], "little")
    config_len = body[12]
    assert conn_handle == 0x0E01
    # Input direction: the broadcaster's host feeds SDUs to the controller.
    assert direction == 0x00
    assert path_id == 0x00  # HCI
    assert config_len == 0


@pytest.mark.asyncio
async def test_create_big_raises_when_the_big_fails():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    task = asyncio.ensure_future(mgr.create_big(num_bis=1))
    await asyncio.sleep(0)
    await mgr.on_hci_event(
        _big_complete_event([0x0E01], status=0x0C, big_handle=0)
    )
    with pytest.raises(RuntimeError, match="0x0C"):
        await task


@pytest.mark.asyncio
async def test_create_big_times_out_without_a_big_complete():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    with pytest.raises(asyncio.TimeoutError):
        await mgr.create_big(num_bis=1, timeout_s=BIG_COMPLETE_TIMEOUT_S)


# ---------------------------------------------------------------------------
# BIS broadcast (ISO SDUs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bis_broadcast_sends_complete_sdu_framing():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    await _run_create_big(mgr, hci, num_bis=1, handles=[0x0E01])

    await mgr.bis_broadcast(0, b"\x00", copies=5)

    assert len(hci.iso_packets) == 5
    for seq, (handle, sdu, pb_flag, ts_flag) in enumerate(hci.iso_packets):
        assert handle == 0x0E01
        # Complete SDU in one HCI packet: PB_Flag 0b10 (§5.4.5), no timestamp.
        assert pb_flag == 0x02
        assert ts_flag == 0
        sn, = struct.unpack_from("<H", sdu, 0)
        length, = struct.unpack_from("<H", sdu, 2)
        assert sn == seq          # one SDU per packet, sequence increments
        assert length == 1        # ISO_SDU_Length, packet status 0b00
        assert sdu[4:] == b"\x00"


@pytest.mark.asyncio
async def test_bis_broadcast_sequence_number_advances_across_calls():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    await _run_create_big(mgr, hci, num_bis=1, handles=[0x0E01])

    await mgr.bis_broadcast(0, b"\x01", copies=2)
    await mgr.bis_broadcast(0, b"\x02", copies=2)

    sns = [struct.unpack_from("<H", sdu, 0)[0] for _, sdu, _, _ in hci.iso_packets]
    assert sns == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_bis_broadcast_unknown_bis_id_raises():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    await _run_create_big(mgr, hci, num_bis=1, handles=[0x0E01])
    with pytest.raises(KeyError):
        await mgr.bis_broadcast(7, b"\x00")


# ---------------------------------------------------------------------------
# BIG teardown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_terminate_big_sends_the_command():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    await mgr.terminate_big(big_handle=0, reason=0x16)
    assert hci.commands[0] == (HCI_LE_TERMINATE_BIG, b"\x00\x16")


@pytest.mark.asyncio
async def test_big_terminate_clears_the_handle_map():
    hci = _FakeHCI()
    mgr = IsoBroadcastManager(hci=hci)
    await _run_create_big(mgr, hci, num_bis=1, handles=[0x0E01])
    await mgr.on_hci_event(HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_TERMINATE_BIG_COMPLETE,
        subevent_parameters=b"\x00\x13",
    ))
    assert mgr.bis_handles == {}
    with pytest.raises(KeyError):
        await mgr.bis_broadcast(0, b"\x00")
