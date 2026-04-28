# CLI Demo Functional Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CLI demos prove real protocol behavior instead of only proving that commands start and stop.

**Architecture:** BLE peripheral demos use the existing GAP advertiser, ATT fixed channel binding, GATT server, and BLE profile decorators. Classic SDP/SPP demos must not hide missing lower layers; RFCOMM/SDP remain blocked on Classic ACL + L2CAP dynamic PSM support and must fail loudly until that stack is implemented.

**Tech Stack:** Python 3.10+, asyncio, pytest, pybluehost HCI/L2CAP/GATT/RFCOMM modules.

---

### Task 1: BLE GATT Callback Binding

**Files:**
- Modify: `pybluehost/ble/gatt.py`
- Modify: `pybluehost/profiles/ble/base.py`
- Modify: `pybluehost/profiles/ble/bas.py`
- Modify: `pybluehost/profiles/ble/hrs.py`
- Test: `tests/unit/ble/test_gatt.py`
- Test: `tests/unit/profiles/test_builtin.py`

- [x] **Step 1: Add failing GATT read/write callback tests**

Run:

```bash
uv run --frozen pytest tests/unit/ble/test_gatt.py::test_gatt_server_read_request_uses_bound_handler tests/unit/ble/test_gatt.py::test_gatt_server_write_request_uses_bound_handler -q --transport=virtual
```

Expected before implementation: FAIL because `GATTServer.register_read_handler()` and `register_write_handler()` do not exist.

- [x] **Step 2: Bind profile callbacks into GATTServer**

`BLEProfileServer.register()` binds `@on_read`, `@on_write`, and `@on_notify` methods to characteristic value handles.

- [x] **Step 3: Update profile state through the GATT DB**

`BatteryServer.update_level()` and `HeartRateServer.update_measurement()` refresh the characteristic value and notify subscribed connections.

- [x] **Step 4: Verify profile tests pass**

Run:

```bash
uv run --frozen pytest tests/unit/ble/test_gatt.py tests/unit/profiles/test_builtin.py -q --transport=virtual
```

Expected: PASS.

### Task 2: BLE Peripheral CLI Advertising

**Files:**
- Create: `pybluehost/cli/app/_ble_peripheral.py`
- Modify: `pybluehost/cli/app/gatt_server.py`
- Modify: `pybluehost/cli/app/hr_monitor.py`
- Modify: `pybluehost/ble/gap.py`
- Test: `tests/unit/cli/test_app_gatt_server.py`
- Test: `tests/unit/cli/test_app_hr_monitor.py`
- Test: `tests/unit/ble/test_gap.py`

- [x] **Step 1: Add failing app tests for connectable advertising**

Tests assert `BLEAdvertiser.start()` is called with ADV_IND, flags, service UUIDs, scan response name, and `stop()` is called on exit.

- [x] **Step 2: Add shared advertising helper**

`_ble_peripheral.py` builds AD flags, UUID16 list, scan response local name, and starts/stops connectable advertising.

- [x] **Step 3: Send scan response data**

`BLEAdvertiser.start()` now sends `HCI_LE_Set_Scan_Response_Data` before enabling advertising.

- [x] **Step 4: Verify BLE app tests pass**

Run:

```bash
uv run --frozen pytest tests/unit/cli/test_app_gatt_server.py tests/unit/cli/test_app_hr_monitor.py tests/unit/ble/test_gap.py -q --transport=virtual
```

Expected: PASS.

### Task 3: Classic Demo Stub Exposure

**Files:**
- Modify: `pybluehost/classic/rfcomm.py`
- Modify: `pybluehost/cli/app/spp_echo.py`
- Test: `tests/unit/classic/test_rfcomm.py`
- Test: `tests/unit/cli/test_app_spp_echo.py`

- [x] **Step 1: Make RFCOMM no-op methods fail loudly**

`RFCOMMManager.listen()` and L2CAP-less channel operations raise `NotImplementedError` instead of silently succeeding.

- [x] **Step 2: Keep testable RFCOMM frame output**

`RFCOMMChannel.send()` writes segmented UIH frames when given an L2CAP-backed session.

- [x] **Step 3: Make spp-echo use SPPService**

The CLI registers an SDP record and calls RFCOMM listen. Until Classic L2CAP PSM 0x0003 exists, it reports the real missing layer.

- [x] **Step 4: Verify Classic stub exposure tests pass**

Run:

```bash
uv run --frozen pytest tests/unit/classic/test_rfcomm.py tests/unit/cli/test_app_spp_echo.py -q --transport=virtual
```

Expected: PASS, with tests asserting explicit `NotImplementedError` for the missing Classic L2CAP path.

### Task 4: Remaining Classic Work

**Files:**
- Future: `pybluehost/classic/gap.py`
- Future: `pybluehost/l2cap/classic.py`
- Future: `pybluehost/l2cap/manager.py`
- Future: `pybluehost/classic/sdp.py`
- Future: `pybluehost/classic/rfcomm.py`
- Future: `pybluehost/cli/app/sdp_browser.py`
- Future: `pybluehost/cli/app/spp_echo.py`

- [ ] **Step 1: Implement BR/EDR ACL connection waiters**

Expose an app-level API similar to `Stack.connect_gatt()` for Classic ACL handles.

- [ ] **Step 2: Implement Classic L2CAP dynamic PSM connect/listen**

Support SDP PSM `0x0001` and RFCOMM PSM `0x0003`.

- [ ] **Step 3: Implement SDPClient over L2CAP**

`sdp-browser` must send ServiceSearchAttribute requests and print real records.

- [ ] **Step 4: Implement RFCOMM session state machine**

Support SABM/UA/DM/DISC/UIH enough for SPP connect/listen/echo.

- [ ] **Step 5: Add CSR hardware acceptance tests**

Use:

```bash
uv run pybluehost app sdp-browser -t usb:vendor=csr -a A0:90:B5:10:40:82
uv run pybluehost app spp-echo -t usb:vendor=csr
```

Expected after implementation: no `NotImplementedError`, and protocol traffic visible in HCI/btsnoop trace.

---

## Test Policy Added By This Plan

- App demo tests must assert at least one protocol-side effect: HCI command, ATT PDU, SDP record, RFCOMM frame, or app-visible connection/error event.
- A test that only starts and stops a CLI coroutine is not sufficient for a demo.
- Stubbed protocol paths must raise explicit `NotImplementedError` and tests must name the missing lower layer.
- Hardware verification must use deterministic transport selection such as `--transport usb:vendor=csr`.
