"""Two-device baseline throughput — REAL HARDWARE ONLY.

Run as::

    uv run pytest tests/hardware/test_throughput_real.py \\
        --transport=usb --transport-peer=usb -v -s

Measures:

- BLE LE CoC throughput @ LE 1M and LE 2M PHYs
- SPP / RFCOMM throughput @ EDR 2-DH only and EDR 3-DH only

Both directions: uplink (central→peripheral) and downlink (peripheral→central).

Output:

- Each cell prints a ``[THROUGHPUT]`` line to stdout (use ``-s``).
- Each cell records a junit XML property
  ``throughput_<profile>_<rate>_<direction>_mbps`` via ``record_property``.

Operator captures results into ``docs/hardware/throughput-baseline.md``
(see ``docs/THROUGHPUT_VERIFY.md`` for the runbook + adapter requirements).

Skips gracefully if the adapter or peer rejects the requested PHY / EDR
constraint — that's a real hardware finding, not a code defect.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from pybluehost.classic.spp import SPPClient, SPPConnection, SPPService
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.hci.constants import LEPhy, LEPhyMask
from pybluehost.l2cap.channel import SimpleChannelEvents

from tests.e2e._classic_test_service import SPP_SERVER_CHANNEL, SPP_SERVICE_NAME


pytestmark = pytest.mark.real_hardware_only(transport="usb")


_DURATION_S = 5.0
_BLE_CHUNK_SIZE = 480
_SPP_CHUNK_SIZE = 512
_THROUGHPUT_PSM = 0x0080


def _print_and_record(record_property, *, profile, rate, direction,
                      received, elapsed_s):
    mbps = (received * 8 / elapsed_s) / 1_000_000 if elapsed_s > 0 else 0
    print(
        f"[THROUGHPUT] profile={profile} rate={rate} direction={direction} "
        f"received={received} bytes in {elapsed_s:.2f}s → {mbps:.2f} Mbps",
    )
    record_property(
        f"throughput_{profile}_{rate}_{direction}_mbps", f"{mbps:.3f}",
    )


async def _pump_for(send_fn, payload: bytes, duration_s: float) -> tuple[int, float]:
    """Send ``payload`` repeatedly for ``duration_s`` seconds.

    Returns ``(bytes_sent, elapsed_seconds)``. Flow control on the underlying
    channel (L2CAP credits for LE CoC, RFCOMM FCTS for SPP) naturally
    backpressures the loop so the rate maps to the link's actual capacity.
    """
    start = time.monotonic()
    deadline = start + duration_s
    total = 0
    while time.monotonic() < deadline:
        await send_fn(payload)
        total += len(payload)
    return total, time.monotonic() - start


# ---------------------------------------------------------------------------
# BLE LE CoC throughput
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["uplink", "downlink"])
@pytest.mark.parametrize("rate", ["1M", "2M"])
async def test_ble_le_coc_throughput(
    stack, peer_stack, rate, direction, record_property,
):
    central, peripheral = stack, peer_stack
    peer_addr = peripheral._local_address

    received = [0]
    incoming: dict = {}

    def on_incoming(ch):
        incoming["ch"] = ch
        ch.set_events(SimpleChannelEvents(
            on_data=lambda data: received.__setitem__(0, received[0] + len(data)),
        ))

    peripheral.l2cap.listen_le_coc_channel(psm=_THROUGHPUT_PSM, handler=on_incoming)
    await peripheral.gap.ble_advertiser.start(ad_data=AdvertisingData([]))

    handle: int | None = None
    c_ch = None
    try:
        # Establish LE link.
        client = await central.connect_gatt(peer_addr, timeout=15.0)
        handle = client._connection_handle

        # Switch PHY on the active link.
        target_mask = LEPhyMask.LE_2M if rate == "2M" else LEPhyMask.LE_1M
        target_val = LEPhy.LE_2M if rate == "2M" else LEPhy.LE_1M
        phy_res = await central.gap.ble_connections.set_phy(
            handle, tx_phys=target_mask, rx_phys=target_mask,
        )
        if phy_res.status != 0:
            pytest.skip(f"set_phy returned status 0x{phy_res.status:02X}")
        if phy_res.tx_phy != target_val or phy_res.rx_phy != target_val:
            pytest.skip(
                f"Adapter or peer negotiated PHY tx={phy_res.tx_phy:#x}/"
                f"rx={phy_res.rx_phy:#x}, wanted {target_val:#x} both",
            )

        # Open LE CoC.
        c_ch = await central.l2cap.connect_le_coc_channel(
            handle=handle, psm=_THROUGHPUT_PSM,
            mtu=512, mps=247, initial_credits=200, timeout=5.0,
        )
        for _ in range(50):
            if "ch" in incoming:
                break
            await asyncio.sleep(0.02)
        assert "ch" in incoming, "peripheral never accepted LE CoC"
        p_ch = incoming["ch"]

        # Pick sender; reset counter when downlink rewires it.
        if direction == "uplink":
            sender = c_ch
        else:
            received[0] = 0
            c_ch.set_events(SimpleChannelEvents(
                on_data=lambda data: received.__setitem__(0, received[0] + len(data)),
            ))
            sender = p_ch

        payload = bytes(_BLE_CHUNK_SIZE)
        _sent, elapsed = await _pump_for(sender.send, payload, _DURATION_S)
        await asyncio.sleep(0.5)  # drain in-flight credits before counting

        _print_and_record(
            record_property, profile="ble", rate=rate, direction=direction,
            received=received[0], elapsed_s=elapsed,
        )
        assert received[0] > 0, "no LE CoC data received — link likely failed"
    finally:
        try:
            if c_ch is not None:
                await central.l2cap.disconnect_le_coc_channel(c_ch)
        except Exception:
            pass
        try:
            if handle is not None:
                await central.gap.ble_connections.disconnect(handle)
        except Exception:
            pass
        try:
            await peripheral.gap.ble_advertiser.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SPP throughput
# ---------------------------------------------------------------------------

class _SPPCounter:
    """Peer-side SPP handler that counts incoming bytes; never echoes.

    Echo handlers measure round-trip rate (and halve the apparent uplink),
    which conflates the two directions. By NOT echoing, the test measures
    one-way throughput honestly.
    """

    def __init__(self):
        self.total = 0
        self.conn: SPPConnection | None = None
        self.connected_event = asyncio.Event()

    async def handler(self, conn: SPPConnection) -> None:
        self.conn = conn
        self.connected_event.set()
        try:
            while True:
                data = await conn.recv()
                if not data:
                    break
                self.total += len(data)
        except (asyncio.CancelledError, Exception):
            return


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["uplink", "downlink"])
@pytest.mark.parametrize("rate", ["2dh", "3dh"])
async def test_spp_throughput(
    stack, peer_stack, rate, direction, record_property,
):
    central, peripheral = stack, peer_stack
    peer_addr = peripheral._local_address

    counter = _SPPCounter()
    service = SPPService(rfcomm=peripheral._rfcomm, sdp=peripheral._sdp)
    service.on_connection(counter.handler)
    await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)
    await peripheral.gap.classic_discoverability.set_connectable(True)
    await peripheral.gap.classic_discoverability.set_discoverable(True)

    handle: int | None = None
    try:
        handle = await central.connect_classic(peer_addr, timeout=20.0)

        if rate == "2dh":
            pt_res = await central.gap.classic_connections.set_acl_packet_types(
                handle, allow_br=False, allow_2dh=True, allow_3dh=False,
            )
        else:
            pt_res = await central.gap.classic_connections.set_acl_packet_types(
                handle, allow_br=False, allow_2dh=False, allow_3dh=True,
            )
        if pt_res.status != 0:
            pytest.skip(
                f"Adapter rejected packet-type change: status 0x{pt_res.status:02X}",
            )

        spp_client = SPPClient(rfcomm=central._rfcomm, sdp=central._sdp)
        spp_conn = await spp_client.connect(target=handle)

        await asyncio.wait_for(counter.connected_event.wait(), timeout=5.0)
        assert counter.conn is not None

        payload = bytes(_SPP_CHUNK_SIZE)
        if direction == "uplink":
            _sent, elapsed = await _pump_for(spp_conn.send, payload, _DURATION_S)
            await asyncio.sleep(0.5)
            _print_and_record(
                record_property, profile="spp", rate=rate, direction=direction,
                received=counter.total, elapsed_s=elapsed,
            )
            assert counter.total > 0, "peer received no SPP data"
        else:
            # Peer pumps, central recv-counts. Run them concurrently.
            received_total = 0
            start = time.monotonic()
            deadline = start + _DURATION_S

            async def peer_pump():
                while time.monotonic() < deadline:
                    await counter.conn.send(payload)

            pump_task = asyncio.create_task(peer_pump())
            try:
                while time.monotonic() < deadline:
                    try:
                        data = await asyncio.wait_for(spp_conn.recv(), timeout=0.1)
                        received_total += len(data)
                    except asyncio.TimeoutError:
                        pass
            finally:
                pump_task.cancel()
                try:
                    await pump_task
                except (asyncio.CancelledError, Exception):
                    pass
            elapsed = time.monotonic() - start
            _print_and_record(
                record_property, profile="spp", rate=rate, direction=direction,
                received=received_total, elapsed_s=elapsed,
            )
            assert received_total > 0, "central received no SPP data"
    finally:
        try:
            if handle is not None:
                await central.gap.classic_connections.disconnect(handle)
        except Exception:
            pass
        try:
            await peripheral.gap.classic_discoverability.set_discoverable(False)
            await peripheral.gap.classic_discoverability.set_connectable(False)
        except Exception:
            pass
