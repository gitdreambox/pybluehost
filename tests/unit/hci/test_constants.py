"""Tests for HCI constants: opcodes, event codes, error codes."""

from pybluehost.hci.constants import (
    make_opcode,
    ogf_ocf,
    OGF,
    HCI_RESET,
    HCI_READ_LOCAL_VERSION,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_SET_SCAN_ENABLE,
    EventCode,
    LEMetaSubEvent,
    ErrorCode,
    HCI_COMMAND_PACKET,
    HCI_ACL_PACKET,
    HCI_SCO_PACKET,
    HCI_EVENT_PACKET,
    HCI_ISO_PACKET,
)


def test_opcode_construction():
    assert make_opcode(OGF.CONTROLLER_BB, 0x03) == 0x0C03  # HCI_Reset
    assert make_opcode(OGF.LE, 0x0C) == 0x200C  # LE_Set_Scan_Enable


def test_ogf_ocf_round_trip():
    opcode = 0x0406
    ogf, ocf = ogf_ocf(opcode)
    assert ogf == 0x01
    assert ocf == 0x06


def test_ogf_ocf_round_trip_all_named():
    for opcode in [HCI_RESET, HCI_READ_BD_ADDR, HCI_LE_SET_SCAN_ENABLE]:
        ogf, ocf = ogf_ocf(opcode)
        assert make_opcode(ogf, ocf) == opcode


def test_named_opcodes():
    assert HCI_RESET == 0x0C03
    assert HCI_READ_BD_ADDR == 0x1009
    assert HCI_READ_LOCAL_VERSION == 0x1001
    assert HCI_READ_BUFFER_SIZE == 0x1005
    assert HCI_LE_READ_BUFFER_SIZE == 0x2002
    assert HCI_LE_SET_SCAN_ENABLE == 0x200C


def test_event_codes():
    assert EventCode.COMMAND_COMPLETE == 0x0E
    assert EventCode.COMMAND_STATUS == 0x0F
    assert EventCode.CONNECTION_COMPLETE == 0x03
    assert EventCode.DISCONNECTION_COMPLETE == 0x05
    assert EventCode.LE_META == 0x3E
    assert EventCode.VENDOR_SPECIFIC == 0xFF


def test_le_meta_sub_events():
    assert LEMetaSubEvent.LE_CONNECTION_COMPLETE == 0x01
    assert LEMetaSubEvent.LE_ADVERTISING_REPORT == 0x02
    assert LEMetaSubEvent.LE_CONNECTION_UPDATE_COMPLETE == 0x03
    assert LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE == 0x0A


def test_periodic_advertising_sub_events():
    """Core 6.3 Vol 4 Part E §7.7.65 numbers these 0x0E/0x0F/0x10/0x18.

    The periodic cluster sat one or two places high across the board
    (0x10/0x11/0x19), which put Sync Established on Sync Lost's code and left
    0x0E — the code a controller actually reports — matching no branch at all.
    Pin all four against the spec table so the block cannot drift again.
    """
    assert LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED == 0x0E
    assert LEMetaSubEvent.LE_PERIODIC_ADVERTISING_REPORT == 0x0F
    assert LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_LOST == 0x10
    assert LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED == 0x18


def test_error_codes():
    assert ErrorCode.SUCCESS == 0x00
    assert ErrorCode.UNKNOWN_COMMAND == 0x01
    assert ErrorCode.CONNECTION_TIMEOUT == 0x08
    assert ErrorCode.UNSUPPORTED_FEATURE == 0x11
    assert ErrorCode.REMOTE_USER_TERMINATED == 0x13


def test_h4_packet_types():
    assert HCI_COMMAND_PACKET == 0x01
    assert HCI_ACL_PACKET == 0x02
    assert HCI_SCO_PACKET == 0x03
    assert HCI_EVENT_PACKET == 0x04
    assert HCI_ISO_PACKET == 0x05


def test_periodic_advertising_sync_transfer_ocfs_match_the_spec():
    """The PAST family OCFs (Vol 4 Part E §7.8.89–7.8.92), cross-checked against
    Zephyr's ``BT_HCI_OP_LE_*`` table.

    This file previously had 0x49 for Sync Transfer and 0x5A for "Set PAST
    Parameters" — both wrong. Sending 0x5A expecting the *parameters* command
    actually issues a Sync Transfer, whose third field is a Sync_Handle: our
    body put 0x01F4 there and the controller answered "Unknown Advertising
    Identifier" (0x42), which is exactly what GAP/PADV hit on air.
    """
    from pybluehost.hci.constants import (
        HCI_LE_PERIODIC_ADVERTISING_SET_INFO_TRANSFER,
        HCI_LE_PERIODIC_ADVERTISING_SYNC_TRANSFER,
        HCI_LE_SET_DEFAULT_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS,
        HCI_LE_SET_PERIODIC_ADVERTISING_RECEIVE_ENABLE,
        HCI_LE_SET_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS,
    )

    assert HCI_LE_SET_PERIODIC_ADVERTISING_RECEIVE_ENABLE == 0x2059
    assert HCI_LE_PERIODIC_ADVERTISING_SYNC_TRANSFER == 0x205A
    # §7.8.90, the *source* direction: the command that actually puts
    # synchronization information on air. It was missing from this stack, so
    # GAP/PADV/PAST answered every WID Ok and never transferred anything.
    assert HCI_LE_PERIODIC_ADVERTISING_SET_INFO_TRANSFER == 0x205B
    assert HCI_LE_SET_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS == 0x205C
    assert HCI_LE_SET_DEFAULT_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS == 0x205D


