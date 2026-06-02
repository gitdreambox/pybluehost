"""BLE advertising impersonation — apply a ClonedIdentity to a downstream controller.

Sends the raw HCI advertising command sequence to make the downstream controller
broadcast with the captured target's advertising payload (and optionally its address).

Allowed imports: pybluehost.cli.app.mitm.recon, pybluehost.hci.controller,
pybluehost.hci.constants, pybluehost.hci.packets.
No l2cap/ble/classic/gap/profiles/stack.
"""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING

from pybluehost.hci.constants import (
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_ADVERTISING_DATA,
    HCI_LE_SET_ADVERTISING_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_RESPONSE_DATA,
)
from pybluehost.hci.packets import HCICommand

if TYPE_CHECKING:
    from pybluehost.cli.app.mitm.recon import ClonedIdentity
    from pybluehost.hci.controller import HCIController

logger = logging.getLogger(__name__)

_ADV_DATA_MAX = 31
# 广播间隔(单位 0.625ms);0x00A0 = 160 → 100ms。
_ADV_INTERVAL_DEFAULT = 0x00A0


def _addr_str_to_le_bytes(addr: str) -> bytes:
    """Convert "AA:BB:CC:DD:EE:FF" to 6 bytes in little-endian (reversed) order."""
    parts = [int(x, 16) for x in addr.split(":")]
    return bytes(reversed(parts))


def _build_adv_data_payload(data: bytes) -> bytes:
    """Build the 32-byte Set Advertising Data / Set Scan Response Data parameter.

    Format: significant_length(1) || data(≤31) || zero-padding to reach 32 bytes total.
    Truncates data to 31 bytes with a warning if oversized.
    """
    if len(data) > _ADV_DATA_MAX:
        logger.warning(
            "Advertising data length %d exceeds 31-byte limit; truncating.", len(data)
        )
        data = data[:_ADV_DATA_MAX]
    sig_len = len(data)
    return bytes([sig_len]) + data + bytes(_ADV_DATA_MAX - len(data))


async def start_impersonation(
    controller: "HCIController",
    identity: "ClonedIdentity",
    *,
    clone_address: bool = False,
) -> None:
    """Apply identity to the downstream controller and start advertising.

    Default (clone_address=False): advertise with the controller's OWN address,
    cloning only adv_data + scan_response (the phone connects by content).
    clone_address=True: set the controller's random address to the target's
    address first (LE byte order), and advertise as random.
    """
    # 1. Optionally set random address
    if clone_address:
        le_addr = _addr_str_to_le_bytes(identity.address)
        await controller.send_command(
            HCICommand(opcode=HCI_LE_SET_RANDOM_ADDRESS, parameters=le_addr)
        )
        own_addr_type = 0x01  # random
    else:
        own_addr_type = 0x00  # public

    # 2. Set advertising parameters
    # adv_interval_min(2 LE) adv_interval_max(2 LE) adv_type(1) own_addr_type(1)
    # peer_addr_type(1) peer_addr(6) adv_channel_map(1) adv_filter_policy(1)
    adv_params = (
        struct.pack("<HH", _ADV_INTERVAL_DEFAULT, _ADV_INTERVAL_DEFAULT)  # interval min, max
        + bytes([0x00])                      # adv_type: ADV_IND
        + bytes([own_addr_type])             # own_addr_type
        + bytes([0x00])                      # peer_addr_type: public
        + bytes(6)                           # peer_addr: zeroed
        + bytes([0x07])                      # adv_channel_map: all channels
        + bytes([0x00])                      # adv_filter_policy: none
    )
    await controller.send_command(
        HCICommand(opcode=HCI_LE_SET_ADVERTISING_PARAMS, parameters=adv_params)
    )

    # 3. Set advertising data
    adv_payload = _build_adv_data_payload(identity.adv_data)
    await controller.send_command(
        HCICommand(opcode=HCI_LE_SET_ADVERTISING_DATA, parameters=adv_payload)
    )

    # 4. Set scan response data (only if non-empty)
    if identity.scan_response:
        scan_rsp_payload = _build_adv_data_payload(identity.scan_response)
        await controller.send_command(
            HCICommand(opcode=HCI_LE_SET_SCAN_RESPONSE_DATA, parameters=scan_rsp_payload)
        )

    # 5. Enable advertising
    await controller.send_command(
        HCICommand(opcode=HCI_LE_SET_ADVERTISE_ENABLE, parameters=bytes([0x01]))
    )
