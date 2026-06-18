import argparse
import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest

from pybluehost.cli.app._ble_peripheral import start_connectable_advertising, start_directed_advertising
from pybluehost.cli.app.ble_adv_direct import (
    _build_ble_adv_direct_stack_config,
    _ble_adv_direct_main,
    register_ble_adv_direct_command,
)
from pybluehost.ble.smp import BondInfo
from pybluehost.core.address import AddressType, BDAddress
from pybluehost.hci.constants import (
    ErrorCode,
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_ADVERTISING_DATA,
    HCI_LE_SET_ADVERTISING_PARAMS,
    HCI_LE_SET_SCAN_RESPONSE_DATA,
)
from pybluehost.hci.packets import HCI_Command_Complete_Event
from pybluehost.stack import StackConnectionEvent


class FakeHCI:
    def __init__(self):
        self.commands = []
        self.status_by_opcode = {}

    async def send_command(self, cmd):
        self.commands.append(cmd)
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=cmd.opcode,
            return_parameters=bytes([self.status_by_opcode.get(cmd.opcode, ErrorCode.SUCCESS)]),
        )


class FakeAdvertiser:
    def __init__(self):
        self.started = []
        self.stopped = 0

    async def start(self, config, ad_data, scan_rsp_data=None):
        self.started.append((config, ad_data, scan_rsp_data))

    async def stop(self):
        self.stopped += 1


class FakeGap:
    def __init__(self):
        self.ble_advertiser = FakeAdvertiser()


class FakeSMP:
    def __init__(self):
        self._peer_addrs = {}
        self.security_requests = []

    async def request_security(self, handle, auth_req=0x01):
        self.security_requests.append((handle, auth_req))


class FakeStack:
    def __init__(self):
        from pybluehost.ble.gatt import GATTServer

        self._hci = FakeHCI()
        self._smp = FakeSMP()
        self.gap = FakeGap()
        self.gatt_server = GATTServer()
        self.local_address = "00:11:22:33:44:55"
        self.handlers = []
        self._config = SimpleNamespace(bond_storage=None)

    def on_connection_event(self, handler):
        self.handlers.append(handler)

    @property
    def hci(self):
        return self._hci

    @property
    def smp(self):
        return self._smp

    def emit(self, event):
        for handler in list(self.handlers):
            handler(event)


async def test_start_directed_advertising_clears_data_and_sets_legacy_params():
    hci = FakeHCI()

    await start_directed_advertising(
        hci,
        peer_address="38:6F:6B:A5:E8:20",
        peer_address_type="public",
        own_address_type="public",
        duty="low",
        interval_ms=100.0,
    )

    opcodes = [cmd.opcode for cmd in hci.commands]
    assert opcodes == [
        HCI_LE_SET_ADVERTISE_ENABLE,
        HCI_LE_SET_ADVERTISING_DATA,
        HCI_LE_SET_SCAN_RESPONSE_DATA,
        HCI_LE_SET_ADVERTISING_PARAMS,
        HCI_LE_SET_ADVERTISE_ENABLE,
    ]
    assert hci.commands[0].parameters == b"\x00"
    assert hci.commands[1].parameters == bytes(32)
    assert hci.commands[2].parameters == bytes(32)

    params = hci.commands[3].parameters
    assert params[4] == 0x04  # low-duty ADV_DIRECT_IND
    assert params[5] == 0x00  # own public
    assert params[6] == 0x00  # peer public
    assert params[7:13] == bytes.fromhex("20e8a56b6f38")
    assert hci.commands[4].parameters == b"\x01"


async def test_start_directed_advertising_supports_high_duty_random_target():
    hci = FakeHCI()

    await start_directed_advertising(
        hci,
        peer_address="D2:10:FA:45:68:46",
        peer_address_type="random",
        own_address_type="random",
        duty="high",
    )

    params = next(cmd.parameters for cmd in hci.commands if cmd.opcode == HCI_LE_SET_ADVERTISING_PARAMS)
    assert params[4] == 0x01  # high-duty ADV_DIRECT_IND
    assert params[5] == 0x01  # own random
    assert params[6] == 0x01  # peer random
    assert params[7:13] == bytes.fromhex("466845fa10d2")


async def test_start_directed_advertising_raises_on_hci_status_error():
    hci = FakeHCI()
    hci.status_by_opcode[HCI_LE_SET_ADVERTISING_PARAMS] = ErrorCode.INVALID_PARAMETERS

    with pytest.raises(RuntimeError, match="0x2006.*INVALID_PARAMETERS"):
        await start_directed_advertising(
            hci,
            peer_address="1C:3C:78:58:61:D8",
            peer_address_type="public",
            own_address_type="public",
            duty="low",
        )


def test_ble_adv_direct_accepts_trace_options():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_ble_adv_direct_command(subparsers)

    args = parser.parse_args(
        [
            "ble-adv-direct",
            "-t",
            "usb:vendor=csr",
            "--name",
            "DirectTest",
            "--peer-address",
            "38:6F:6B:A5:E8:20",
            "--peer-address-type",
            "public",
            "--own-address-type",
            "public",
            "--direct-duty",
            "high",
            "--direct-timeout",
            "5",
            "--bond-store",
            "bonds.json",
            "--hci-log",
            "--btsnoop",
            "direct.cfa",
        ]
    )

    assert args.transport == "usb:vendor=csr"
    assert args.name == "DirectTest"
    assert args.peer_address == "38:6F:6B:A5:E8:20"
    assert args.peer_address_type == "public"
    assert args.own_address_type == "public"
    assert args.direct_duty == "high"
    assert args.direct_timeout == 5.0
    assert args.bond_store == Path("bonds.json")
    assert args.hci_log is True
    assert args.btsnoop == Path("direct.cfa")


