# Remote HCI Information Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable Stack API that retrieves remote name, supported/extended features, and version/company information over HCI, then log it immediately after a Classic ACL connect in `app sdp-browser` without ever blocking SDP browsing.

**Architecture:** Keep HCI wire formats and completion-event parsers in a focused `pybluehost/hci/remote_info.py` module. Add a generic one-shot HCI event-listener hook to `HCIController`; `Stack` uses it to correlate the four completion events and returns a typed best-effort `RemoteDeviceInformation` snapshot. `sdp-browser` remains a thin formatter over that snapshot.

**Tech Stack:** Python 3.10+, asyncio, pytest / pytest-asyncio, existing HCI packet classes, `SIGDatabase`, `uv run pytest`.

---

## File Structure

| File | Responsibility |
|---|---|
| `pybluehost/hci/constants.py` | Add the three missing Link Control / Informational Parameters opcodes. |
| `pybluehost/hci/remote_info.py` | Create dataclasses, exact command builders, completion-event parsers, and `company_name` / version formatting. |
| `pybluehost/hci/controller.py` | Add a generic `on_hci_event_listener` registration hook and fan out raw events before existing command handling. |
| `pybluehost/stack.py` | Add a per-query event-wait helper, four query methods, and `read_remote_information()` snapshot orchestration. |
| `pybluehost/cli/app/sdp_browser.py` | Call the snapshot API after connect and log its fields before authentication. |
| `pybluehost/hci/virtual.py` | Support remote-information commands and emit virtual completion events. |
| `pybluehost/hci/virtual_classic_link.py` | Support the four commands on VirtualClassicLink so the Classic e2e path does not time out. |
| `tests/unit/hci/test_remote_info.py` | Test wire formats, event decoding, snapshots, and formatted company identity. |
| `tests/unit/hci/test_event_listener_api.py` | Test the removable raw-event subscription: events that never reach upstream, listener exceptions, removal, and async scheduling. |
| `tests/unit/test_stack_remote_info.py` | Create. Test Stack command/event correlation, order, timeouts, and best-effort continuation. |
| `tests/unit/hci/test_virtual_remote_info.py` | Create. Test VirtualController's four command handlers and synthetic completion events. |
| `tests/unit/cli/test_app_sdp_browser.py` | Test the CLI prelude and failure isolation. |
| `README.md` / `AGENTS.md` | Document the new Stack API and CLI behavior. |

## Task 1: HCI constants and typed remote-information protocol module

**Files:**
- Modify: `pybluehost/hci/constants.py:78-87`, `pybluehost/hci/constants.py:109-116`
- Create: `pybluehost/hci/remote_info.py`
- Create: `tests/unit/hci/test_remote_info.py`

- [ ] **Step 1: Write the failing constants and protocol tests**

Create `tests/unit/hci/test_remote_info.py` with this exact content:

```python
"""Tests for HCI remote-information commands and completion events."""
from __future__ import annotations

import struct

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_READ_REMOTE_EXTENDED_FEATURES,
    HCI_READ_REMOTE_SUPPORTED_FEATURES,
    HCI_READ_REMOTE_VERSION_INFORMATION,
    HCI_REMOTE_NAME_REQUEST,
    OGF,
    ogf_ocf,
)
from pybluehost.hci.packets import HCIEvent
from pybluehost.hci.remote_info import (
    RemoteDeviceInformation,
    RemoteExtendedFeatures,
    RemoteInformationError,
    RemoteName,
    RemoteSupportedFeatures,
    RemoteVersionInformation,
    build_read_remote_extended_features,
    build_read_remote_supported_features,
    build_read_remote_version_information,
    build_remote_name_request,
    company_name,
    parse_remote_extended_features_complete,
    parse_remote_name_request_complete,
    parse_remote_supported_features_complete,
    parse_remote_version_information_complete,
)


def test_remote_information_opcodes_match_core_spec():
    assert ogf_ocf(HCI_READ_REMOTE_SUPPORTED_FEATURES) == (OGF.LINK_CONTROL, 0x1B)
    assert ogf_ocf(HCI_READ_REMOTE_EXTENDED_FEATURES) == (OGF.LINK_CONTROL, 0x1C)
    assert ogf_ocf(HCI_READ_REMOTE_VERSION_INFORMATION) == (OGF.LINK_CONTROL, 0x1D)
    assert ogf_ocf(HCI_REMOTE_NAME_REQUEST) == (OGF.LINK_CONTROL, 0x19)


def test_remote_information_command_bodies_are_exact():
    peer = BDAddress.from_string("1A:8D:8D:1B:F5:6B")
    name_command = build_remote_name_request(peer)
    assert name_command.opcode == HCI_REMOTE_NAME_REQUEST
    assert name_command.parameters == bytes.fromhex("6bf51b8d8d1a01000000")

    supported = build_read_remote_supported_features(0x0042)
    assert supported.opcode == HCI_READ_REMOTE_SUPPORTED_FEATURES
    assert supported.parameters == b"\x42\x00"

    extended = build_read_remote_extended_features(0x0042, page_number=1)
    assert extended.opcode == HCI_READ_REMOTE_EXTENDED_FEATURES
    assert extended.parameters == b"\x42\x00\x01"

    version = build_read_remote_version_information(0x0042)
    assert version.opcode == HCI_READ_REMOTE_VERSION_INFORMATION
    assert version.parameters == b"\x42\x00"


def test_parse_remote_name_request_complete_decodes_nul_padded_name():
    peer = BDAddress.from_string("1A:8D:8D:1B:F5:6B")
    params = b"\x00" + peer.to_hci() + b"Remote Device".ljust(248, b"\x00")
    event = HCIEvent(event_code=int(EventCode.REMOTE_NAME_REQUEST_COMPLETE), parameters=params)

    parsed = parse_remote_name_request_complete(event, peer)

    assert isinstance(parsed, RemoteName)
    assert parsed.status == 0
    assert parsed.name == "Remote Device"


def test_parse_remote_name_rejects_wrong_address():
    event = HCIEvent(
        event_code=int(EventCode.REMOTE_NAME_REQUEST_COMPLETE),
        parameters=b"\x00" + bytes(6) + b"Name".ljust(248, b"\x00"),
    )
    with pytest.raises(RemoteInformationError, match="address"):
        parse_remote_name_request_complete(event, BDAddress.from_string("1A:8D:8D:1B:F5:6B"))


def test_parse_remote_supported_features_complete_decodes_handle_and_bitmap():
    params = b"\x00\x42\x00" + bytes.fromhex("ff59000800000000")
    event = HCIEvent(event_code=int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE), parameters=params)
    parsed = parse_remote_supported_features_complete(event, 0x0042)
    assert isinstance(parsed, RemoteSupportedFeatures)
    assert parsed.status == 0
    assert parsed.lmp_features.hex() == "ff59000800000000"


def test_parse_remote_extended_features_complete_decodes_page_fields():
    params = b"\x00\x42\x00\x01\x02" + bytes.fromhex("0000000000000000")
    event = HCIEvent(event_code=int(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE), parameters=params)
    parsed = parse_remote_extended_features_complete(event, 0x0042, page_number=1)
    assert isinstance(parsed, RemoteExtendedFeatures)
    assert parsed.status == 0
    assert parsed.page_number == 1
    assert parsed.max_page_number == 2
    assert parsed.extended_lmp_features == bytes(8)


def test_parse_remote_version_information_complete_decodes_company_id():
    payload = struct.pack("<BHH", 0x0C, 0x000F, 0x1234)
    params = b"\x00\x42\x00" + payload
    event = HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=params)
    parsed = parse_remote_version_information_complete(event, 0x0042)
    assert isinstance(parsed, RemoteVersionInformation)
    assert parsed.status == 0
    assert parsed.lmp_version == 0x0C
    assert parsed.company_id == 0x000F
    assert parsed.lmp_subversion == 0x1234
    assert company_name(0x000F) == "Broadcom Corporation"
    assert parsed.company == "Broadcom Corporation"


@pytest.mark.parametrize("event_code, parser", [
    (EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE, parse_remote_supported_features_complete),
    (EventCode.READ_REMOTE_VERSION_COMPLETE, parse_remote_version_information_complete),
])
def test_remote_information_parsers_reject_truncated_payloads(event_code, parser):
    event = HCIEvent(event_code=int(event_code), parameters=b"\x00\x42\x00")
    with pytest.raises(RemoteInformationError, match="truncated"):
        parser(event, 0x0042)


def test_remote_information_parsers_reject_wrong_handle():
    event = HCIEvent(
        event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE),
        parameters=b"\x00\x43\x00" + struct.pack("<BHH", 0x0C, 0x0002, 0x0003),
    )
    with pytest.raises(RemoteInformationError, match="handle"):
        parse_remote_version_information_complete(event, 0x0042)


def test_remote_device_snapshot_defaults_to_per_query_errors():
    snapshot = RemoteDeviceInformation(handle=0x0042)
    assert snapshot.remote_name is None
    assert snapshot.supported_features is None
    assert snapshot.extended_features is None
    assert snapshot.version_information is None
    assert snapshot.errors == {}
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
uv run pytest tests/unit/hci/test_remote_info.py -v
```

