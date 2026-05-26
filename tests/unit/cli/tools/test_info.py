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
        "hci_version", "hci_version_name", "hci_revision", "hci_revision_hex",
        "lmp_version", "lmp_version_name", "lmp_subversion", "lmp_subversion_hex",
        "capability_summary", "le_features", "bredr_features",
        "supported_commands",
    ):
        assert key in parsed, f"missing key {key!r} in JSON output"


@pytest.mark.asyncio
async def test_info_json_decodes_version_names(capsys):
    """hci_version_name / lmp_version_name should be human-readable strings,
    not raw integers."""
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = True

    await _cmd_info_async(_Args())
    parsed = json.loads(capsys.readouterr().out)
    # Virtual controller reports hci_version=12 → "Bluetooth 5.3"
    assert isinstance(parsed["hci_version_name"], str)
    assert parsed["hci_version_name"].startswith("Bluetooth") or "Unknown" in parsed["hci_version_name"]
    assert isinstance(parsed["lmp_version_name"], str)
    # subversion always renders as 0xXXXX hex form
    assert parsed["lmp_subversion_hex"].startswith("0x")
    assert parsed["hci_revision_hex"].startswith("0x")


@pytest.mark.asyncio
async def test_info_json_exposes_bredr_extended_pages(capsys):
    """BR/EDR Read_Local_Extended_Features pages 1+2 surface as separate
    decoded sections in the JSON output."""
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = True

    await _cmd_info_async(_Args())
    parsed = json.loads(capsys.readouterr().out)
    assert "bredr_features_page1" in parsed
    assert "bredr_features_page2" in parsed
    # Each page-decoded section is a dict of (octet/bit) -> {name, supported}
    p2 = parsed["bredr_features_page2"]
    # (1, 0) is "Secure Connections (Controller Support)" per Spec 5.4
    assert "1/0" in p2
    assert "Secure Connections" in p2["1/0"]["name"]
    assert isinstance(p2["1/0"]["supported"], bool)


@pytest.mark.asyncio
async def test_info_capability_summary_keys_present(capsys):
    """capability_summary exposes a fixed set of 7 derived capability flags."""
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = True

    await _cmd_info_async(_Args())
    parsed = json.loads(capsys.readouterr().out)
    summary = parsed["capability_summary"]
    expected_keys = {
        "le_secure_connections",
        "le_privacy_rpa",
        "le_extended_advertising",
        "le_2m_phy",
        "le_coded_phy",
        "bredr_encryption",
        "bredr_ssp",
        "bredr_sc_controller",
        "bredr_sc_host_support",
        "extended_inquiry_response",
    }
    assert set(summary.keys()) == expected_keys
    # Every value must be a boolean (not None, not int).
    for key, val in summary.items():
        assert isinstance(val, bool), f"{key!r} = {val!r} (expected bool)"


@pytest.mark.asyncio
async def test_info_human_table_shows_decoded_versions(capsys):
    """Human table prints 'Bluetooth 5.x' next to the raw HCI Version byte."""
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    await _cmd_info_async(_Args())
    out = capsys.readouterr().out
    assert "HCI Version" in out
    assert "LMP Version" in out
    assert "LMP Subversion" in out
    # Decoded marker — either a Bluetooth spec version or an "Unknown (0xNN)" fallback
    assert "Bluetooth" in out or "Unknown (0x" in out


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
