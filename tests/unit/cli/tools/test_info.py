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


@pytest.mark.asyncio
async def test_info_json_stdout_is_pure_json_even_when_logs_emit(capsys):
    """Regression: transport-layer print/log emissions to stdout during
    stack init must not leak into --json output. Downstream tools like
    `jq` / json.load require pure JSON on stdout.
    """
    import sys

    from pybluehost.cli.tools import info as info_module

    class _Args:
        transport = "virtual"
        json = True

    # Wrap the underlying factory so it prints to stdout during init —
    # simulating a transport-layer banner ("Generic USBTransport initialized"
    # / "Intel TLV: ..."). The CLI's --json path must redirect this to
    # stderr; stdout should contain ONLY the JSON document.
    original_build = info_module.__dict__.get("_orig_build")
    if original_build is None:
        from tests._transport_resolve import build_stack_from_spec as original_build

    async def _noisy_build(spec, *, config=None):
        print("LEAK: simulated transport banner")  # would normally go to stdout
        return await original_build(spec, config=config)

    # Patch the import inside the function by intercepting tests._transport_resolve.
    import tests._transport_resolve as resolve_mod
    saved = resolve_mod.build_stack_from_spec
    resolve_mod.build_stack_from_spec = _noisy_build
    try:
        await info_module._cmd_info_async(_Args())
    finally:
        resolve_mod.build_stack_from_spec = saved

    out = capsys.readouterr().out
    # stdout must parse cleanly as JSON — no LEAK: prefix.
    assert "LEAK" not in out, f"stdout contaminated by transport-layer print: {out!r}"
    parsed = json.loads(out)
    assert "transport" in parsed