def test_ble_adv_direct_stack_config_uses_bond_store(tmp_path):
    path = tmp_path / "direct-bonds.json"

    config = _build_ble_adv_direct_stack_config(path)

    assert config.bond_storage is not None


async def test_ble_adv_direct_flow_switches_to_directed_after_disconnect():
    stack = FakeStack()
    stop = asyncio.Event()

    task = asyncio.create_task(
        _ble_adv_direct_main(
            stack,
            stop,
            name="DirectTest",
            peer_address="38:6F:6B:A5:E8:20",
            peer_address_type="public",
            own_address_type="public",
            direct_duty="low",
            direct_timeout=1.0,
        )
    )
    await asyncio.sleep(0)

    assert len(stack.gap.ble_advertiser.started) == 1
    stack.emit(StackConnectionEvent(state="connected", handle=0x0040))
    await asyncio.sleep(0)
    stack.emit(StackConnectionEvent(state="disconnected", handle=0x0040, reason="remote user"))
    await asyncio.sleep(0)
    stack.emit(StackConnectionEvent(state="connected", handle=0x0041))
    await asyncio.sleep(0)
    stop.set()
    await task

    assert stack.gap.ble_advertiser.stopped >= 1
    assert stack._smp.security_requests == [(0x0040, 0x01)]
    opcodes = [cmd.opcode for cmd in stack._hci.commands]
    assert HCI_LE_SET_ADVERTISING_PARAMS in opcodes
    directed_params = next(
        cmd.parameters
        for cmd in stack._hci.commands
        if cmd.opcode == HCI_LE_SET_ADVERTISING_PARAMS
    )
    assert directed_params[4] == 0x04


async def test_start_connectable_advertising_puts_name_in_primary_adv_data():
    stack = FakeStack()

    await start_connectable_advertising(
        stack,
        service_uuids=[0x180F, 0x180D],
        local_name="PyBlueHost",
    )

    _, ad_data, scan_rsp_data = stack.gap.ble_advertiser.started[0]
    assert ad_data.get_complete_local_name() == "PyBlueHost"
    assert scan_rsp_data.get_complete_local_name() == "PyBlueHost"


async def test_ble_adv_direct_flow_uses_peer_address_from_connection_event():
    stack = FakeStack()
    stop = asyncio.Event()
    peer = BDAddress.from_string("38:6F:6B:A5:E8:20")

    task = asyncio.create_task(
        _ble_adv_direct_main(
            stack,
            stop,
            name="DirectTest",
            peer_address=None,
            peer_address_type="public",
            own_address_type="public",
            direct_duty="low",
            direct_timeout=1.0,
        )
    )
    await asyncio.sleep(0)

    stack.emit(StackConnectionEvent(state="connected", handle=0x0040, peer_address=peer))
    await asyncio.sleep(0)
    stack._smp._peer_addrs.clear()
    stack.emit(StackConnectionEvent(state="disconnected", handle=0x0040, reason="remote user"))
    await asyncio.sleep(0)
    stack.emit(StackConnectionEvent(state="connected", handle=0x0041))
    await asyncio.sleep(0)
    stop.set()
    await task

    directed_params = next(
        cmd.parameters
        for cmd in stack._hci.commands
        if cmd.opcode == HCI_LE_SET_ADVERTISING_PARAMS
    )
    assert directed_params[7:13] == bytes.fromhex("20e8a56b6f38")


async def test_ble_adv_direct_prefers_bond_identity_address_for_directed_target():
    class FakeBondStorage:
        async def list_bonds(self):
            return [
                BondInfo(
                    peer_address=BDAddress.from_string("38:6F:6B:A5:E8:20", AddressType.PUBLIC),
                    address_type=AddressType.PUBLIC,
                    ltk=b"\x11" * 16,
                )
            ]

    stack = FakeStack()
    stack._config.bond_storage = FakeBondStorage()
    stop = asyncio.Event()
    rpa = BDAddress.from_string("74:73:C2:D0:07:8B", AddressType.RANDOM)

    task = asyncio.create_task(
        _ble_adv_direct_main(
            stack,
            stop,
            name="DirectTest",
            peer_address=None,
            peer_address_type="random",
            own_address_type="public",
            direct_duty="low",
            direct_timeout=1.0,
        )
    )
    await asyncio.sleep(0)

    stack.emit(StackConnectionEvent(state="connected", handle=0x0040, peer_address=rpa))
    await asyncio.sleep(0)
    stack.emit(StackConnectionEvent(state="disconnected", handle=0x0040, reason="remote user"))
    await asyncio.sleep(0)
    stack.emit(StackConnectionEvent(state="connected", handle=0x0041))
    await asyncio.sleep(0)
    stop.set()
    await task

    directed_params = next(
        cmd.parameters
        for cmd in stack._hci.commands
        if cmd.opcode == HCI_LE_SET_ADVERTISING_PARAMS
    )
    assert directed_params[6] == 0x00
    assert directed_params[7:13] == bytes.fromhex("20e8a56b6f38")
