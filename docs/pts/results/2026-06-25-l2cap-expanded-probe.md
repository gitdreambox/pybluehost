# L2CAP Expanded PTS Probe - 2026-06-25

This report records the broader L2CAP PTS probe run on 2026-06-25 after the original current-expected manifest had already reached 8/8 PASS. It is not a completion claim for all V1.2 PTS IUT cases.

## Environment

| Item | Value |
|---|---|
| PTS version | 8.13.0.4 |
| IUT adapter | CSR8510, `00:1A:7D:DA:71:11`, `usb:0A12:0001#1` |
| PTS adapter | `USB_INTEL`, `C8:8A:9A:6D:5F:5F` |
| Workspace | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\PyBlueHost_L2CAP.pqw6` |
| Controller logs | `runs\pts_iut_controller_20260625_1510_bv06_fix\`, `runs\pts_iut_controller_20260625_2252_bv01\`, `runs\pts_iut_controller_20260625_2300_bv32\`, `runs\pts_iut_controller_20260625_2305_bv32_addr\` |

## Workspace Generation Notes

Older workspaces were generated through PTS COM `CreateWorkspace(UInt64 ullBthAddr, String pszPathOfPtsFile, String pszWorkspaceName, String pszWorkspacePath)` using small `.pts` manifests such as `pybluehost-l2cap.pts`, `pybluehost-sdp.pts`, and `pybluehost-l2cap-gap-gatt.pts`.

For this probe, profile manifests were generated under `runs\pts_profile_probe_20260625_131036\` for L2CAP, GAP, GATT, SM, and RFCOMM. PTS accepted L2CAP/GAP/GATT/SM/RFCOMM workspaces. HCI was not accepted by the installed PTS TSS set: `GetTestCaseCountFromTSSFile('HCI')` returned `HRESULT:0x849C0010`, and `CreateWorkspace` for HCI returned `HRESULT:0x849C0003`. SMP is exposed by this PTS install as `SM`, not `SMP`.

## L2CAP Setup

PIXIT/PICS used for the expanded L2CAP probe:

| Setting | Value |
|---|---|
| `TSPX_bd_addr_iut` | `001A7DDA7111` |
| `TSPX_time_guard` | `60000` |
| `TSPX_use_implicit_send` | `TRUE` |
| `TSPX_spsm` | `0080` |
| `TSPC_L2CAP_0a_2` | `TRUE` |
| `TSPC_L2CAP_2_40` | `TRUE` |
| `TSPC_L2CAP_2_45a` | `TRUE` |
| `TSPC_L2CAP_2_46` | `TRUE` |
| `TSPC_L2CAP_2_47` | `TRUE` |

Before PTS listener-style cases, the JSON controller ran `advertise` and `l2cap-le-listen psm=0x0080`.

## Code Changes Made During Probe

| Area | Change | Evidence |
|---|---|---|
| LE signaling decode | `decode_le_signaling()` now rejects frames where outer signaling length is shorter or longer than the actual frame body. | `L2CAP/COS/CED/BI-13-C` changed from FAIL to PASS. |
| LE connection event handling | `L2CAPManager.on_hci_event()` now registers LE fixed channels for `LE_ENHANCED_CONNECTION_COMPLETE` as well as legacy `LE_CONNECTION_COMPLETE`. | `L2CAP/LE/CFC/BV-06-C` changed from INDCSV to PASS; controller logged `Accepted LE CoC channel`. |
| PTS JSON controller | Added/extended commands for `advertise`, `stop-advertise`, `connect`, `pair`, `l2cap-le-listen`, and `l2cap-le-connect`; `l2cap-le-connect` can now use explicit `handle` or current `last_handle`. | Unit tests in `tests\unit\pts\test_iut_controller.py` pass. |

Focused verification commands:

```powershell
uv run pytest tests\unit\pts\test_iut_controller.py -q
uv run pytest tests\unit\l2cap\test_manager.py tests\unit\l2cap\test_le_signaling_codec.py tests\unit\l2cap\test_le_signaling_dispatch.py tests\unit\l2cap\test_le_coc_connect.py tests\unit\l2cap\test_le_coc_listen.py tests\unit\l2cap\test_le_coc_credits.py -q
```

Both commands passed after the fixes.

## Latest Expanded L2CAP Verdicts

| Test Case | Verdict | Latest XML | Notes |
|---|---|---|---|
| `L2CAP/COS/CED/BI-05-C` | PASS | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CED_BI_05_C_2026_06_25_14_18_54\L2CAP_COS_CED_BI_05_C_2026_06_25_14_18_54.xml` | IUT terminates link properly. |
| `L2CAP/COS/CED/BI-09-C` | PASS | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CED_BI_09_C_2026_06_25_14_20_12\L2CAP_COS_CED_BI_09_C_2026_06_25_14_20_12.xml` | IUT terminates link properly. |
| `L2CAP/COS/CED/BI-11-C` | FAIL | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CED_BI_11_C_2026_06_25_14_20_23\L2CAP_COS_CED_BI_11_C_2026_06_25_14_20_23.xml` | PTS asks MMI_274 whether IUT discarded the malformed frame; current automation does not answer this Yes/No prompt. |
| `L2CAP/COS/CED/BI-13-C` | PASS | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CED_BI_13_C_2026_06_25_14_48_40\L2CAP_COS_CED_BI_13_C_2026_06_25_14_48_40.xml` | Fixed by strict LE signaling frame length validation. |
| `L2CAP/COS/CED/BI-16-C` | PASS | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CED_BI_16_C_2026_06_25_14_21_45\L2CAP_COS_CED_BI_16_C_2026_06_25_14_21_45.xml` | IUT terminates link properly. |
| `L2CAP/COS/CED/BI-17-C` | PASS | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CED_BI_17_C_2026_06_25_14_21_54\L2CAP_COS_CED_BI_17_C_2026_06_25_14_21_54.xml` | IUT terminates link properly. |
| `L2CAP/COS/CED/BI-29-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CED_BI_29_C_2026_06_25_14_22_03\L2CAP_COS_CED_BI_29_C_2026_06_25_14_22_03.xml` | Requires IUT to initiate LE CoC during MMI_41; current automation did not execute during blocking `RunTestCase`. |
| `L2CAP/COS/CFC/BV-01-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CFC_BV_01_C_2026_06_25_22_52_23\L2CAP_COS_CFC_BV_01_C_2026_06_25_22_52_23.xml` | PTS sent LE CoC request with MTU `0x02A0`, MPS `0x0017`; IUT host did not log an L2CAP connection for this run. |
| `L2CAP/COS/CFC/BV-02-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CFC_BV_02_C_2026_06_25_22_46_07\L2CAP_COS_CFC_BV_02_C_2026_06_25_22_46_07.xml` | Same pattern as BV-01. |
| `L2CAP/COS/CFC/BV-03-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CFC_BV_03_C_2026_06_25_22_46_16\L2CAP_COS_CFC_BV_03_C_2026_06_25_22_46_16.xml` | Same pattern as BV-01. |
| `L2CAP/COS/CFC/BV-04-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_COS_CFC_BV_04_C_2026_06_25_22_46_25\L2CAP_COS_CFC_BV_04_C_2026_06_25_22_46_25.xml` | Same pattern as BV-01. |
| `L2CAP/LE/CFC/BI-01-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BI_01_C_2026_06_25_22_46_43\L2CAP_LE_CFC_BI_01_C_2026_06_25_22_46_43.xml` | PTS sent MTU/MPS `0x0017`; no IUT-side L2CAP connection log. |
| `L2CAP/LE/CFC/BV-06-C` | PASS | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_06_C_2026_06_25_22_38_29\L2CAP_LE_CFC_BV_06_C_2026_06_25_22_38_29.xml` | Fixed by LE Enhanced Connection Complete handling. |
| `L2CAP/LE/CFC/BV-07-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_07_C_2026_06_25_22_46_34\L2CAP_LE_CFC_BV_07_C_2026_06_25_22_46_34.xml` | PTS sent MTU/MPS `0x0017`; no IUT-side L2CAP connection log. |
| `L2CAP/LE/CFC/BV-08-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_08_C_2026_06_25_22_46_52\L2CAP_LE_CFC_BV_08_C_2026_06_25_22_46_52.xml` | Same pattern as BV-07. |
| `L2CAP/LE/CFC/BV-09-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_09_C_2026_06_25_22_47_01\L2CAP_LE_CFC_BV_09_C_2026_06_25_22_47_01.xml` | Same pattern as BV-07. |
| `L2CAP/LE/CFC/BV-23-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_23_C_2026_06_25_22_47_10\L2CAP_LE_CFC_BV_23_C_2026_06_25_22_47_10.xml` | IUT accepted CoC, then PTS asked MMI_270 to send Command Reject; stack sent normal Disconnection Response. |
| `L2CAP/LE/CFC/BV-26-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_26_C_2026_06_25_22_48_25\L2CAP_LE_CFC_BV_26_C_2026_06_25_22_48_25.xml` | PTS sent MTU/MPS `0x0017`; no IUT-side L2CAP connection log. |
| `L2CAP/LE/CFC/BV-27-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_27_C_2026_06_25_22_48_34\L2CAP_LE_CFC_BV_27_C_2026_06_25_22_48_34.xml` | Same pattern as BV-26. |
| `L2CAP/LE/CFC/BV-28-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_28_C_2026_06_25_22_48_42\L2CAP_LE_CFC_BV_28_C_2026_06_25_22_48_42.xml` | Same pattern as BV-26. |
| `L2CAP/LE/CFC/BV-31-C` | INDCSV | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_31_C_2026_06_25_22_48_51\L2CAP_LE_CFC_BV_31_C_2026_06_25_22_48_51.xml` | Same pattern as BV-26. |
| `L2CAP/LE/CFC/BV-32-C` | FAIL | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CFC_BV_32_C_2026_06_25_23_01_40\L2CAP_LE_CFC_BV_32_C_2026_06_25_23_01_40.xml` | Requires IUT-initiated CoC during MMI_41. Current-connection action had no active handle; explicit PTS-address connect timed out. |
| `L2CAP/LE/CID/BI-01-C` | PASS | `runs\pts_profile_probe_20260625_131036\workspace\PyBlueHost_L2CAP\L2CAP\L2CAP_LE_CID_BI_01_C_2026_06_25_13_22_26\L2CAP_LE_CID_BI_01_C_2026_06_25_13_22_26.xml` | PASS from earlier probe. |

