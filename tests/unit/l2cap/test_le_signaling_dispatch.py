"""L2CAPManager LE signaling dispatcher — routes 0x06/0x07/0x14/0x15/0x16 PDUs."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.core.types import LinkType
from pybluehost.l2cap.constants import CID_LE_SIGNALING
from pybluehost.l2cap.le_signaling import (
    LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
    LEFlowControlCredit, DisconnectionRequest,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
    LE_SIG_LE_FLOW_CONTROL_CREDIT,
    LE_SIG_DISCONNECTION_REQUEST,
    encode_le_signaling,
)
from pybluehost.l2cap.manager import L2CAPManager


def _make_manager() -> L2CAPManager:
    hci = MagicMock()
    hci.send_acl_data = AsyncMock()
    return L2CAPManager(hci=hci)


def test_manager_init_adds_le_state():
    m = _make_manager()
    assert m._le_listeners == {}
    assert m._pending_le_connect == {}
    assert m._next_le_signaling_id == 1
    # LE dynamic CID range per Core Spec Vol 3 Part A §2.1 starts at 0x0040.
    assert m._next_le_cid == 0x0040
    assert m._le_channels == {}


def test_allocate_le_cid_increments():
    m = _make_manager()
    a = m._allocate_le_cid()
    b = m._allocate_le_cid()
    assert a == 0x0040
    assert b == 0x0041
    assert m._next_le_cid == 0x0042


def test_next_le_signaling_id_wraps_after_0xFF():
    m = _make_manager()
    m._next_le_signaling_id = 0xFF
    assert m._next_le_signaling_id_value() == 0xFF
    # After consume, wraps to 1 (not 0 — 0 reserved).
    assert m._next_le_signaling_id_value() == 0x01


@pytest.mark.asyncio
async def test_on_connection_wires_le_signaling_handler():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    # Events bound: on_data callback should be set to dispatch into _on_le_signaling.
    assert sig_ch._events is not None
    assert sig_ch._events.on_data is not None


@pytest.mark.asyncio
async def test_le_signaling_response_resolves_pending_future():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    fut = asyncio.get_event_loop().create_future()
    m._pending_le_connect[0x05] = fut

    body = LECreditBasedConnectionResponse(
        dcid=0x0050, mtu=247, mps=247, initial_credits=5, result=0x0000,
    ).encode()
    pdu = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, 0x05, body)

    await m._on_le_signaling(handle=0x000C, data=pdu)

    assert fut.done()
    resp = fut.result()
    assert resp.dcid == 0x0050
    assert resp.result == 0x0000
    assert 0x05 not in m._pending_le_connect


@pytest.mark.asyncio
async def test_le_signaling_credit_pdu_dispatches_to_channel():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    # Register a fake channel whose _peer_cid matches the credit PDU's cid.
    fake_channel = MagicMock()
    fake_channel._peer_cid = 0x0060
    fake_channel.add_credits = MagicMock()
    m._le_channels[0x0042] = fake_channel

    body = LEFlowControlCredit(cid=0x0060, credits=7).encode()
    pdu = encode_le_signaling(LE_SIG_LE_FLOW_CONTROL_CREDIT, 0x06, body)

    await m._on_le_signaling(handle=0x000C, data=pdu)

    fake_channel.add_credits.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_le_signaling_request_routed_to_incoming_handler(monkeypatch):
    """Incoming LE_CREDIT_BASED_CONNECTION_REQUEST is dispatched to
    `_handle_incoming_le_coc_request`. T2 makes this a no-op stub so this test
    just confirms the dispatcher routes — T4 will replace the stub."""
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    called = {}
    async def fake_handler(handle, ident, req):
        called["args"] = (handle, ident, req)
    monkeypatch.setattr(m, "_handle_incoming_le_coc_request", fake_handler)

    body = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0040, mtu=512, mps=251, initial_credits=10,
    ).encode()
    pdu = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x07, body)

    await m._on_le_signaling(handle=0x000C, data=pdu)

    assert called["args"][0] == 0x000C
    assert called["args"][1] == 0x07
    assert called["args"][2].le_psm == 0x0080


@pytest.mark.asyncio
async def test_send_le_signaling_writes_to_signaling_channel():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    await m._send_le_signaling(
        handle=0x000C, code=LE_SIG_LE_FLOW_CONTROL_CREDIT, ident=0x08,
        payload=LEFlowControlCredit(cid=0x0040, credits=3).encode(),
    )

    sig_ch.send.assert_awaited_once()
    sent = sig_ch.send.await_args.args[0]
    # First byte = code, second = ident.
    assert sent[0] == LE_SIG_LE_FLOW_CONTROL_CREDIT
    assert sent[1] == 0x08


@pytest.mark.asyncio
async def test_conn_param_update_request_accepted_and_applied():
    """PTS GAP/CONN/CPUP/BV-04/05: a peripheral's Connection Parameter Update
    Request (0x12) must be answered with 0x13 accept AND applied via HCI
    LE_Connection_Update so the link actually moves to the new params."""
    import struct

    from pybluehost.hci.constants import HCI_LE_CONNECTION_UPDATE
    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m = _make_manager()
    m._hci.send_command = AsyncMock()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    # Matches the on-air capture: itvl_min=8, itvl_max=0xaa, latency=0, timeout=0x800.
    req_payload = struct.pack("<HHHH", 0x0008, 0x00AA, 0x0000, 0x0800)
    pdu = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST, 0x01, req_payload
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)

    # 1) 0x13 response with the same identifier and result=accepted(0x0000).
    sig_ch.send.assert_awaited_once()
    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE
    assert sent[1] == 0x01
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0000

    # 2) HCI LE_Connection_Update carries the negotiated params on this handle.
    m._hci.send_command.assert_awaited_once()
    cmd = m._hci.send_command.await_args.args[0]
    assert cmd.opcode == HCI_LE_CONNECTION_UPDATE
    assert cmd.parameters == struct.pack(
        "<HHHHHHH", 0x000C, 0x0008, 0x00AA, 0x0000, 0x0800, 0x0000, 0x0000
    )


@pytest.mark.asyncio
async def test_conn_param_update_request_malformed_rejected():
    """A truncated 0x12 payload is rejected (result=0x0001), no HCI update sent."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m = _make_manager()
    m._hci.send_command = AsyncMock()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    pdu = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST, 0x02, b"\x08\x00"
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)

    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0001
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_conn_param_update_request_rejects_latency_above_500():
    """L2CAP/LE/CPU/BI-01: a CPU Request whose Latency exceeds 500 (the
    TGAP(conn_param_latency) ceiling) must be answered result=0x0001 (rejected)
    and must NOT be applied to the link."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m = _make_manager()
    m._hci.send_command = AsyncMock()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    # The BI-01 stimulus: Latency = 512 (> 500).
    req_payload = struct.pack("<HHHH", 0x0008, 0x00AA, 0x0200, 0x0800)
    pdu = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST, 0x03, req_payload
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)

    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0001
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def _cpu_reject_case(req_payload: bytes) -> tuple[L2CAPManager, MagicMock]:
    """Shared harness for the CPUP/BV-05 invalid-parameter cases: feed a 0x12
    request, return (manager, signaling-channel mock) after dispatch."""
    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
    )

    m = _make_manager()
    m._hci.send_command = AsyncMock()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    pdu = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST, 0x05, req_payload
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)
    return m, sig_ch


@pytest.mark.asyncio
async def test_conn_param_update_request_rejects_interval_below_core_min():
    """GAP/CONN/CPUP/BV-05-C: the Lower Tester sends a request built from the
    TSPX_iut_invalid_connection_interval_* IXITs. An interval below the Core
    range floor (0x0006 = 7.5 ms, Vol 6 Part B §4.5.3) must be answered
    result=0x0001 (rejected) and must NOT touch the link."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m, sig_ch = await _cpu_reject_case(struct.pack("<HHHH", 0x0001, 0x00AA, 0, 0x0800))
    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0001
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_conn_param_update_request_rejects_interval_above_core_max():
    """CPUP/BV-05: an interval above 0x0C80 (4000 ms) is invalid → 0x0001."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m, sig_ch = await _cpu_reject_case(struct.pack("<HHHH", 0x0008, 0x0C81, 0, 0x0800))
    sent = sig_ch.send.await_args.args[0]
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0001
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_conn_param_update_request_rejects_interval_max_below_min():
    """CPUP/BV-05: itvl_max < itvl_min is a malformed window → 0x0001."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m, sig_ch = await _cpu_reject_case(struct.pack("<HHHH", 0x00AA, 0x0008, 0, 0x0800))
    sent = sig_ch.send.await_args.args[0]
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0001
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_conn_param_update_request_rejects_timeout_below_core_min():
    """CPUP/BV-05: a Supervision Timeout below 0x000A (100 ms) is invalid → 0x0001."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m, sig_ch = await _cpu_reject_case(struct.pack("<HHHH", 0x0008, 0x00AA, 0, 0x0009))
    sent = sig_ch.send.await_args.args[0]
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0001
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_conn_param_update_request_rejects_timeout_relation_violation():
    """CPUP/BV-05: §4.20 requires the Supervision Timeout to exceed
    (1 + Latency) × Conn_Interval_Max — in HCI units, timeout*4 must exceed
    (1+latency)*interval_max*2 (zephyr bt_le_conn_param_valid). Violation → 0x0001."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    # All fields individually in range, but 11*4=44 < (1+499)*8*2=8000.
    m, sig_ch = await _cpu_reject_case(struct.pack("<HHHH", 0x0008, 0x0008, 499, 0x000B))
    sent = sig_ch.send.await_args.args[0]
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0001
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_conn_param_update_request_still_accepts_boundary_values():
    """The validity floor must not swallow legal edge params: latency=500 is the
    TGAP(conn_param_latency) ceiling (GAP.TS treats 500 as acceptable) and the
    timeout relation holds with slack → accepted AND applied."""
    import struct

    from pybluehost.hci.constants import HCI_LE_CONNECTION_UPDATE

    # 1504*4=6016 > (1+500)*6*2=6012.
    m, sig_ch = await _cpu_reject_case(struct.pack("<HHHH", 0x0006, 0x0006, 500, 1504))
    sent = sig_ch.send.await_args.args[0]
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0000
    m._hci.send_command.assert_awaited_once()
    cmd = m._hci.send_command.await_args.args[0]
    assert cmd.opcode == HCI_LE_CONNECTION_UPDATE


