# Remote HCI Information Design

> Approved 2026-11-07.

## Goal

After a Classic ACL connection is established, `pybluehost app sdp-browser` first retrieves remote identity information through HCI, logs it, and then continues the existing authentication, encryption, and SDP-record browsing flow.

## Scope

The reusable Stack API exposes one best-effort snapshot operation that issues these four HCI commands, in order:

1. `HCI_Remote_Name_Request` — wait for `Remote_Name_Request_Complete` and decode the remote friendly name.
2. `HCI_Read_Remote_Supported_Features` — wait for `Read_Remote_Supported_Features_Complete` and retain the 8-byte LMP feature bitmap.
3. `HCI_Read_Remote_Extended_Features` — wait for `Read_Remote_Extended_Features_Complete` for page 1, retaining page number, maximum page number, and the 8-byte feature bitmap.
4. `HCI_Read_Remote_Version_Information` — wait for `Read_Remote_Version_Information_Complete` and decode LMP version/subversion and `Company_ID` / `Manufacturer_Name`.

The result is a structured, typed snapshot suitable for other CLI apps and profiles. `sdp-browser` calls the snapshot API immediately after `stack.connect_classic()` and before `stack.authenticate_classic()`.

## Architecture

A small protocol-module owns the four constants, typed command builders, completion-event parsers, and the `RemoteInformation` / `RemoteDeviceInformation` data model. `Stack` owns the event-waiter orchestration and exposes `read_remote_information(handle, peer_address=None, timeout=...)`; it sends commands through its existing `HCIController.send_command()` path and correlates raw completion events by event code, ACL handle, and peer BD_ADDR where applicable.

`HCIController` gets a general one-shot event-listener registration hook so Stack does not replace its existing `_on_hci_event` callback or disturb L2CAP/GAP/MITM hooks. The CLI remains a thin formatter/logger.

The SIG company-name lookup reuses `SIGDatabase.company_name()` through the existing `format_company_id()` helper. HCI/LMP version names reuse `hci_version_name()` where available; feature bitmaps remain raw bytes in the typed snapshot, with their hex representation logged.

## Error handling

* Each query is individually awaited with a bounded timeout.
* A command-status error, completion-event error status, malformed event, or timeout records a per-query error in the snapshot and logs a warning. It does not abort the remaining queries and does not raise from the snapshot call.
* Unsupported optional commands are treated the same way. `HCI_Read_Remote_Extended_Features` page 1 is optional; no additional pages are fetched in this version.
* `Remote_Name_Request` requires a peer address. If no address is supplied, the snapshot records `peer_address_required` and skips only that query.
* `sdp-browser` always proceeds to authentication/encryption/SDP even if every remote-information query fails.

## Testing

* Unit tests cover all four wire commands (opcode and exact parameters), all four completion-event parsers (including error status and malformed payload), and the company-ID / version decoding.
* Stack tests use fake HCI controllers that inject typed completion events; they assert command order, per-handle event correlation, timeout isolation, and best-effort continuation.
* CLI tests use a fake Stack snapshot method and assert the identity lines appear between `Connected ACL` and `Authenticated ACL`, plus that an exception or error-only snapshot does not prevent SDP browsing.
* Virtual-controller support is added so the existing virtual/e2e Classic path can answer the four commands and emit their completion events.
* Full verification: the affected unit-test directories, CLI/e2e lifecycle tests under `--transport=virtual`, then `uv run pytest tests/ -q --transport=virtual`.

## Documentation

`README.md` gains a short note that `sdp-browser` logs the four remote-information fields before SDP records. `AGENTS.md` gains a short "Remote HCI information" subsection with the reusable API, test locations, and the best-effort contract. No new CLI arguments are added, so the CLI command table does not change.

## Non-goals

* No SDP PnP Information parsing in this version.
* No automatic queries for every Classic connection; callers opt in through the Stack method.
* No feature-bit name expansion, persistent cache, or background refresh.
* No change to authentication, encryption, or SDP continuation-state behavior.