Expected: FAIL at collection with `ImportError: cannot import name 'HCI_READ_REMOTE_SUPPORTED_FEATURES'`.

- [ ] **Step 3: Add the three missing opcodes**

In `pybluehost/hci/constants.py`, add these exact lines inside the Link Control group immediately after `HCI_REMOTE_NAME_REQUEST = make_opcode(OGF.LINK_CONTROL, 0x19)`:

```python
HCI_READ_REMOTE_SUPPORTED_FEATURES = make_opcode(OGF.LINK_CONTROL, 0x1B)
HCI_READ_REMOTE_EXTENDED_FEATURES = make_opcode(OGF.LINK_CONTROL, 0x1C)
HCI_READ_REMOTE_VERSION_INFORMATION = make_opcode(OGF.LINK_CONTROL, 0x1D)
```

> **OCF correction (0x1B, not 0x0B):** OCF `0x0B` is already taken by `HCI_LINK_KEY_REQUEST_REPLY`. Per the Core Spec and the existing `SUPPORTED_COMMAND_NAMES` table (`(2,5) Read_Remote_Supported_Features` → OCF 0x1B), `Read_Remote_Supported_Features` is OCF **0x1B** (`opcode 0x041B`); `Read_Remote_Extended_Features` is OCF 0x1C; `Read_Remote_Version_Information` is OCF 0x1D.

Add `READ_REMOTE_EXTENDED_FEATURES_COMPLETE = 0x23` to the `EventCode` enum immediately after `CONNECTION_PACKET_TYPE_CHANGED = 0x1D`.

- [ ] **Step 4: Create the protocol module**

Create `pybluehost/hci/remote_info.py` with this exact content:

