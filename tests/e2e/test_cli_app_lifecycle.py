"""End-to-end coverage for the ``pybluehost app`` CLI namespace.

These tests exercise the command-level coroutines with real virtual stacks.
Unit tests still own argparse details; this module owns protocol-visible
behavior and a guard that every registered app command has E2E coverage.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import math
import os
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from pybluehost.ble.gap import ScanResult
from pybluehost.classic.sdp import SDPClient
from pybluehost.classic.spp import SPPClient
from pybluehost.cli.app import register_app_commands
from pybluehost.cli.app.a2dp_sink import _a2dp_sink_main
from pybluehost.cli.app.a2dp_source import _a2dp_source_main
from pybluehost.cli.app.avrcp_control import _avrcp_control_main
from pybluehost.cli.app.avrcp_target import _avrcp_target_main
from pybluehost.cli.app.ble_adv import _ble_adv_main
from pybluehost.cli.app.ble_adv_direct import _ble_adv_direct_main
from pybluehost.cli.app.ble_scan import _ble_scan_main
from pybluehost.cli.app.bridge import HCITransportBridge
from pybluehost.cli.app.classic_inquiry import _classic_inquiry_main
from pybluehost.cli.app.demo_headphone import _demo_headphone_main
from pybluehost.cli.app.demo_phone import _demo_phone_main
from pybluehost.cli.app.gatt_browser import _gatt_browser_run
from pybluehost.cli.app.gatt_server import _gatt_server_main
from pybluehost.cli.app.hfp_test import _hfp_test_main
from pybluehost.cli.app.hr_monitor import _hr_monitor_main
from pybluehost.cli.app.hsp_test import _hsp_test_main
from pybluehost.cli.app.mitm.cli import (
    build_relays_from_args,
    register_mitm_command,
)
from pybluehost.cli.app.sdp_browser import _sdp_browser_run
from pybluehost.cli.app.spp_echo import _spp_echo_main
from pybluehost.core.address import BDAddress
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.core.uuid import UUID16
from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.l2cap.constants import PSM_SDP
from pybluehost.transport.base import Transport, TransportInfo

from tests.e2e._helpers import (
    classic_discover_and_pair_jw,
    disconnect_classic_and_wait,
    disconnect_le_and_wait,
    e2e_timeout,
)


CLI_APP_E2E_COVERAGE: dict[str, str] = {
    "a2dp-sink": "test_a2dp_source_and_sink_cli_apps_write_wav",
    "a2dp-source": "test_a2dp_source_and_sink_cli_apps_write_wav",
    "avrcp-control": "test_avrcp_control_and_target_cli_apps_exchange_pass_through",
    "avrcp-target": "test_avrcp_control_and_target_cli_apps_exchange_pass_through",
    "ble-adv": "test_ble_adv_and_scan_cli_apps_exercise_gap",
    "ble-adv-direct": "test_ble_adv_direct_cli_app_reconnects_after_directed_phase",
    "ble-scan": "test_ble_adv_and_scan_cli_apps_exercise_gap",
    "bridge": "test_bridge_cli_app_tcp_round_trip_e2e",
    "classic-inquiry": "test_classic_inquiry_and_spp_echo_cli_apps_exchange_rfcomm",
    "demo-headphone": "test_demo_phone_and_headphone_cli_apps_connect_and_send_avrcp",
    "demo-phone": "test_demo_phone_and_headphone_cli_apps_connect_and_send_avrcp",
    "gatt-browser": "test_gatt_server_and_browser_cli_apps_discover_services",
    "gatt-server": "test_gatt_server_and_browser_cli_apps_discover_services",
    "hfp-test": "test_hfp_cli_app_hf_to_ag_wav_loopback",
    "hr-monitor": "test_hr_monitor_cli_app_updates_measurement",
    "hsp-test": "test_hsp_cli_app_hs_to_ag_wav_loopback",
    "mitm": "test_mitm_cli_app_builds_authorized_relay_specs",
    "pts-iut": "test_pts_iut_cli_app_action_layer_drives_gap",
    "pts-tester": "test_pts_tester_cli_app_starts_btp_tester_and_stops_cleanly",
    "sdp-browser": "test_sdp_browser_cli_app_queries_spp_echo_record",
    "spp-echo": "test_classic_inquiry_and_spp_echo_cli_apps_exchange_rfcomm",
}


def _registered_app_commands() -> set[str]:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_app_commands(subparsers)
    app_parser = subparsers.choices["app"]
    app_subparsers = next(
        action
        for action in app_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return set(app_subparsers.choices)


def test_registered_cli_app_commands_have_e2e_coverage() -> None:
    assert _registered_app_commands() == set(CLI_APP_E2E_COVERAGE)


async def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.01) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not reached before timeout")
        await asyncio.sleep(interval)


async def _stop_app_task(stop: asyncio.Event, task: asyncio.Task[None]) -> None:
    stop.set()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3.0)


def _make_stereo_wav(path: Path, *, sample_rate: int = 44100, secs: float = 0.25) -> None:
    n = int(sample_rate * secs)
    samples: list[int] = []
    for i in range(n):
        left = int(6000 * math.sin(2 * math.pi * 440 * i / sample_rate))
        right = int(6000 * math.sin(2 * math.pi * 660 * i / sample_rate))
        samples.extend([left, right])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _make_mono_wav(path: Path, *, sample_rate: int = 8000, secs: float = 0.8) -> None:
    n = int(sample_rate * secs)
    samples = [
        int(6000 * math.sin(2 * math.pi * 400 * i / sample_rate))
        for i in range(n)
    ]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{n}h", *samples))


def _wav_frames(path: Path) -> int:
    with wave.open(str(path), "rb") as w:
        return w.getnframes()


async def _attach_classic_link(stack_c, stack_p, transport_mode: str):
    if transport_mode != "virtual":
        return None
    link = VirtualClassicLink(
        central=stack_c._virtual_controller,
        peripheral=stack_p._virtual_controller,
        central_address=stack_c._local_address,
        peripheral_address=stack_p._local_address,
        page_timeout_seconds=0.5,
    )
    link.attach()
    return link


class RecordingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[bytes] = []
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True
        self.opened = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    @property
    def is_open(self) -> bool:
        return self.opened

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="test",
            description="recording transport",
            platform="test",
            details={},
        )

    async def emit(self, data: bytes) -> None:
        assert self._sink is not None
        await self._sink.on_transport_data(data)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ble_adv_and_scan_cli_apps_exercise_gap(stack, caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.cli.app.ble_scan")

    stop = asyncio.Event()
    task = asyncio.create_task(_ble_adv_main(stack, stop, name="PBH CLI ADV"))
    await _wait_until(lambda: stack.gap.ble_advertiser._active)
    assert stack.gap.ble_advertiser._active is True
    await _stop_app_task(stop, task)
    assert stack.gap.ble_advertiser._active is False

    stop = asyncio.Event()
    task = asyncio.create_task(_ble_scan_main(stack, stop))
    await _wait_until(lambda: stack.gap.ble_scanner._active)

    ad = AdvertisingData()
    ad.set_complete_local_name("PBH CLI PEER")
    await stack.gap.ble_scanner._on_advertising_report(
        ScanResult(
            address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"),
            rssi=-42,
            advertising_data=ad,
        )
    )
    await _wait_until(lambda: "PBH CLI PEER" in caplog.text)
    await _stop_app_task(stop, task)
    assert stack.gap.ble_scanner._active is False


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_gatt_server_and_browser_cli_apps_discover_services(
    stack, peer_stack, transport_mode, caplog,
):
    caplog.set_level(logging.INFO, logger="pybluehost.cli.app.gatt_browser")
    link = None
    stop = asyncio.Event()
    task = asyncio.create_task(_gatt_server_main(peer_stack, stop))
    try:
        await _wait_until(lambda: peer_stack.gap.ble_advertiser._active)
        assert peer_stack.gatt_server.find_characteristic_value_handle(UUID16(0x2A19)) is not None
        assert peer_stack.gatt_server.find_characteristic_value_handle(UUID16(0x2A37)) is not None

        if transport_mode == "virtual":
            link = VirtualLELink(
                central=stack._virtual_controller,
                peripheral=peer_stack._virtual_controller,
                central_address=stack._local_address,
                peripheral_address=peer_stack._local_address,
            )
            browser_task = asyncio.create_task(
                _gatt_browser_run(stack, asyncio.Event(), peer_stack._local_address)
            )
            await asyncio.sleep(0.05)
            await link.connect()
            await asyncio.wait_for(browser_task, timeout=5.0)
        else:
            await _gatt_browser_run(stack, asyncio.Event(), peer_stack._local_address)

        assert "0x180F" in caplog.text
        assert "0x180D" in caplog.text
    finally:
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()
        await _stop_app_task(stop, task)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_hr_monitor_cli_app_updates_measurement(stack):
    stop = asyncio.Event()
    task = asyncio.create_task(_hr_monitor_main(stack, stop, interval=0.01))
    try:
        await _wait_until(lambda: stack.gap.ble_advertiser._active)
        hr_handle = stack.gatt_server.find_characteristic_value_handle(UUID16(0x2A37))
        assert hr_handle is not None
        await _wait_until(lambda: stack.gatt_server.db.read(hr_handle)[:1] == b"\x00")
        bpm = stack.gatt_server.db.read(hr_handle)[1]
        assert 60 <= bpm <= 100
    finally:
        await _stop_app_task(stop, task)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ble_adv_direct_cli_app_reconnects_after_directed_phase(
    stack, peer_stack, transport_mode,
):
    if transport_mode != "virtual":
        pytest.skip("ble-adv-direct CLI E2E uses deterministic virtual reconnects")

    link = VirtualLELink(
        central=stack._virtual_controller,
        peripheral=peer_stack._virtual_controller,
        central_address=stack._local_address,
        peripheral_address=peer_stack._local_address,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(
        _ble_adv_direct_main(
            peer_stack,
            stop,
            name="PBH Direct",
            peer_address=str(stack._local_address),
            peer_address_type="public",
            own_address_type="public",
            direct_duty="low",
            direct_timeout=5.0,
            direct_interval_ms=100.0,
        )
    )
    first_handle = None
    second_handle = None
    try:
        await _wait_until(lambda: peer_stack.gap.ble_advertiser._active)
        connect_task = asyncio.create_task(stack.connect_gatt(peer_stack._local_address, timeout=5.0))
        await asyncio.sleep(0.05)
        await link.connect()
        client = await connect_task
        first_handle = client._connection_handle

        await link.disconnect()
        await asyncio.sleep(0.05)
        first_handle = None

        connect_task = asyncio.create_task(stack.connect_gatt(peer_stack._local_address, timeout=5.0))
        await asyncio.sleep(0.05)
        await link.connect()
        client = await connect_task
        second_handle = client._connection_handle
        assert second_handle is not None
        stop.set()
        await asyncio.wait_for(task, timeout=5.0)
    finally:
        if second_handle is not None:
            with contextlib.suppress(Exception):
                await disconnect_le_and_wait(stack, second_handle, timeout=2.0)
        if first_handle is not None:
            with contextlib.suppress(Exception):
                await disconnect_le_and_wait(stack, first_handle, timeout=2.0)
        with contextlib.suppress(Exception):
            await link.disconnect()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_classic_inquiry_and_spp_echo_cli_apps_exchange_rfcomm(
    stack, peer_stack, transport_mode, caplog,
):
    caplog.set_level(logging.INFO, logger="pybluehost.cli.app.classic_inquiry")
    link = await _attach_classic_link(stack, peer_stack, transport_mode)
    stop_spp = asyncio.Event()
    spp_task = asyncio.create_task(_spp_echo_main(peer_stack, stop_spp))
    stop_inquiry = asyncio.Event()
    inquiry_task = None
    handle = None
    spp_conn = None
    try:
        await _wait_until(lambda: getattr(peer_stack._virtual_controller, "_page_scan", True))
        inquiry_task = asyncio.create_task(_classic_inquiry_main(stack, stop_inquiry))
        await _wait_until(lambda: str(peer_stack._local_address) in caplog.text, timeout=3.0)

        handle = await classic_discover_and_pair_jw(
            stack,
            peer_stack._local_address,
            scan_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=10.0),
            pair_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=10.0),
        )
        sdp_chan = await stack.l2cap.connect_classic_channel(handle, psm=PSM_SDP)
        sdp_client = SDPClient(l2cap=sdp_chan)
        spp_client = SPPClient(rfcomm=stack.rfcomm, sdp_client=sdp_client)
        spp_conn = await spp_client.connect(target=handle)
        await spp_conn.send(b"cli spp echo")
        assert await asyncio.wait_for(spp_conn.recv(), timeout=2.0) == b"cli spp echo"
    finally:
        if spp_conn is not None:
            with contextlib.suppress(Exception):
                await spp_conn.close()
        if handle is not None:
            with contextlib.suppress(Exception):
                await disconnect_classic_and_wait(stack, handle, timeout=2.0)
        if inquiry_task is not None:
            await _stop_app_task(stop_inquiry, inquiry_task)
        await _stop_app_task(stop_spp, spp_task)
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sdp_browser_cli_app_queries_spp_echo_record(
    stack, peer_stack, transport_mode, caplog,
):
    caplog.set_level(logging.INFO, logger="pybluehost.cli.app.sdp_browser")
    link = await _attach_classic_link(stack, peer_stack, transport_mode)
    stop_spp = asyncio.Event()
    spp_task = asyncio.create_task(_spp_echo_main(peer_stack, stop_spp))
    try:
        await _wait_until(lambda: getattr(peer_stack._virtual_controller, "_page_scan", True))
        await _sdp_browser_run(
            stack,
            asyncio.Event(),
            peer_stack._local_address,
            0x1101,
            e2e_timeout(transport_mode, virtual=3.0, usb=10.0),
            0x03F0,
        )
        assert "ServiceClassIDList" in caplog.text
        assert "ProtocolDescriptorList" in caplog.text
    finally:
        await _stop_app_task(stop_spp, spp_task)
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_a2dp_source_and_sink_cli_apps_write_wav(
    stack, peer_stack, transport_mode, tmp_path,
):
    if transport_mode != "virtual":
        pytest.skip("A2DP CLI app E2E uses deterministic virtual classic link")

    link = await _attach_classic_link(stack, peer_stack, transport_mode)
    src_wav = tmp_path / "a2dp-src.wav"
    rx_wav = tmp_path / "a2dp-rx.wav"
    _make_stereo_wav(src_wav)

    stop_sink = asyncio.Event()
    sink_args = SimpleNamespace(output=str(rx_wav), device_index=None)
    sink_task = asyncio.create_task(_a2dp_sink_main(peer_stack, stop_sink, sink_args))
    try:
        await _wait_until(lambda: peer_stack._virtual_controller._page_scan)
        source_args = SimpleNamespace(
            target=str(peer_stack._local_address),
            play=str(src_wav),
            device_index=None,
        )
        await _a2dp_source_main(stack, asyncio.Event(), source_args)
    finally:
        await _stop_app_task(stop_sink, sink_task)
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()

    assert os.path.exists(rx_wav)
    assert _wav_frames(rx_wav) > 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_avrcp_control_and_target_cli_apps_exchange_pass_through(
    stack, peer_stack, transport_mode, caplog,
):
    if transport_mode != "virtual":
        pytest.skip("AVRCP CLI app E2E uses deterministic virtual classic link")

    caplog.set_level(logging.INFO, logger="pybluehost.cli.app.avrcp_target")
    link = await _attach_classic_link(stack, peer_stack, transport_mode)
    stop_target = asyncio.Event()
    target_task = asyncio.create_task(_avrcp_target_main(peer_stack, stop_target))
    try:
        await _wait_until(lambda: peer_stack._virtual_controller._page_scan)
        control_args = SimpleNamespace(
            target=str(peer_stack._local_address),
            cmd_action="pause",
        )
        await _avrcp_control_main(stack, asyncio.Event(), control_args)
        await _wait_until(lambda: "PAUSE pressed" in caplog.text, timeout=3.0)
    finally:
        await _stop_app_task(stop_target, target_task)
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_hfp_cli_app_hf_to_ag_wav_loopback(
    stack, peer_stack, transport_mode, tmp_path,
):
    if transport_mode != "virtual":
        pytest.skip("HFP CLI app E2E uses deterministic virtual classic link")

    link = await _attach_classic_link(stack, peer_stack, transport_mode)
    src_wav = tmp_path / "hfp-src.wav"
    rx_wav = tmp_path / "hfp-rx.wav"
    _make_mono_wav(src_wav)

    stop_ag = asyncio.Event()
    ag_args = SimpleNamespace(
        role="ag",
        output=str(rx_wav),
        speaker_device=None,
        wav=None,
        mic_device=None,
        out=None,
    )
    ag_task = asyncio.create_task(_hfp_test_main(peer_stack, stop_ag, ag_args))
    try:
        await _wait_until(lambda: peer_stack._virtual_controller._page_scan)
        hf_args = SimpleNamespace(
            role="hf",
            target=str(peer_stack._local_address),
            wav=str(src_wav),
            mic_device=None,
            out=None,
            speaker_device=None,
            output=None,
        )
        await _hfp_test_main(stack, asyncio.Event(), hf_args)
    finally:
        await _stop_app_task(stop_ag, ag_task)
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()

    assert os.path.exists(rx_wav)
    assert _wav_frames(rx_wav) > 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_hsp_cli_app_hs_to_ag_wav_loopback(
    stack, peer_stack, transport_mode, tmp_path,
):
    if transport_mode != "virtual":
        pytest.skip("HSP CLI app E2E uses deterministic virtual classic link")

    link = await _attach_classic_link(stack, peer_stack, transport_mode)
    src_wav = tmp_path / "hsp-src.wav"
    rx_wav = tmp_path / "hsp-rx.wav"
    _make_mono_wav(src_wav)

    stop_ag = asyncio.Event()
    ag_args = SimpleNamespace(
        role="ag",
        output=str(rx_wav),
        speaker_device=None,
        wav=None,
        mic_device=None,
        out=None,
    )
    ag_task = asyncio.create_task(_hsp_test_main(peer_stack, stop_ag, ag_args))
    try:
        await _wait_until(lambda: peer_stack._virtual_controller._page_scan)
        hs_args = SimpleNamespace(
            role="hs",
            target=str(peer_stack._local_address),
            wav=str(src_wav),
            mic_device=None,
            out=None,
            speaker_device=None,
            output=None,
        )
        await _hsp_test_main(stack, asyncio.Event(), hs_args)
    finally:
        await _stop_app_task(stop_ag, ag_task)
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()

    assert os.path.exists(rx_wav)
    assert _wav_frames(rx_wav) > 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_demo_phone_and_headphone_cli_apps_connect_and_send_avrcp(
    stack, peer_stack, transport_mode, tmp_path, caplog,
):
    if transport_mode != "virtual":
        pytest.skip("integrated demo CLI app E2E uses deterministic virtual classic link")

    caplog.set_level(logging.INFO, logger="pybluehost.cli.app.demo_phone")
    link = await _attach_classic_link(stack, peer_stack, transport_mode)
    music = tmp_path / "music.wav"
    received = tmp_path / "received.wav"
    _make_stereo_wav(music)

    stop_phone = asyncio.Event()
    phone_args = SimpleNamespace(
        wav=str(music),
        ring_after=None,
        caller="+15555550199",
    )
    phone_task = asyncio.create_task(_demo_phone_main(peer_stack, stop_phone, phone_args))
    stop_headphone = asyncio.Event()
    headphone_args = SimpleNamespace(
        target=str(peer_stack._local_address),
        output=str(received),
        avrcp_cmd="pause",
        avrcp_cmd_at=0.1,
        auto_answer=False,
        call_output=str(tmp_path / "call.wav"),
    )
    headphone_task = None
    try:
        await _wait_until(lambda: peer_stack._virtual_controller._page_scan)
        headphone_task = asyncio.create_task(
            _demo_headphone_main(stack, stop_headphone, headphone_args)
        )
        await _wait_until(lambda: "command from headphone: PAUSE" in caplog.text, timeout=8.0)
    finally:
        if headphone_task is not None:
            await _stop_app_task(stop_headphone, headphone_task)
        await _stop_app_task(stop_phone, phone_task)
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()

    assert os.path.exists(received)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bridge_cli_app_tcp_round_trip_e2e():
    backend = RecordingTransport()
    bridge = HCITransportBridge(backend, protocol="tcp", host="127.0.0.1", port=0)
    await bridge.start()
    try:
        host, port = bridge.listen_addr
        reader, writer = await asyncio.open_connection(host, port)
        command = bytes.fromhex("01 03 0c 00")
        event = bytes.fromhex("04 0e 04 01 03 0c 00")

        writer.write(command[:2])
        await writer.drain()
        await asyncio.sleep(0.02)
        assert backend.sent == []
        writer.write(command[2:])
        await writer.drain()
        await _wait_until(lambda: backend.sent == [command])

        await backend.emit(event)
        assert await reader.readexactly(len(event)) == event

        writer.close()
        await writer.wait_closed()
    finally:
        await bridge.close()

    assert backend.closed is True


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_pts_iut_cli_app_action_layer_drives_gap(stack):
    """The PTS IUT action layer drives a real virtual stack's GAP primitives.

    Guards that ``IutActions`` (shared by the Phase 1 REPL and the future
    Phase 2 BTP tester) stays wired to the current Stack/GAP API: construction
    registers a connection-event handler, and advertise/scan/status operate
    against the live virtual controller.
    """
    from pybluehost.pts.actions import IutActions

    actions = IutActions(stack)
    assert actions.status().connections == {}

    await actions.advertise()
    assert stack.gap.ble_advertiser._active is True
    await actions.stop_advertising()
    assert stack.gap.ble_advertiser._active is False

    await actions.scan()
    assert stack.gap.ble_scanner._active is True
    await actions.stop_scan()
    assert stack.gap.ble_scanner._active is False


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_pts_tester_cli_app_starts_btp_tester_and_stops_cleanly(stack):
    """BTP tester starts, binds a TCP port, and shuts down cleanly on stop."""
    from pybluehost.cli.app.pts_tester import _pts_tester_main

    stop = asyncio.Event()
    task = asyncio.create_task(_pts_tester_main(stack, stop, listen="127.0.0.1:0"))
    try:
        # Give it a moment to bind and enter the wait loop
        await asyncio.sleep(0.05)
        assert not task.done(), "pts-tester task should still be running"
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=3.0)


def test_mitm_cli_app_builds_authorized_relay_specs() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_mitm_command(subparsers)

    args = parser.parse_args(
        [
            "mitm",
            "--upstream",
            "virtual",
            "--downstream",
            "virtual",
            "--transport-mode",
            "both",
            "--target",
            "AA:BB:CC:DD:EE:FF",
        ]
    )
    specs = build_relays_from_args(args)

    assert args.cmd == "mitm"
    assert [spec.mode for spec in specs] == ["le", "bredr"]
