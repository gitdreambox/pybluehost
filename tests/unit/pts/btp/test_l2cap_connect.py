"""L2CAP BTP Connect handler (0x02) — upstream-aligned wire format."""
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.l2cap import LeCoCService


# ---- Fakes --------------------------------------------------------------

@dataclass
class _FakeChannel:
    cid: int = 0x0040
    _peer_cid: int = 0x0050


@dataclass
class _FakePeer:
    address: bytes
    @property
    def bytes(self): return self.address


@dataclass
class _ConnInfo:
    handle: int
    peer: _FakePeer
    transport: str = "le"


@dataclass
class _FakeSession:
    connections: dict


class _FakeL2CAPManager:
    def __init__(self):
        self.connect_calls = []
        self.next_channel = _FakeChannel()

    async def connect_le_coc_channel(self, *, handle, psm, mtu=512, mps=247,
                                      initial_credits=10, timeout=5.0):
        self.connect_calls.append(
            {"handle": handle, "psm": psm, "mtu": mtu, "mps": mps,
             "initial_credits": initial_credits, "timeout": timeout}
        )
        return self.next_channel


class _FakeStack:
    def __init__(self):
        self.l2cap = _FakeL2CAPManager()


class _FakeActions:
    def __init__(self, conns=None):
        self._stack = _FakeStack()
        self._session = _FakeSession(connections=conns or {})

    def status(self):
        return self._session


def _make_svc_with_peer(addr_bytes, conn_handle=0x000C):
    actions = _FakeActions(conns={
        conn_handle: _ConnInfo(handle=conn_handle, peer=_FakePeer(address=addr_bytes)),
    })
    return LeCoCService(actions=actions, tester=MagicMock()), actions


@pytest.mark.asyncio
async def test_connect_returns_chan_id_and_records_channel():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, actions = _make_svc_with_peer(addr)
    body = (
        bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr
        + (0x0080).to_bytes(2, "little")    # PSM
        + (512).to_bytes(2, "little")        # MTU
        + bytes([1])                         # Num
        + bytes([0])                         # Options (unused in P.8 v1)
    )
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Response: Num(u8) + chan_ids(u8 × Num)
    assert data[0] == 1
    chan_id = data[1]
    assert chan_id == 1   # first allocation
    # Service records the channel.
    assert chan_id in svc._channels
    # connect_le_coc_channel was called with the right args.
    call = actions._stack.l2cap.connect_calls[0]
    assert call["handle"] == 0x000C
    assert call["psm"] == 0x0080
    assert call["mtu"] == 512


@pytest.mark.asyncio
async def test_connect_short_body_fails():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, _ = _make_svc_with_peer(addr)
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=b"\x00\x01\x02",
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_connect_unknown_peer_fails():
    """Body addr doesn't match any active LE connection → FAILED."""
    svc, _ = _make_svc_with_peer(bytes.fromhex("AABBCCDDEEFF"))
    body = (
        bytes([0]) + bytes.fromhex("000000000000")
        + (0x0080).to_bytes(2, "little") + (512).to_bytes(2, "little")
        + bytes([1, 0])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_connect_multi_channel_unsupported_in_v1():
    """Num > 1 is upstream-valid but P.8 v1 only supports single-channel."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, _ = _make_svc_with_peer(addr)
    body = (
        bytes([0]) + addr + (0x0080).to_bytes(2, "little")
        + (512).to_bytes(2, "little")
        + bytes([3, 0])   # Num=3 (unsupported)
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_connect_manager_raises_returns_failed():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, actions = _make_svc_with_peer(addr)
    async def boom(**kwargs):
        raise RuntimeError("LE CoC connect failed: result=0x0002")
    actions._stack.l2cap.connect_le_coc_channel = boom
    body = (
        bytes([0]) + addr + (0x0080).to_bytes(2, "little")
        + (512).to_bytes(2, "little") + bytes([1, 0])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED
    # No channel registered after failure.
    assert svc._channels == {}