```python
"""Typed HCI remote-information commands and completion-event decoders.

Commands in this module follow Core Spec Vol 4 Part E §7.1. Completion
events are decoded from raw ``HCIEvent.parameters`` so both real controllers
and the virtual controller use the same wire layout.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_READ_REMOTE_EXTENDED_FEATURES,
    HCI_READ_REMOTE_SUPPORTED_FEATURES,
    HCI_READ_REMOTE_VERSION_INFORMATION,
    HCI_REMOTE_NAME_REQUEST,
)
from pybluehost.hci.packets import HCICommand, HCIEvent


class RemoteInformationError(ValueError):
    """A remote-information completion event does not match its request."""


@dataclass(frozen=True)
class RemoteName:
    status: int
    name: str


@dataclass(frozen=True)
class RemoteSupportedFeatures:
    status: int
    lmp_features: bytes


@dataclass(frozen=True)
class RemoteExtendedFeatures:
    status: int
    page_number: int
    max_page_number: int
    extended_lmp_features: bytes


@dataclass(frozen=True)
class RemoteVersionInformation:
    status: int
    lmp_version: int
    company_id: int
    lmp_subversion: int

    @property
    def company(self) -> str:
        return company_name(self.company_id)


@dataclass
class RemoteDeviceInformation:
    handle: int
    remote_name: RemoteName | None = None
    supported_features: RemoteSupportedFeatures | None = None
    extended_features: list[RemoteExtendedFeatures] = field(default_factory=list)
    version_information: RemoteVersionInformation | None = None
    errors: dict[str, str] = field(default_factory=dict)


def company_name(company_id: int) -> str:
    """Resolve a Bluetooth SIG Company Identifier to its assigned name."""
    from pybluehost.core.sig_db import SIGDatabase

    return SIGDatabase.get().company_name(company_id) or "Unknown"


def build_remote_name_request(peer: BDAddress) -> HCICommand:
    return HCICommand(
        opcode=HCI_REMOTE_NAME_REQUEST,
        parameters=peer.to_hci() + bytes([0x01, 0x00, 0x00, 0x00]),
    )


def build_read_remote_supported_features(handle: int) -> HCICommand:
    return HCICommand(
        opcode=HCI_READ_REMOTE_SUPPORTED_FEATURES,
        parameters=struct.pack("<H", handle),
    )


def build_read_remote_extended_features(handle: int, *, page_number: int) -> HCICommand:
    return HCICommand(
        opcode=HCI_READ_REMOTE_EXTENDED_FEATURES,
        parameters=struct.pack("<HB", handle, page_number),
    )


def build_read_remote_version_information(handle: int) -> HCICommand:
    return HCICommand(
        opcode=HCI_READ_REMOTE_VERSION_INFORMATION,
        parameters=struct.pack("<H", handle),
    )


def _validate_completion(event: HCIEvent, expected_code: int, *, name: str, min_length: int) -> None:
    if event.event_code != expected_code:
        raise RemoteInformationError(f"wrong {name} event code 0x{event.event_code:02X}")
    if len(event.parameters) < min_length:
        raise RemoteInformationError(f"truncated {name} completion")


def parse_remote_name_request_complete(event: HCIEvent, peer: BDAddress) -> RemoteName:
    _validate_completion(
        event, int(EventCode.REMOTE_NAME_REQUEST_COMPLETE),
        name="remote name", min_length=7,
    )
    params = event.parameters
    if params[1:7] != peer.to_hci():
        raise RemoteInformationError("remote name completion has a different address")
    return RemoteName(
        status=params[0],
        name=params[7:255].rstrip(b"\x00").decode("utf-8", errors="replace"),
    )


def parse_remote_supported_features_complete(event: HCIEvent, handle: int) -> RemoteSupportedFeatures:
    _validate_completion(
        event, int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE),
        name="remote supported features", min_length=11,
    )
    params = event.parameters
    peer_handle = struct.unpack_from("<H", params, 1)[0]
    if peer_handle != handle:
        raise RemoteInformationError("remote supported features completion has a different handle")
    return RemoteSupportedFeatures(status=params[0], lmp_features=bytes(params[3:11]))


def parse_remote_extended_features_complete(
    event: HCIEvent, handle: int, *, page_number: int,
) -> RemoteExtendedFeatures:
    _validate_completion(
        event, int(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE),
        name="remote extended features", min_length=13,
    )
    params = event.parameters
    peer_handle = struct.unpack_from("<H", params, 1)[0]
    if peer_handle != handle:
        raise RemoteInformationError("remote extended features completion has a different handle")
    return RemoteExtendedFeatures(
        status=params[0],
        page_number=params[3],
        max_page_number=params[4],
        extended_lmp_features=bytes(params[5:13]),
    )


def parse_remote_version_information_complete(
    event: HCIEvent, handle: int,
) -> RemoteVersionInformation:
    _validate_completion(
        event, int(EventCode.READ_REMOTE_VERSION_COMPLETE),
        name="remote version", min_length=8,
    )
    params = event.parameters
    peer_handle = struct.unpack_from("<H", params, 1)[0]
    if peer_handle != handle:
        raise RemoteInformationError("remote version completion has a different handle")
    # Core Vol 4 Part E §7.7.42: Status(1) + Connection_Handle(2) +
    # Version(1, LMP version) + Manufacturer_Name(2, Company_ID) + Subversion(2).
    # There is no HCI_Revision field in the remote variant.
    lmp_version, company_id, lmp_subversion = struct.unpack_from("<BHH", params, 3)
    return RemoteVersionInformation(
        status=params[0],
        lmp_version=lmp_version,
        company_id=company_id,
        lmp_subversion=lmp_subversion,
    )
```

- [ ] **Step 5: Run the protocol tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/hci/test_remote_info.py -v
```

Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/hci/constants.py pybluehost/hci/remote_info.py tests/unit/hci/test_remote_info.py
git commit -m "feat(hci): add remote information commands and decoders"
```

## Task 2: Generic controller event-listener hook

**Files:**
- Modify: `pybluehost/hci/controller.py:237-246`, `pybluehost/hci/controller.py:407-424`
- Create: `tests/unit/hci/test_event_listener_api.py`

- [ ] **Step 1: Write the failing listener tests**

Create `tests/unit/hci/test_event_listener_api.py` (as landed in `d23344a` it also carries four tests beyond the sketch below — events that never reach upstream, multi-listener exception isolation, async listener scheduling, and self-removal during dispatch):

```python
"""Tests for the HCIController generic removable event-listener hook."""
from __future__ import annotations

import asyncio

from pybluehost.hci.constants import EventCode
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCIEvent


class SilentTransport:
    def __init__(self) -> None:
        self._sink = None

    def set_sink(self, sink) -> None:
        self._sink = sink

    async def send(self, data: bytes) -> None:
        pass

    @property
    def is_open(self) -> bool:
        return True


def make_controller() -> HCIController:
    return HCIController(SilentTransport())


async def test_hci_event_listener_receives_raw_event_before_upstream():
    controller = make_controller()
    order: list[str] = []
    event = HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"\x00\x42\x00")

    def listener(received: HCIEvent) -> None:
        order.append("listener")
        assert received is event

    async def upstream(received: HCIEvent) -> None:
        order.append("upstream")
        assert received is event

    controller.set_upstream(on_hci_event=upstream)
    remove = controller.on_hci_event_listener(listener)
    await controller.on_transport_data(event.to_bytes())
    await asyncio.sleep(0)

    assert order == ["listener", "upstream"]
    remove()


async def test_hci_event_listener_can_be_removed():
    controller = make_controller()
    seen: list[HCIEvent] = []
    remove = controller.on_hci_event_listener(seen.append)
    remove()
    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert seen == []


async def test_hci_event_listener_exception_does_not_break_upstream():
    controller = make_controller()
    seen: list[str] = []

    def broken_listener(received: HCIEvent) -> None:
        raise RuntimeError("listener failed")

    async def upstream(received: HCIEvent) -> None:
        seen.append("upstream")

    controller.set_upstream(on_hci_event=upstream)
    controller.on_hci_event_listener(broken_listener)
    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert seen == ["upstream"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/hci/test_event_listener_api.py -v
```

Expected: FAIL with `AttributeError: 'HCIController' object has no attribute 'on_hci_event_listener'`.

- [ ] **Step 3: Implement listener storage and registration**

Add `import contextlib` to the standard-library imports at the top of `pybluehost/hci/controller.py`.

In `HCIController.__init__`, immediately after the encryption event listener lists, add:

```python
        # Generic one-shot observers for raw HCI events. Listeners receive
        # every event before the single upstream callback and may be removed
        # by the callable returned from on_hci_event_listener().
        self._hci_event_listeners: list = []
```

Add this public method immediately after `set_upstream()`:

