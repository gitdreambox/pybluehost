"""_enable_secure_connections: send 0x0C7A when supported; warn and fall back (do not send) when not."""
import logging

from pybluehost.cli.app.mitm.controllers import _enable_secure_connections
from pybluehost.hci.constants import HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT


class _Cmds:
    def __init__(self, supported: bool) -> None:
        self._supported = supported

    def has(self, opcode: int) -> bool:
        return self._supported


class _FakeController:
    def __init__(self, supported: bool) -> None:
        self._supported_commands = _Cmds(supported)
        self.sent = []

    async def send_command(self, cmd):
        self.sent.append(cmd)
        return None


async def test_secure_connections_sent_when_supported():
    ctrl = _FakeController(supported=True)
    await _enable_secure_connections(ctrl, "upstream")
    assert len(ctrl.sent) == 1
    assert ctrl.sent[0].opcode == HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT
    # secure_connections_host_support=0x01
    assert ctrl.sent[0].parameters == bytes([0x01])


async def test_secure_connections_skipped_when_unsupported(caplog):
    ctrl = _FakeController(supported=False)
    with caplog.at_level(logging.WARNING):
        await _enable_secure_connections(ctrl, "upstream")
    assert ctrl.sent == []
    assert any("Secure Connections" in r.message for r in caplog.records)