@pytest.mark.asyncio
async def test_conn_param_update_request_as_peripheral_sends_command_reject():
    """L2CAP/LE/CPU/BI-02: the CPU procedure is peripheral→central only. When we
    are the PERIPHERAL and receive a CPU Request, it is an unsupported command in
    that direction — answer with COMMAND_REJECT_RSP reason 0x0000 (Command not
    understood), not a 0x13 response."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD,
        LE_SIG_COMMAND_REJECT,
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
    )

    m = _make_manager()
    m._hci.send_command = AsyncMock()
    m.set_le_role_provider(lambda handle: 0x01)  # 0x01 = peripheral
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    req_payload = struct.pack("<HHHH", 0x0008, 0x00AA, 0x0200, 0x0800)
    pdu = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST, 0x04, req_payload
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)

    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == LE_SIG_COMMAND_REJECT
    assert sent[1] == 0x04
    assert struct.unpack_from("<H", sent, 4)[0] == LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD
    m._hci.send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_signaling_code_gets_command_reject():
    """L2CAP/LE/REJ/BI-02: an RFU/unsupported LE signaling code must be answered
    with COMMAND_REJECT_RSP reason 0x0000 (Command not understood) and NO Reason
    Data field. Silence makes PTS run to its time guard."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD,
        LE_SIG_COMMAND_REJECT,
        encode_le_signaling,
    )

    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    # 0x1F is RFU (Table 4.26 lists 0x1B-0xFF as reserved for LE).
    pdu = encode_le_signaling(0x1F, 0x07, b"\xaa\xbb")
    await m._on_le_signaling(handle=0x000C, data=pdu)

    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == LE_SIG_COMMAND_REJECT
    assert sent[1] == 0x07
    # Payload is exactly the 2-byte reason — no Reason Data field.
    assert struct.unpack_from("<H", sent, 4)[0] == LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD
    assert len(sent) == 6


