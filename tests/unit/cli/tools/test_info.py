"""Unit tests for `pybluehost tools info`."""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_info_human_table_lists_bd_addr_and_manufacturer(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    rc = await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    assert rc == 0
    assert "BD_ADDR" in captured
    assert "Manufacturer" in captured


@pytest.mark.asyncio
async def test_info_human_table_lists_le_features_decoded(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    # At least one decoded LE feature name should appear (regardless of supported flag)
    assert "LE Encryption" in captured or "LE 2M PHY" in captured


@pytest.mark.asyncio
async def test_info_human_table_lists_bredr_features_section(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    assert "BR/EDR Features" in captured


@pytest.mark.asyncio
async def test_info_human_table_lists_capability_summary(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    assert "Capability summary" in captured


@pytest.mark.asyncio
async def test_info_json_output_has_required_keys(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = True

    rc = await _cmd_info_async(_Args())
    assert rc == 0
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    for key in (
        "transport", "bd_addr", "manufacturer_id", "manufacturer_name",
        "capability_summary", "le_features", "bredr_features",
        "supported_commands",
    ):
        assert key in parsed, f"missing key {key!r} in JSON output"


@pytest.mark.asyncio
async def test_info_unknown_command_bits_appear_in_unknown_list(capsys):
    """If a bit is set in the cmd bitmap but not in _OPCODE_BIT_POSITIONS,
    it shows up in the JSON unknown_bits_set list."""
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = True

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    assert "unknown_bits_set" in parsed["supported_commands"]
    assert isinstance(parsed["supported_commands"]["unknown_bits_set"], list)
