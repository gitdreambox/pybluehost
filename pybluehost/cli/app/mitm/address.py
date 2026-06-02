"""Optional BD_ADDR cloning for MITM impersonation.

Only needed for ``--clone-address`` in BR reconnect / address-pinned scenarios.
Vendor ``Write_BD_ADDR`` differs per chip; this module probes the downstream
chip's manufacturer ID and either sends the matching command or raises
``AddressCloneUnsupported`` with a clear diagnostic message.
"""

from pybluehost.hci.packets import HCICommand

_BROADCOM_WRITE_BDADDR = 0xFC01

_MFR_BROADCOM = 0x000F
_MFR_CSR = 0x000A
_MFR_INTEL = 0x0002
_MFR_REALTEK = 0x005D


class AddressCloneUnsupported(Exception):
    """Downstream chip cannot write BD_ADDR (e.g. Intel OTP-locked)."""


def _addr_str_to_le_bytes(addr: str) -> bytes:
    """Convert "AA:BB:CC:DD:EE:FF" to 6 little-endian bytes."""
    parts = [int(x, 16) for x in addr.split(":")]
    return bytes(reversed(parts))


def build_broadcom_write_bdaddr(addr: str) -> HCICommand:
    """Build the Broadcom vendor Write_BD_ADDR (0xFC01) command."""
    return HCICommand(opcode=_BROADCOM_WRITE_BDADDR, parameters=_addr_str_to_le_bytes(addr))


async def clone_bd_addr(controller, addr: str) -> None:
    """Probe the downstream chip vendor and send the matching Write_BD_ADDR.

    Broadcom → 0xFC01 (temporary, reverts on power cycle).
    Intel → AddressCloneUnsupported (OTP-locked).
    CSR/Realtek → AddressCloneUnsupported for now (PSKEY/vendor write not
      implemented; message suggests a Broadcom dongle).
    Unknown manufacturer → AddressCloneUnsupported with a clear message.
    """
    mfr = controller.manufacturer_id()
    if mfr == _MFR_BROADCOM:
        await controller.send_command(build_broadcom_write_bdaddr(addr))
        return
    if mfr == _MFR_INTEL:
        raise AddressCloneUnsupported(
            "Intel 控制器 BD_ADDR OTP 锁死,无法克隆地址;伪装侧请改用 Broadcom dongle。"
        )
    if mfr is not None:
        raise AddressCloneUnsupported(
            f"manufacturer_id=0x{mfr:04X} 不支持 Write_BD_ADDR;"
            "伪装侧推荐 Broadcom(0xFC01)。"
        )
    raise AddressCloneUnsupported(
        "无法识别控制器厂商,Write_BD_ADDR 不可用;伪装侧推荐 Broadcom。"
    )