@pytest.mark.asyncio
async def test_request_le_conn_param_update_sends_0x12_and_resolves_on_0x13():
    """L2CAP/LE/CPU/BV-01-C: acting as the peripheral, we transmit
    L2CAP_CONNECTION_PARAMETER_UPDATE_REQ on the LE signaling channel (CID=5)
    and complete once the central answers 0x13."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sent_pdus: list[bytes] = []

    async def _capture(data):
        sent_pdus.append(bytes(data))

    sig_ch.send = _capture

    task = asyncio.create_task(m.request_le_conn_param_update(
        handle=0x000C, itvl_min=0x0008, itvl_max=0x00AA, latency=0x0000,
        timeout=0x0800,
    ))
    await asyncio.sleep(0.01)  # let the request reach the wire
    assert sent_pdus, "the CPU Request must be transmitted before we wait"

    req = sent_pdus[0]
    assert req[0] == LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST
    assert req[1] != 0x00  # a real identifier (0 is reserved)
    assert req[4:] == struct.pack("<HHHH", 0x0008, 0x00AA, 0x0000, 0x0800)

    resp = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE, req[1],
        struct.pack("<H", 0x0000),
    )
    await m._on_le_signaling(handle=0x000C, data=resp)

    assert await asyncio.wait_for(task, timeout=1.0) == 0x0000
    assert m._pending_le_cpu == {}, "the pending entry must be consumed"


@pytest.mark.asyncio
async def test_request_le_conn_param_update_propagates_rejection():
    """The central may reject (result=0x0001); the caller must see it rather
    than a silent success."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sent_pdus: list[bytes] = []

    async def _capture(data):
        sent_pdus.append(bytes(data))

    sig_ch.send = _capture

    task = asyncio.create_task(m.request_le_conn_param_update(
        handle=0x000C, itvl_min=0x0008, itvl_max=0x00AA, latency=0x0000,
        timeout=0x0800,
    ))
    await asyncio.sleep(0.01)

    resp = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE, sent_pdus[0][1],
        struct.pack("<H", 0x0001),
    )
    await m._on_le_signaling(handle=0x000C, data=resp)

    assert await asyncio.wait_for(task, timeout=1.0) == 0x0001