def test_default_le_event_mask_unmasks_the_periodic_advertising_family():
    """The LE Event Mask must cover every event the stack consumes.

    The controller "shall not generate" an event whose mask bit is clear
    (Vol 4 Part E §7.8.1) — so a bit that is missing here is not a hint, it is
    a guarantee that the event never arrives, even when the command that
    triggers it succeeded. An init-time mask of 0x1F (bits 0-4) silenced
    GAP/PADV outright: Create_Sync answered Command Status 0x00 and then
    nothing ever came, because Extended Advertising Report (bit 12) and every
    periodic-advertising event (bits 13/14/15/23) were forbidden.
    """
    from pybluehost.hci.constants import DEFAULT_LE_EVENT_MASK, LEEventMaskBit

    for bit in (
        LEEventMaskBit.LE_CONNECTION_COMPLETE,
        LEEventMaskBit.LE_ADVERTISING_REPORT,
        LEEventMaskBit.LE_CONNECTION_UPDATE_COMPLETE,
        LEEventMaskBit.LE_READ_REMOTE_FEATURES_PAGE_0_COMPLETE,
        LEEventMaskBit.LE_LONG_TERM_KEY_REQUEST,
        LEEventMaskBit.LE_EXTENDED_ADVERTISING_REPORT,
        LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED,
        LEEventMaskBit.LE_PERIODIC_ADVERTISING_REPORT,
        LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_LOST,
        LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED,
        # GAP/BIS/BBM: the BIG the IUT creates reports its BIS connection
        # handles here; teardown reports LE BIG Terminate. No bit, no event —
        # LE_Create_BIG would answer Command Status 0x00 and then go silent
        # (same shape as the GAP/PADX mask bug).
        LEEventMaskBit.LE_CREATE_BIG_COMPLETE,
        LEEventMaskBit.LE_TERMINATE_BIG_COMPLETE,
    ):
        assert DEFAULT_LE_EVENT_MASK & bit, f"mask is missing bit {bit!r}"

    # Wire form: the 8-byte little-endian mask HCI_Set_Event_Mask carries.
    assert DEFAULT_LE_EVENT_MASK.to_bytes(8, "little") == b"\x1F\xF0\x80\x0C\x00\x00\x00\x00"


def test_default_le_event_mask_omits_the_events_we_cannot_answer():
    """Two deliberately-clear bits, each for a reason worth not re-learning.

    Bit 5 (Remote Connection Parameter Request) obliges the host to reply; we
    do not implement the reply, so unmasking it would stall the peer's LL
    procedure. Bit 9 (Enhanced Connection Complete) *replaces* the legacy
    Connection Complete on every connection, which would change the hot path
    of every test case at once.
    """
    from pybluehost.hci.constants import DEFAULT_LE_EVENT_MASK, LEEventMaskBit

    assert not DEFAULT_LE_EVENT_MASK & LEEventMaskBit.LE_REMOTE_CONNECTION_PARAMETER_REQUEST
    assert not DEFAULT_LE_EVENT_MASK & LEEventMaskBit.LE_ENHANCED_CONNECTION_COMPLETE


def test_le_event_mask_bit_n_is_le_meta_subevent_n_plus_1():
    """Bit *n* of the mask enables LE Meta sub-event code *n + 1*.

    The two tables are offset by one (§7.7.65 vs §7.8.1), which is the kind of
    thing that is easy to get right once and wrong every time after by hand.
    """
    from pybluehost.hci.constants import LEEventMaskBit, LEMetaSubEvent

    pairs = [
        (LEEventMaskBit.LE_CONNECTION_COMPLETE, LEMetaSubEvent.LE_CONNECTION_COMPLETE),
        (LEEventMaskBit.LE_ADVERTISING_REPORT, LEMetaSubEvent.LE_ADVERTISING_REPORT),
        (
            LEEventMaskBit.LE_ENHANCED_CONNECTION_COMPLETE,
            LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE,
        ),
        (
            LEEventMaskBit.LE_EXTENDED_ADVERTISING_REPORT,
            LEMetaSubEvent.LE_EXTENDED_ADVERTISING_REPORT,
        ),
        (
            LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED,
            LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED,
        ),
        (
            LEEventMaskBit.LE_PERIODIC_ADVERTISING_REPORT,
            LEMetaSubEvent.LE_PERIODIC_ADVERTISING_REPORT,
        ),
        (
            LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_LOST,
            LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_LOST,
        ),
        (
            LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED,
            LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED,
        ),
        (
            LEEventMaskBit.LE_CREATE_BIG_COMPLETE,
            LEMetaSubEvent.LE_CREATE_BIG_COMPLETE,
        ),
        (
            LEEventMaskBit.LE_TERMINATE_BIG_COMPLETE,
            LEMetaSubEvent.LE_TERMINATE_BIG_COMPLETE,
        ),
    ]

    for mask_bit, subevent in pairs:
        assert mask_bit.bit_length() == subevent.value, (
            f"{mask_bit.name} should be bit {subevent.value - 1} "
            f"to enable sub-event 0x{subevent.value:02X}"
        )
