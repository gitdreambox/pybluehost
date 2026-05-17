"""HCIController.initialize() conditionally enables BR/EDR Secure Connections."""
from __future__ import annotations

from pybluehost.ble.security import SecurityConfig
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCI_Write_Secure_Connections_Host_Support_Command
from pybluehost.hci.virtual import VirtualController


async def test_initialize_skips_write_sc_when_config_off():
    vc, host_t = await VirtualController.create()
    sent: list = []
    hci = HCIController(
        transport=host_t, trace=None, command_timeout=2.0,
        security_config=SecurityConfig(enable_secure_connections=False),
    )
    original_send = hci.send_command

    async def _capture(cmd):
        sent.append(cmd)
        return await original_send(cmd)
    hci.send_command = _capture
    try:
        await hci.initialize()
        assert not any(isinstance(c, HCI_Write_Secure_Connections_Host_Support_Command) for c in sent)
    finally:
        await host_t.close()


async def test_initialize_issues_write_sc_when_config_on():
    vc, host_t = await VirtualController.create()
    sent: list = []
    hci = HCIController(
        transport=host_t, trace=None, command_timeout=2.0,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    original_send = hci.send_command

    async def _capture(cmd):
        sent.append(cmd)
        return await original_send(cmd)
    hci.send_command = _capture
    try:
        await hci.initialize()
        sc_cmds = [c for c in sent if isinstance(c, HCI_Write_Secure_Connections_Host_Support_Command)]
        assert len(sc_cmds) == 1
        assert sc_cmds[0].secure_connections_host_support == 0x01
    finally:
        await host_t.close()


async def test_initialize_with_no_security_config_skips_sc():
    """Default behavior: security_config=None -> no SC enabling, same as before this Plan."""
    vc, host_t = await VirtualController.create()
    sent: list = []
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    original_send = hci.send_command

    async def _capture(cmd):
        sent.append(cmd)
        return await original_send(cmd)
    hci.send_command = _capture
    try:
        await hci.initialize()
        assert not any(isinstance(c, HCI_Write_Secure_Connections_Host_Support_Command) for c in sent)
    finally:
        await host_t.close()