Summary: 23 expanded L2CAP active cases recorded: 7 PASS, 16 non-PASS, 0 missing XML. The existing current-expected manifest remains 8/8 PASS; this expanded probe deliberately covers cases beyond that manifest.

## Remaining Blockers

1. Custom MMI handling is still missing for prompts such as MMI_274 and MMI_270. `TSPX_use_implicit_send=TRUE` is not enough for every L2CAP prompt.
2. Several CFC cases send MTU/MPS `0x0017` and then disconnect before IUT logs an L2CAP connection. This needs HCI-level IUT trace to determine whether CSR8510 reports a connection event to the host for those runs.
3. IUT-initiated CoC cases need a reliable way to trigger the JSON controller while `RunTestCase` is blocking and while the IUT has a real active handle. The delayed-job approach works mechanically but BV-32 did not expose an active handle.
4. Command Reject behavior for BV-23 is not represented by the current LE CoC API; passing that case likely needs a test-specific raw LE signaling command or protocol behavior hook.

## Additional BI-11 Callback Probe

After the expanded table above was generated, `L2CAP/COS/CED/BI-11-C` was probed again with a PTS COM implicit-send callback. The useful logs are:

| Attempt | Result |
|---|---|
| `logs\l2cap_bi11_callback_logger_rerun_20260625_2328.log` | `SetControlClientLoggerCallback()` and `RegisterImplicitSendCallbackEx()` both returned `0`; the logger callback observed `MMI_56`, but PTS still treated the prompt as Cancel and ended FAIL before reaching `MMI_274`. |
| `logs\l2cap_bi11_comvisible_rerun_20260625_2338.log` | Re-declared the callback interfaces as COM-visible .NET interfaces; `RunTestCase()` failed with RPC error before producing a useful verdict, likely due incompatible .NET marshaling for the native `LPWSTR` response buffer. |
| `logs\l2cap_bi11_nativeptr_rerun_20260625_2342.log` | Retried with native pointer parameters for the Ex callback, but the PTS adapter was already stale and `GetPTSBluetoothAddress()` returned `HRESULT:0x849C0043`. |

Current cleanup state after the callback probes:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'PTS.exe' -or ($_.Name -in @('python.exe','uv.exe') -and $_.CommandLine -like '*pts_iut_controller.py*') }
```

returned no PTS/controller processes. `pybluehost tools info --transport=usb:0A12:0001#1` can open the CSR8510 IUT, but PTS `GetDeviceList()` still reports `USB_INTEL:InUse` and `ExitPTS()` returns an RPC failure. Continue PTS runs only after the Intel PTS dongle is released, for example by restarting PTS or re-enumerating the Intel dongle.

## Recommended Next Steps

1. Add HCI/L2CAP trace capture to `scripts\pts_iut_controller.py` runs so non-PASS CFC cases can be correlated with actual IUT-side HCI events.
2. Add a PTS implicit-send callback or a UI automation layer for Yes/No and action MMIs, especially BI-11 and BV-23.
3. Add targeted controller commands for raw LE signaling actions required by PTS action prompts.
4. After L2CAP action prompts are under control, repeat the same workspace/PICS process for GAP, GATT, SM, and RFCOMM. HCI cannot be run from this PTS install until an HCI TSS/workspace source is available.