@pytest.mark.asyncio
async def test_unsolicited_conn_param_update_response_is_ignored():
    """A 0x13 with no matching pending request must not raise (the ACL read
    task would swallow the exception and the peer would hang)."""
    import struct

    from pybluehost.l2cap.le_signaling import (
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
    )

    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    pdu = encode_le_signaling(
        LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE, 0x42,
        struct.pack("<H", 0x0000),
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)
    assert m._pending_le_cpu == {}


# ---------------------------------------------------------------------------
# Malformed C-frames (L2CAP.TS 4.4.1.4 / 4.4.1.6 — COS/CED/BI-13/16/17)
# ---------------------------------------------------------------------------

def _coc_request_body() -> bytes:
    return LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0040, mtu=64, mps=64, initial_credits=2,
    ).encode()


async def _signaling_capture():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    return m, sig_ch


@pytest.mark.asyncio
async def test_extra_trailing_octet_after_a_valid_command_is_rejected():
    """COS/CED/BI-13: the command header declares Data Length 10 but the PDU
    carries 11 octets (an extra zero). Accepting the request is the failure
    this test exists to prevent — the LT fails the case on a valid-looking
    L2CAP_LE_CREDIT_BASED_CONNECTION_RSP to a malformed C-frame."""
    import struct

    m, sig_ch = await _signaling_capture()
    pdu = struct.pack("<BBH", LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 1, 10) \
        + _coc_request_body() + b"\x00"

    await m._on_le_signaling_safe(handle=0x000C, data=pdu)

    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == 0x01, "COMMAND_REJECT_RSP expected"
    assert struct.unpack_from("<H", sent, 4)[0] == 0x0000
    assert m._le_channels == {}, "no channel may be created from a malformed PDU"


@pytest.mark.asyncio
async def test_truncated_second_command_rejects_the_whole_pdu():
    """COS/CED/BI-16: a valid connection request followed by a second command
    whose declared Data Length exceeds the octets present. The first command
    must NOT be acted on either — the C-frame as a whole is malformed."""
    import struct

    m, sig_ch = await _signaling_capture()
    first = encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 1, _coc_request_body())
    second = struct.pack("<BBH", LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 2, 11) \
        + _coc_request_body()

    await m._on_le_signaling_safe(handle=0x000C, data=first + second)

    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == 0x01, "COMMAND_REJECT_RSP expected"
    assert m._le_channels == {}


@pytest.mark.asyncio
async def test_truncated_disconnection_request_as_second_command_is_rejected():
    """COS/CED/BI-17: same shape with a Disconnection Request declaring 5
    octets while only 4 are present."""
    import struct

    m, sig_ch = await _signaling_capture()
    first = encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 1, _coc_request_body())
    second = struct.pack("<BBH", LE_SIG_DISCONNECTION_REQUEST, 2, 5) + b"\x40\x00\x40\x00"

    await m._on_le_signaling_safe(handle=0x000C, data=first + second)

    sent = sig_ch.send.await_args.args[0]
    assert sent[0] == 0x01, "COMMAND_REJECT_RSP expected"
    assert m._le_channels == {}


@pytest.mark.asyncio
async def test_two_wellformed_commands_in_one_pdu_are_both_dispatched():
    """Positive guard: L2CAP permits several signaling commands per C-frame,
    so a well-formed pair must not be rejected (and the second command must
    not be silently dropped either)."""
    m, sig_ch = await _signaling_capture()
    m.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None)
    first = encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 1, _coc_request_body())
    second = encode_le_signaling(
        LE_SIG_DISCONNECTION_REQUEST, 2,
        DisconnectionRequest(dcid=0x0040, scid=0x0040).encode())

    await m._on_le_signaling_safe(handle=0x000C, data=first + second)

    from pybluehost.l2cap.le_signaling import LE_SIG_DISCONNECTION_RESPONSE

    codes = [c.args[0][0] for c in sig_ch.send.await_args_list]
    assert codes == [LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
                     LE_SIG_DISCONNECTION_RESPONSE]