```python
    def on_hci_event_listener(self, listener: Callable[[HCIEvent], object]) -> Callable[[], None]:
        """Register a raw HCI event observer; return a removal callable."""
        self._hci_event_listeners.append(listener)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._hci_event_listeners.remove(listener)

        return remove
```

- [ ] **Step 4: Fan out every raw event before command handling**

At the top of `HCIController._handle_event()`, before its first `isinstance(event, HCI_Command_Complete_Event)` check, insert:

```python
        for listener in list(self._hci_event_listeners):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    _schedule_listener_result(result)
            except Exception:
                logger.exception("HCI event listener failed for event 0x%02X", event.event_code)
```

- [ ] **Step 5: Run the listener tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/hci/test_event_listener_api.py -v
```

Expected: PASS, 7 tests (the sketch below shows three; as landed the file also pins the never-reaches-upstream contract, multi-listener exception isolation, async scheduling, and self-removal during dispatch).

- [ ] **Step 6: Commit**

```bash
git add pybluehost/hci/controller.py tests/unit/hci/test_event_listener_api.py
git commit -m "feat(hci): add removable raw event listeners"
```

## Task 3: Reusable Stack remote-information API

**Files:**
- Modify: `pybluehost/stack.py:98-124`, `pybluehost/stack.py:1819-1852`
- Create: `tests/unit/test_stack_remote_info.py`

- [ ] **Step 1: Write the failing Stack API tests**

Create `tests/unit/test_stack_remote_info.py`:

```python
"""Tests for Stack.read_remote_information()."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCIEvent
from pybluehost.stack import Stack


class FakeHCI:
    def __init__(self, *, name: bool = True, supported: bool = True,
                 extended: bool = True, version: bool = True) -> None:
        self.commands: list = []
        self.enabled = {"name": name, "supported": supported, "extended": extended, "version": version}
        self.listeners: list = []
        self.remove_listener = lambda: None
        self.on_hci_event_listener = self._register

    def _register(self, listener):
        self.listeners.append(listener)
        return lambda: None

    async def send_command(self, command):
        self.commands.append(command)
        opcode = command.opcode
        handle = struct.unpack_from("<H", command.parameters, 0)[0] if len(command.parameters) >= 2 else None
        if opcode == 0x0419 and self.enabled["name"]:
            self._emit_remote_name(command.parameters[:6])
        elif opcode == 0x041B and self.enabled["supported"]:
            self._emit_event(
                EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE,
                b"\x00" + struct.pack("<H", handle) + bytes(8),
            )
        elif opcode == 0x041C and self.enabled["extended"]:
            self._emit_event(
                EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE,
                b"\x00" + struct.pack("<H", handle) + b"\x01\x02" + bytes(8),
            )
        elif opcode == 0x041D and self.enabled["version"]:
            self._emit_event(
                EventCode.READ_REMOTE_VERSION_COMPLETE,
                b"\x00" + struct.pack("<H", handle)
                + struct.pack("<BHH", 0x0C, 2, 3),
            )
        return HCIEvent(event_code=int(EventCode.COMMAND_STATUS), parameters=b"\x00\x01" + struct.pack("<H", opcode))

    def _emit_remote_name(self, peer):
        self._emit_event(
            EventCode.REMOTE_NAME_REQUEST_COMPLETE,
            b"\x00" + peer + b"Remote Device".ljust(248, b"\x00"),
        )

    def _emit_event(self, code, parameters):
        event = HCIEvent(event_code=int(code), parameters=parameters)
        for listener in list(self.listeners):
            listener(event)


def make_stack(fake_hci: FakeHCI) -> Stack:
    stack = Stack()
    stack._hci = fake_hci
    return stack


async def test_read_remote_information_issues_all_four_commands_in_order():
    hci = FakeHCI()
    stack = make_stack(hci)
    peer = BDAddress.from_string("1A:8D:8D:1B:F5:6B")
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.1)
    assert [command.opcode for command in hci.commands] == [0x0419, 0x041B, 0x041C, 0x041D]
    assert snapshot.remote_name.name == "Remote Device"
    assert snapshot.supported_features.lmp_features == bytes(8)
    assert snapshot.extended_features[0].max_page_number == 2
    assert snapshot.version_information.company_id == 2
    assert snapshot.errors == {}


async def test_read_remote_information_continues_after_each_failure():
    hci = FakeHCI(name=False, supported=False, extended=False, version=False)
    stack = make_stack(hci)
    peer = BDAddress.from_string("1A:8D:8D:1B:F5:6B")
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.01)
    assert [command.opcode for command in hci.commands] == [0x0419, 0x041B, 0x041C, 0x041D]
    assert set(snapshot.errors) == {"remote_name", "supported_features", "extended_features", "version_information"}


async def test_read_remote_information_skips_name_without_peer_address():
    hci = FakeHCI()
    stack = make_stack(hci)
    snapshot = await stack.read_remote_information(0x0042, timeout=0.1)
    assert [command.opcode for command in hci.commands] == [0x041B, 0x041C, 0x041D]
    assert snapshot.errors["remote_name"] == "peer_address_required"


async def test_read_remote_information_does_not_leave_listeners_registered():
    removals: list[bool] = []

    class RemovingHCI(FakeHCI):
        def _register(self, listener):
            self.listeners.append(listener)
            return lambda: removals.append(True)

    hci = RemovingHCI()
    stack = make_stack(hci)
    await stack.read_remote_information(0x0042, timeout=0.1)
    assert removals == [True, True, True]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/test_stack_remote_info.py -v
```

Expected: FAIL with `AttributeError: 'Stack' object has no attribute 'read_remote_information'`.

- [ ] **Step 3: Add the Stack API implementation**

No new per-instance state is needed — each query uses a local future and a local one-shot listener (see `_send_and_wait_remote_info_event` below).

Add these top-level imports to `pybluehost/stack.py` (place them with the other `pybluehost.*` imports near the top). `stack.py` has `from __future__ import annotations` at line 2, so the `HCIEvent`/`HCICommand` type hints are strings at runtime; only `EventCode` and the `remote_info` names are actually imported for runtime use:

```python
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCICommand, HCIEvent
from pybluehost.hci.remote_info import (
    RemoteDeviceInformation,
    RemoteInformationError,
    build_read_remote_extended_features,
    build_read_remote_supported_features,
    build_read_remote_version_information,
    build_remote_name_request,
    parse_remote_extended_features_complete,
    parse_remote_name_request_complete,
    parse_remote_supported_features_complete,
    parse_remote_version_information_complete,
)
```

Insert these methods immediately before `async def power_on(self) -> None:`:

```python
    async def _send_and_wait_remote_info_event(
        self,
        command: HCICommand,
        *,
        key: str,
        event_code: int,
        timeout: float,
        snapshot: RemoteDeviceInformation,
    ) -> HCIEvent | None:
        """Send one remote-information command and await its completion event.

        The raw-event listener is registered *before* the command is sent so a
        controller (real or fake) that reports the completion synchronously
        cannot race past the waiter. ``send_command`` resolves on the
        Command_Status reply; the completion event arrives later and is caught
        by the listener.
        """
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[HCIEvent] = loop.create_future()

        def on_event(event: HCIEvent) -> None:
            if event.event_code == event_code and not waiter.done():
                waiter.set_result(event)

        remove = self._hci.on_hci_event_listener(on_event)
        try:
            await self._hci.send_command(command)
            return await asyncio.wait_for(waiter, timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            snapshot.errors[key] = f"timeout: {exc}"
            logger.warning("Remote HCI %s query timed out", key)
            return None
        except Exception as exc:
            snapshot.errors[key] = str(exc)
            logger.warning("Remote HCI %s query failed: %s", key, exc)
            return None
        finally:
            remove()

    async def _query_remote_name(
        self, command: HCICommand, peer: BDAddress, *,
        timeout: float, snapshot: RemoteDeviceInformation,
    ) -> None:
        event = await self._send_and_wait_remote_info_event(
            command, key="remote_name",
            event_code=int(EventCode.REMOTE_NAME_REQUEST_COMPLETE),
            timeout=timeout, snapshot=snapshot,
        )
        if event is None:
            return
        try:
            parsed = parse_remote_name_request_complete(event, peer)
            if parsed.status != 0:
                snapshot.errors["remote_name"] = _hci_status_text(parsed.status)
            else:
                snapshot.remote_name = parsed
        except RemoteInformationError as exc:
            snapshot.errors["remote_name"] = str(exc)

    async def _query_remote_supported_features(
        self, command: HCICommand, *, timeout: float,
        snapshot: RemoteDeviceInformation,
    ) -> None:
        event = await self._send_and_wait_remote_info_event(
            command, key="supported_features",
            event_code=int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE),
            timeout=timeout, snapshot=snapshot,
        )
        if event is None:
            return
        try:
            parsed = parse_remote_supported_features_complete(event, snapshot.handle)
            if parsed.status != 0:
                snapshot.errors["supported_features"] = _hci_status_text(parsed.status)
            else:
                snapshot.supported_features = parsed
        except RemoteInformationError as exc:
            snapshot.errors["supported_features"] = str(exc)

    async def _query_remote_extended_features(
        self, command: HCICommand, *, timeout: float,
        snapshot: RemoteDeviceInformation,
    ) -> None:
        event = await self._send_and_wait_remote_info_event(
            command, key="extended_features",
            event_code=int(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE),
            timeout=timeout, snapshot=snapshot,
        )
        if event is None:
            return
        try:
            parsed = parse_remote_extended_features_complete(
                event, snapshot.handle, page_number=1,
            )
            if parsed.status != 0:
                snapshot.errors["extended_features"] = _hci_status_text(parsed.status)
            else:
                snapshot.extended_features.append(parsed)
        except RemoteInformationError as exc:
            snapshot.errors["extended_features"] = str(exc)

    async def _query_remote_version_information(
        self, command: HCICommand, *, timeout: float,
        snapshot: RemoteDeviceInformation,
    ) -> None:
        event = await self._send_and_wait_remote_info_event(
            command, key="version_information",
            event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE),
            timeout=timeout, snapshot=snapshot,
        )
        if event is None:
            return
        try:
            parsed = parse_remote_version_information_complete(event, snapshot.handle)
            if parsed.status != 0:
                snapshot.errors["version_information"] = _hci_status_text(parsed.status)
            else:
                snapshot.version_information = parsed
        except RemoteInformationError as exc:
            snapshot.errors["version_information"] = str(exc)

    async def read_remote_information(
        self,
        handle: int,
        *,
        peer_address: BDAddress | None = None,
        timeout: float = 2.0,
    ) -> RemoteDeviceInformation:
        """Read remote name, feature, and version information over HCI.

        Every query is best-effort: failures are recorded in the returned
        snapshot's ``errors`` mapping and do not abort later queries.
        """
        self._check_writable()
        snapshot = RemoteDeviceInformation(handle=handle)
        queries: list[tuple[str, object]] = []
        if peer_address is None:
            snapshot.errors["remote_name"] = "peer_address_required"
        else:
            queries.append((
                "remote_name",
                lambda: self._query_remote_name(
                    build_remote_name_request(peer_address),
                    peer_address, timeout=timeout, snapshot=snapshot,
                ),
            ))
        queries.extend([
            ("supported_features", lambda: self._query_remote_supported_features(
                build_read_remote_supported_features(handle),
                timeout=timeout, snapshot=snapshot,
            )),
            ("extended_features", lambda: self._query_remote_extended_features(
                build_read_remote_extended_features(handle, page_number=1),
                timeout=timeout, snapshot=snapshot,
            )),
            ("version_information", lambda: self._query_remote_version_information(
                build_read_remote_version_information(handle),
                timeout=timeout, snapshot=snapshot,
            )),
        ])
        for key, query in queries:
            try:
                await query()
            except Exception as exc:
                snapshot.errors[key] = str(exc)
                logger.warning("Remote HCI %s query failed: %s", key, exc)
        return snapshot
```

- [ ] **Step 4: Run the Stack API tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/test_stack_remote_info.py -v
```

Expected: PASS, 4 tests. If `asyncio.wait_for` raises `asyncio.TimeoutError` rather than built-in `TimeoutError`, the existing `except (asyncio.TimeoutError, TimeoutError)` clause covers both.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/stack.py tests/unit/test_stack_remote_info.py
git commit -m "feat(stack): add best-effort remote HCI information API"
```

## Task 4: Wire the best-effort prelude into `app sdp-browser`

**Files:**
- Modify: `pybluehost/cli/app/sdp_browser.py:125-155`
- Modify: `tests/unit/cli/test_app_sdp_browser.py:78-252`

- [ ] **Step 1: Add the failing CLI tests**

Append these tests to `tests/unit/cli/test_app_sdp_browser.py`:

```python
async def test_sdp_browser_logs_remote_information_before_authentication(monkeypatch, capsys):
    from pybluehost.hci.remote_info import (
        RemoteDeviceInformation,
        RemoteExtendedFeatures,
        RemoteName,
        RemoteSupportedFeatures,
        RemoteVersionInformation,
    )

    snapshot = RemoteDeviceInformation(
        handle=0x0042,
        remote_name=RemoteName(status=0, name="Remote Device"),
        supported_features=RemoteSupportedFeatures(status=0, lmp_features=bytes.fromhex("ff59000800000000")),
        extended_features=[RemoteExtendedFeatures(0, 1, 2, bytes(8))],
        version_information=RemoteVersionInformation(0, 0x0C, 0x000F, 0x1234),
    )

    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            return object()

    class FakeStack:
        l2cap = FakeL2CAP()
        order = []

        async def connect_classic(self, addr):
            return 0x0042

        async def read_remote_information(self, handle, *, peer_address=None, timeout=2.0):
            assert handle == 0x0042
            assert str(peer_address) == "A0:90:B5:10:40:82"
            return snapshot

        async def authenticate_classic(self, handle):
            self.order.append("authenticate")

        async def enable_classic_encryption(self, handle):
            pass

    async def run_app(_transport_arg, main_coro, **_kwargs):
        await main_coro(FakeStack(), asyncio.Event())
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            pass

        async def search_attributes(self, target, uuid, attr_ids=None):
            return []

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)
    args = argparse.Namespace(
        transport="virtual", target="A0:90:B5:10:40:82", uuid=0x1101,
        sdp_timeout=10.0, max_attribute_bytes=0x03F0, hci_log=False, btsnoop=None,
    )
    assert await _sdp_browser_main(args) == 0
    out = capsys.readouterr().out
    assert "Remote name: Remote Device" in out
    assert "Remote LMP features: ff59000800000000" in out
    assert "Remote extended features page 1/2: 0000000000000000" in out
    assert "Remote Company_ID: 0x000F (Broadcom Corporation)" in out
    assert "Remote LMP version: 0x0C (Bluetooth 5.3) subversion=0x1234" in out
    assert out.index("Remote Company_ID") < out.index("Authenticated ACL")


async def test_sdp_browser_continues_when_remote_information_raises(monkeypatch, capsys):
    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            return object()

    class FakeStack:
        l2cap = FakeL2CAP()
        authenticated = False

        async def connect_classic(self, addr):
            return 0x0042

        async def read_remote_information(self, handle, **kwargs):
            raise RuntimeError("remote information unavailable")

        async def authenticate_classic(self, handle):
            self.authenticated = True

        async def enable_classic_encryption(self, handle):
            pass

    async def run_app(_transport_arg, main_coro, **_kwargs):
        stack = FakeStack()
        await main_coro(stack, asyncio.Event())
        assert stack.authenticated is True
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            pass

        async def search_attributes(self, target, uuid, attr_ids=None):
            return []

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)
    args = argparse.Namespace(
        transport="virtual", target="A0:90:B5:10:40:82", uuid=0x1101,
        sdp_timeout=10.0, max_attribute_bytes=0x03F0, hci_log=False, btsnoop=None,
    )
    assert await _sdp_browser_main(args) == 0
    assert "remote information unavailable" in capsys.readouterr().out
```

Update the three existing `FakeStack` classes in `test_sdp_browser_uses_run_app_command`, `test_sdp_browser_default_scan_deduplicates_records`, and `test_sdp_browser_accepts_custom_uuid` to add this exact method:

```python
        async def read_remote_information(self, handle, *, peer_address=None, timeout=2.0):
            from pybluehost.hci.remote_info import RemoteDeviceInformation
            return RemoteDeviceInformation(handle=handle)
```

- [ ] **Step 2: Run the CLI tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/cli/test_app_sdp_browser.py -v
```

Expected: the two new tests FAIL because `_sdp_browser_run()` never calls `read_remote_information()`; the three existing tests then FAIL because their fake Stack has been extended but the implementation has not yet changed, which is expected at this checkpoint.

- [ ] **Step 3: Implement the CLI prelude and formatter**

Add these imports to `pybluehost/cli/app/sdp_browser.py`:

```python
from pybluehost.hci.features_decode import hci_version_name
from pybluehost.hci.format_fields import format_company_id
from pybluehost.hci.remote_info import RemoteDeviceInformation
```

In `_sdp_browser_run()`, replace:

```python
    logger.info("Connected ACL handle=0x%04X", handle)
    await stack.authenticate_classic(handle)
```

with:

```python
    logger.info("Connected ACL handle=0x%04X", handle)
    await _log_remote_device_information(stack, handle, addr)
    await stack.authenticate_classic(handle)
```

Add these functions immediately before `_query_sdp_records()`:

```python
async def _log_remote_device_information(stack: Stack, handle: int, addr) -> None:
    """Query and log remote HCI identity; never block SDP browsing."""
    try:
        snapshot = await stack.read_remote_information(handle, peer_address=addr)
    except Exception as exc:
        logger.warning("Remote HCI information unavailable: %s", exc)
        return
    _log_remote_device_snapshot(snapshot)


def _log_remote_device_snapshot(snapshot: RemoteDeviceInformation) -> None:
    if snapshot.remote_name is not None:
        logger.info("Remote name: %s", snapshot.remote_name.name)
    if snapshot.supported_features is not None:
        logger.info(
            "Remote LMP features: %s", snapshot.supported_features.lmp_features.hex()
        )
    for features in snapshot.extended_features:
        logger.info(
            "Remote extended features page %d/%d: %s",
            features.page_number, features.max_page_number,
            features.extended_lmp_features.hex(),
        )
    version = snapshot.version_information
    if version is not None:
        logger.info("Remote Company_ID: %s", format_company_id(version.company_id))
        logger.info(
            "Remote LMP version: 0x%02X (%s) subversion=0x%04X",
            version.lmp_version, hci_version_name(version.lmp_version),
            version.lmp_subversion,
        )
    for query, error in sorted(snapshot.errors.items()):
        logger.warning("Remote HCI %s unavailable: %s", query, error)
```

- [ ] **Step 4: Run the CLI tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/cli/test_app_sdp_browser.py -v
```

Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/sdp_browser.py tests/unit/cli/test_app_sdp_browser.py
git commit -m "feat(cli): log remote HCI identity before SDP browsing"
```

## Task 5: Virtual-controller and VirtualClassicLink support

**Files:**
- Modify: `pybluehost/hci/virtual.py:102-132`, `pybluehost/hci/virtual.py:472-532`
- Modify: `pybluehost/hci/virtual_classic_link.py:134-236`
- Modify: `tests/e2e/test_cli_app_lifecycle.py:395-430`

- [ ] **Step 1: Add failing virtual-controller tests**

Create `tests/unit/hci/test_virtual_remote_info.py` with this exact content:

```python
"""Tests for VirtualController remote-information command handling."""
from __future__ import annotations

import struct

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_READ_REMOTE_EXTENDED_FEATURES,
    HCI_READ_REMOTE_SUPPORTED_FEATURES,
    HCI_READ_REMOTE_VERSION_INFORMATION,
    HCI_REMOTE_NAME_REQUEST,
)
from pybluehost.hci.packets import HCICommand, decode_hci_packet
from pybluehost.hci.virtual import VirtualController


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[bytes] = []

    async def on_transport_data(self, data: bytes) -> None:
        self.events.append(data)


def make_controller() -> tuple[VirtualController, CapturingSink]:
    controller = VirtualController(BDAddress.from_string("AA:BB:CC:DD:EE:01"))
    sink = CapturingSink()
    controller._host_sink = sink
    return controller, sink


async def settle() -> None:
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)


def decode_completion(sink: CapturingSink):
    assert len(sink.events) == 1
    return decode_hci_packet(sink.events[0])


async def test_virtual_controller_emits_remote_name_request_complete():
    controller, sink = make_controller()
    peer = BDAddress.from_string("1A:8D:8D:1B:F5:6B")
    command = HCICommand(
        opcode=HCI_REMOTE_NAME_REQUEST,
        parameters=peer.to_hci() + bytes([0x01, 0x00, 0x00, 0x00]),
    )
    assert (await controller.process(command.to_bytes())) is not None
    await settle()
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.REMOTE_NAME_REQUEST_COMPLETE)
    assert event.parameters[1:7] == peer.to_hci()
    assert event.parameters[7:].rstrip(b"\x00") == b"Virtual Peer"


async def test_virtual_controller_emits_remote_supported_features_complete():
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_READ_REMOTE_SUPPORTED_FEATURES,
        parameters=struct.pack("<H", 0x0042),
    )
    await controller.process(command.to_bytes())
    await settle()
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE)
    assert struct.unpack_from("<H", event.parameters, 1)[0] == 0x0042
    assert len(event.parameters) == 11


async def test_virtual_controller_emits_remote_extended_features_complete():
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_READ_REMOTE_EXTENDED_FEATURES,
        parameters=struct.pack("<HB", 0x0042, 1),
    )
    await controller.process(command.to_bytes())
    await settle()
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE)
    assert event.parameters[3:5] == b"\x01\x02"
    assert len(event.parameters) == 13


async def test_virtual_controller_emits_remote_version_information_complete():
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_READ_REMOTE_VERSION_INFORMATION,
        parameters=struct.pack("<H", 0x0042),
    )
    await controller.process(command.to_bytes())
    await settle()
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.READ_REMOTE_VERSION_COMPLETE)
    assert struct.unpack_from("<BHH", event.parameters, 3) == (0x0C, 0x0002, 0x0001)
```

Read `tests/e2e/test_cli_app_lifecycle.py:395-430`. Keep its existing SDP-record assertions. If that test constructs a real virtual Stack, add this assertion after `_sdp_browser_run()` returns:

```python
    assert "Remote Company_ID" in caplog.text
```

- [ ] **Step 2: Run the virtual tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/hci/test_virtual_remote_info.py tests/e2e/test_cli_app_lifecycle.py::test_sdp_browser_cli_app_queries_spp_echo_record -v --transport=virtual
```

Expected: the new virtual tests FAIL because `VirtualController.process()` has no remote-information handlers; the e2e assertion fails only if that test uses a real virtual Stack.

- [ ] **Step 3: Add VirtualController command handlers**

In `VirtualController.__init__` handler dict, add these four entries:

```python
            HCI_REMOTE_NAME_REQUEST: self._handle_remote_name_request,
            HCI_READ_REMOTE_SUPPORTED_FEATURES: self._handle_read_remote_supported_features,
            HCI_READ_REMOTE_EXTENDED_FEATURES: self._handle_read_remote_extended_features,
            HCI_READ_REMOTE_VERSION_INFORMATION: self._handle_read_remote_version_information,
```

Add the corresponding imports from `pybluehost.hci.constants` and then add these methods beside `_handle_read_local_version()`:

```python
    def _remote_info_handle(self, cmd: HCICommand) -> int:
        return struct.unpack_from("<H", cmd.parameters, 0)[0] if len(cmd.parameters) >= 2 else 0

    def _emit_remote_info_completion(self, event_code: int, parameters: bytes) -> None:
        async def emit() -> None:
            await asyncio.sleep(0)
            await self._send_event_to_host(
                HCIEvent(event_code=int(event_code), parameters=parameters)
            )
        asyncio.create_task(emit())

    def _handle_remote_name_request(self, cmd: HCICommand) -> bytes:
        peer = cmd.parameters[:6]
        params = b"\x00" + peer + b"Virtual Peer".ljust(248, b"\x00")
        self._emit_remote_info_completion(EventCode.REMOTE_NAME_REQUEST_COMPLETE, params)
        return b"\x00"

    def _handle_read_remote_supported_features(self, cmd: HCICommand) -> bytes:
        handle = self._remote_info_handle(cmd)
        params = b"\x00" + struct.pack("<H", handle) + bytes(8)
        self._emit_remote_info_completion(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE, params)
        return b"\x00"

    def _handle_read_remote_extended_features(self, cmd: HCICommand) -> bytes:
        handle = self._remote_info_handle(cmd)
        page = cmd.parameters[2] if len(cmd.parameters) >= 3 else 0
        params = b"\x00" + struct.pack("<H", handle) + bytes([page, 2]) + bytes(8)
        self._emit_remote_info_completion(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE, params)
        return b"\x00"

    def _handle_read_remote_version_information(self, cmd: HCICommand) -> bytes:
        handle = self._remote_info_handle(cmd)
        payload = struct.pack("<BHH", 0x0C, 0x0002, 0x0001)
        params = b"\x00" + struct.pack("<H", handle) + payload
        self._emit_remote_info_completion(EventCode.READ_REMOTE_VERSION_COMPLETE, params)
        return b"\x00"
```

- [ ] **Step 4: Add VirtualClassicLink interceptor branches**

Add the four opcode imports from `pybluehost.hci.constants` to `pybluehost/hci/virtual_classic_link.py`. In `_make_interceptor()`, insert these branches immediately after the `HCI_CREATE_CONNECTION` branch:

```python
            if opcode == HCI_REMOTE_NAME_REQUEST:
                peer_addr_bytes = raw_params[0:6]
                params = b"\x00" + peer_addr_bytes + b"Virtual Peer".ljust(248, b"\x00")
                asyncio.create_task(self._emit_remote_info_event(
                    controller, int(EventCode.REMOTE_NAME_REQUEST_COMPLETE), params,
                ))
                return self._command_status(opcode, status=0)
            if opcode == HCI_READ_REMOTE_SUPPORTED_FEATURES:
                handle = struct.unpack_from("<H", raw_params, 0)[0]
                params = b"\x00" + struct.pack("<H", handle) + bytes(8)
                asyncio.create_task(self._emit_remote_info_event(
                    controller, int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE), params,
                ))
                return self._command_status(opcode, status=0)
            if opcode == HCI_READ_REMOTE_EXTENDED_FEATURES:
                handle = struct.unpack_from("<H", raw_params, 0)[0]
                page = raw_params[2] if len(raw_params) > 2 else 0
                params = b"\x00" + struct.pack("<H", handle) + bytes([page, 2]) + bytes(8)
                asyncio.create_task(self._emit_remote_info_event(
                    controller, int(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE), params,
                ))
                return self._command_status(opcode, status=0)
            if opcode == HCI_READ_REMOTE_VERSION_INFORMATION:
                handle = struct.unpack_from("<H", raw_params, 0)[0]
                payload = struct.pack("<BHH", 0x0C, 0x0002, 0x0001)
                params = b"\x00" + struct.pack("<H", handle) + payload
                asyncio.create_task(self._emit_remote_info_event(
                    controller, int(EventCode.READ_REMOTE_VERSION_COMPLETE), params,
                ))
                return self._command_status(opcode, status=0)
```

Add this helper beside `_emit_connection_complete()`:

```python
    async def _emit_remote_info_event(
        self, controller: VirtualController, event_code: int, parameters: bytes,
    ) -> None:
        await asyncio.sleep(0)
        event = HCIEvent(event_code=event_code, parameters=parameters)
        sink = controller._host_sink
        if sink is not None:
            await sink.on_transport_data(event.to_bytes())
```

- [ ] **Step 5: Run the e2e and virtual-controller tests**

Run:

```bash
uv run pytest tests/unit/hci/test_virtual_remote_info.py tests/unit/hci tests/e2e/test_cli_app_lifecycle.py::test_sdp_browser_cli_app_queries_spp_echo_record -v --transport=virtual
```

Expected: PASS. The lifecycle test confirms the CLI prelude works through the virtual Classic link; the dedicated virtual-controller tests pin every synthetic completion event.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/hci/virtual.py pybluehost/hci/virtual_classic_link.py tests/unit/hci/test_virtual_remote_info.py tests/e2e/test_cli_app_lifecycle.py
git commit -m "test(hci): support remote information on virtual Classic links"
```

## Task 6: Documentation and full verification

**Files:**
- Modify: `README.md:126-134`, `README.md:835-842`
- Modify: `AGENTS.md` "已交付子系统" section
- Modify: `docs/superpowers/STATUS.md` only if this work is being tracked as a Plan

- [ ] **Step 1: Add README usage note**

Immediately after the two `pybluehost app sdp-browser` examples in README §1.4 add:

```markdown
连接 ACL 后，`sdp-browser` 会先通过 HCI 尽力读取并打印远端名称、LMP 支持/扩展特性，以及 `Read_Remote_Version_Information_Complete` 中的 `Company_ID`、LMP 版本和 subversion；任一查询失败只记 warning，不影响后续 SDP 浏览。
```

Add `read_remote_information` to the CLI/API documentation sentence near the `sdp-browser` command table without changing the command name or required flags.

- [ ] **Step 2: Add AGENTS.md API note**

In the "已交付子系统" section, add a `### Remote HCI information` subsection with:

```markdown
`Stack.read_remote_information(handle, *, peer_address=None, timeout=2.0)` 返回 `RemoteDeviceInformation`：依次查询 `HCI_Remote_Name_Request`、`HCI_Read_Remote_Supported_Features`、`HCI_Read_Remote_Extended_Features`(page 1)、`HCI_Read_Remote_Version_Information`。`Company_ID` 经 `format_company_id()` 解析 SIG 公司名。四项均 best-effort，失败写进 `snapshot.errors`，不抛给调用方；`app sdp-browser` 在连接后、认证前打印这些信息。线格式与解析：`pybluehost/hci/remote_info.py`；单测：`tests/unit/hci/test_remote_info.py`、`tests/unit/test_stack_remote_info.py`、`tests/unit/cli/test_app_sdp_browser.py`。
```

- [ ] **Step 3: Run project doc self-checks**

Run:

```bash
uv run pytest tests/unit/test_version_sync.py -q
for cmd in $(grep -oE "pybluehost (app|tools) [a-z-]+" README.md | awk '{print $3}' | sort -u); do
  uv run pybluehost --help 2>&1 | grep -qE "[[:space:]]$cmd\b" || \
  uv run pybluehost app --help 2>&1 | grep -qE "[[:space:]]$cmd\b" || \
  uv run pybluehost tools --help 2>&1 | grep -qE "[[:space:]]$cmd\b" || \
  echo "stale CLI in README: $cmd"
done
```

Expected: version test PASS; no `stale CLI in README` lines.

- [ ] **Step 4: Run the focused regression suite**

Run:

```bash
uv run pytest tests/unit/hci tests/unit/test_stack_remote_info.py tests/unit/cli tests/unit/test_stack.py tests/e2e/test_cli_app_lifecycle.py -q --transport=virtual
```

Expected: PASS with zero failures.

- [ ] **Step 5: Run the full virtual suite**

Run:

```bash
uv run pytest tests/ -q --transport=virtual
```

Expected: PASS with zero failures; skipped hardware/sig_db tests are acceptable and must be reported with their count.

- [ ] **Step 6: Commit documentation and verification result**

```bash
git add README.md AGENTS.md docs/superpowers/STATUS.md
git commit -m "docs: document remote HCI information API and sdp-browser prelude"
```

Only include `docs/superpowers/STATUS.md` in this command if it was actually modified; otherwise omit that path from both `git add` and the commit.

---

## Self-Review Notes

* Spec coverage: four command/query pairs, typed snapshot, company/version formatting, reusable Stack API, best-effort errors, sdp-browser order, virtual links, tests, and docs are covered by Tasks 1–6.
* The snapshot keys are stable throughout: `remote_name`, `supported_features`, `extended_features`, `version_information`.
* `RemoteDeviceInformation.extended_features` is a list; the CLI iterates it and the Stack appends one page-1 result.
* No new CLI flags are introduced, so README's CLI command table does not need a new command row.
