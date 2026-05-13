"""GATTClient retries read_characteristic/write_characteristic once after
auto-pair on ATT Insufficient_Encryption (0x0F)."""
from __future__ import annotations

import pytest


async def test_gatt_read_triggers_pair_and_retry():
    """GATT read_characteristic receiving ATT 0x0F triggers pair, then retries."""
    from pybluehost.ble.att import ATTError
    from pybluehost.ble.gatt import GATTClient

    calls: list = []

    class FakeBearer:
        async def read(self, handle: int) -> bytes:
            calls.append(handle)
            if len(calls) == 1:
                raise ATTError(0x0F)
            return b"OK"

        async def write(self, handle: int, value: bytes) -> None:  # pragma: no cover
            pass

    paired: list = []

    async def fake_pair(handle: int) -> None:
        paired.append(handle)

    client = GATTClient(
        bearer=FakeBearer(),
        connection_handle=0x0040,
        on_insufficient_encryption=fake_pair,
    )
    value = await client.read_characteristic(0x0010)
    assert value == b"OK"
    assert calls == [0x0010, 0x0010]
    assert paired == [0x0040]


async def test_gatt_read_does_not_retry_more_than_once():
    """If retry still fails with 0x0F, the second exception propagates."""
    from pybluehost.ble.att import ATTError
    from pybluehost.ble.gatt import GATTClient

    calls: list = []

    class FakeBearer:
        async def read(self, handle: int) -> bytes:
            calls.append(handle)
            raise ATTError(0x0F)

        async def write(self, handle: int, value: bytes) -> None:  # pragma: no cover
            pass

    async def fake_pair(handle: int) -> None:
        pass

    client = GATTClient(
        bearer=FakeBearer(),
        connection_handle=0x0040,
        on_insufficient_encryption=fake_pair,
    )
    with pytest.raises(ATTError):
        await client.read_characteristic(0x0010)
    assert len(calls) == 2  # one original + one retry
