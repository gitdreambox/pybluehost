"""BR/EDR Secure Simple Pairing — local HCI termination.

Controller-driven: the host only responds to HCI events (IO_Capability_Request,
User_Confirmation_Request, Link_Key_Notification, Link_Key_Request).  No
application-layer crypto is required — the controller handles all SSP maths.

Allowed deps: pybluehost.hci.*, pybluehost.core.address, pairing.delegate.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
)
from pybluehost.hci.packets import HCICommand, HCI_Link_Key_Request_Reply_Command

from .delegate import PairingDelegate

# IO capability codes (Bluetooth Core Spec Vol 2 Part C §5.2.2.2)
IOCAP_DISPLAY_ONLY: int = 0x00
IOCAP_DISPLAY_YESNO: int = 0x01
IOCAP_KEYBOARD_ONLY: int = 0x02
IOCAP_NO_INPUT_NO_OUTPUT: int = 0x03

# Authentication requirements (Vol 2 Part C §5.2.2.5)
_AUTH_DEDICATED_BONDING_NO_MITM: int = 0x02   # Just Works
_AUTH_DEDICATED_BONDING_MITM: int = 0x03       # Numeric Comparison


class SspTermination:
    """Respond to SSP HCI events on behalf of a BR/EDR side in a MITM proxy.

    Parameters
    ----------
    controller:
        An HCIController (or compatible fake) that exposes the four
        ``on_io_capability_request``, ``on_user_confirmation_request``,
        ``on_link_key_notification``, and ``on_link_key_request`` listener
        registration methods plus ``send_command``.
    delegate:
        A :class:`PairingDelegate` whose ``confirm_numeric`` is called for
        User_Confirmation_Request events.
    side_name:
        Human-readable label passed to ``delegate.confirm_numeric`` (e.g.
        ``"target"`` or ``"phone"``).
    numeric:
        If *True*, advertise DisplayYesNo capability and request MITM
        protection (Numeric Comparison flow).  If *False* (default), advertise
        NoInputNoOutput (Just Works).
    """

    def __init__(
        self,
        controller,
        *,
        delegate: PairingDelegate,
        side_name: str,
        numeric: bool = False,
        key_log_path: str | Path | None = None,
    ) -> None:
        self._controller = controller
        self._delegate = delegate
        self._side_name = side_name
        self._numeric = numeric
        self._key_log_path = key_log_path
        # addr string → 16-byte link key
        self._link_keys: dict[str, bytes] = {}
        # key type of the most recent Link_Key_Notification (0x04/0x05 = SC derived;
        # 0x00-0x03 = legacy), None = not yet paired. The session mirrors the sink's SC capability from this.
        self.last_link_key_type: int | None = None
        # Load previously captured keys on startup: if the peer is already bonded,
        # Link_Key_Request returns the key directly on reconnection, so encryption ACL
        # can be established without re-pairing (real-world requirement: pair once, relay afterwards).
        if key_log_path is not None:
            self._load_keys(key_log_path)

    def _load_keys(self, path: str | Path) -> None:
        """Restore known link keys from a key log (JSONL); missing file or bad lines are only warned, not fatal."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        addr, key = rec["addr"], rec["link_key"]
                        self._link_keys[addr] = bytes.fromhex(key)
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            pass  # first run: file missing is normal
        if self._link_keys:
            logger.info("[SSP:%s] 已从 %s 恢复 %d 条 link key",
                        self._side_name, path, len(self._link_keys))

    def forget_key(self, addr: str) -> None:
        """Discard the link key for an address: remove from memory and rewrite the key-log JSONL.

        Self-healing after authentication failure (e.g. earbud-side bond expired,
        key mismatch 0x05): local key is invalidated so the next round falls back to
        unpaired SSP. JSONL keeps only SSP records (type != "ltk") for other addresses,
        preserving LTK records (type == "ltk") and ordering; case-insensitive match.
        If no path is configured or no matching record exists, only memory is cleared
        and the file is not rewritten.
        """
        target = addr.upper()
        for known in [a for a in self._link_keys if a.upper() == target]:
            del self._link_keys[known]
        if self._key_log_path is None:
            return
        try:
            with open(self._key_log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return  # file missing: memory removal is enough
        kept: list[str] = []
        removed = 0
        for line in lines:
            stripped = line.strip()
            rec = None
            if stripped:
                try:
                    rec = json.loads(stripped)
                except ValueError:
                    rec = None  # keep bad lines as-is (same tolerance as _load_keys)
            if (isinstance(rec, dict)
                    and rec.get("type") != "ltk"
                    and str(rec.get("addr", "")).upper() == target):
                removed += 1
                continue
            kept.append(line)
        if removed == 0:
            return  # no matching record: don't rewrite file
        try:
            with open(self._key_log_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
        except OSError as exc:
            # Robustness beats on-disk key persistence; failure is only logged (memory removal already took effect).
            logger.warning("forget_key 重写 key log 失败 path=%s: %s",
                           self._key_log_path, exc)

    # ------------------------------------------------------------------
    # Listener registration
    # ------------------------------------------------------------------

    def attach(self) -> None:
        """Register all four SSP event listeners on the controller."""
        self._controller.on_io_capability_request(self._on_io)
        self._controller.on_user_confirmation_request(self._on_uc)
        self._controller.on_link_key_notification(self._on_lkn)
        self._controller.on_link_key_request(self._on_lkr)

    # ------------------------------------------------------------------
    # Event handlers (coroutines — controller awaits them)
    # ------------------------------------------------------------------

    async def _on_io(self, addr: BDAddress) -> None:
        """Reply to IO_Capability_Request with our chosen IO capability."""
        io_cap = IOCAP_DISPLAY_YESNO if self._numeric else IOCAP_NO_INPUT_NO_OUTPUT
        auth_req = _AUTH_DEDICATED_BONDING_MITM if self._numeric else _AUTH_DEDICATED_BONDING_NO_MITM
        logger.info("[SSP:%s] IO_Capability_Request from %s -> reply io_cap=0x%02x auth=0x%02x",
                    self._side_name, addr, io_cap, auth_req)
        params = (
            addr.to_hci()          # bd_addr must be HCI little-endian wire order (not addr.address big-endian)
            + bytes([io_cap])
            + bytes([0x00])      # OOB data not present
            + bytes([auth_req])
        )
        await self._controller.send_command(
            HCICommand(opcode=HCI_IO_CAPABILITY_REQUEST_REPLY, parameters=params)
        )

    async def _on_uc(self, addr: BDAddress, value: int) -> None:
        """Reply to User_Confirmation_Request after asking the delegate."""
        logger.info("[SSP:%s] User_Confirmation_Request from %s value=%d", self._side_name, addr, value)
        accept = await self._delegate.confirm_numeric(self._side_name, value)
        if accept:
            opcode = HCI_USER_CONFIRMATION_REQUEST_REPLY
        else:
            opcode = HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY
        await self._controller.send_command(
            HCICommand(opcode=opcode, parameters=addr.to_hci())
        )

    def _on_lkn(self, addr: BDAddress, key: bytes, key_type: int) -> None:
        """Store a newly-negotiated link key (sync — no HCI reply needed)."""
        logger.info("[SSP:%s] Link_Key_Notification addr=%s key=%s type=0x%02x",
                    self._side_name, addr, key.hex(), key_type)
        self._link_keys[str(addr)] = key
        self.last_link_key_type = key_type
        if self._key_log_path is not None:
            # Persist key in HCI wire order as-is; compare with peer-side trace and reverse only if order is uncertain.
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "side": self._side_name,
                "addr": str(addr),
                "link_key": key.hex(),
                "key_type": key_type,
            }
            try:
                with open(self._key_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            except OSError as exc:
                # Pairing robustness beats on-disk key persistence; failure is only logged, not raised.
                logger.warning(
                    "link key 落盘失败 path=%s: %s", self._key_log_path, exc
                )

    async def _on_lkr(self, addr: BDAddress) -> None:
        """Reply to Link_Key_Request with stored key or a negative reply."""
        key = self._link_keys.get(str(addr))
        logger.info("[SSP:%s] Link_Key_Request from %s -> %s",
                    self._side_name, addr, "reply key" if key is not None else "negative reply")
        if key is not None:
            # Use dedicated command class (bd_addr reversed to little-endian wire order), same as classic/gap.py.
            await self._controller.send_command(
                HCI_Link_Key_Request_Reply_Command(bd_addr=addr, link_key=key)
            )
        else:
            await self._controller.send_command(
                HCICommand(opcode=HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY, parameters=addr.to_hci())
            )
