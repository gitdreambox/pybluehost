"""'app mitm' —— 目标设备与手机之间的 BLE/BR ACL 透传中间人(授权测试专用)。"""
from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RelaySpec:
    mode: str  # "le" | "bredr"


def default_btsnoop_name() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"mitm-{ts}.btsnoop"


def _select_delegate(pairing: str):
    from pybluehost.cli.app.mitm.pairing.delegate import (
        AutoConfirmDelegate,
        InteractiveNumericDelegate,
    )
    if pairing == "numeric":
        return InteractiveNumericDelegate()
    return AutoConfirmDelegate()


def build_relays_from_args(args) -> list[RelaySpec]:
    if args.transport_mode == "both":
        return [RelaySpec("le"), RelaySpec("bredr")]
    return [RelaySpec(args.transport_mode)]


def register_mitm_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "mitm",
        help="BLE/BR ACL 透传中间人(授权测试专用)",
    )
    p.add_argument("--upstream", required=True, help="连目标侧 transport (如 usb:vendor=intel)")
    p.add_argument("--downstream", required=True, help="对手机伪装侧 transport (如 usb:index=1)")
    p.add_argument("--target", help="目标地址 AA:BB:.. (或用 --target-name)")
    p.add_argument("--target-name", help="按名字匹配目标")
    p.add_argument(
        "--transport-mode",
        choices=["le", "bredr", "both"],
        default="both",
        help="透传哪种链路(默认 both)",
    )
    p.add_argument("--clone-address", action="store_true", help="套用目标地址(BR 需可写芯片)")
    p.add_argument("--btsnoop", help="btsnoop 输出路径(默认按时间戳命名)")
    p.add_argument(
        "--pairing", choices=["just-works", "numeric"], default="just-works"
    )
    p.set_defaults(func=lambda args: asyncio.run(_mitm_main(args)))


async def _mitm_main(args: argparse.Namespace) -> None:
    import asyncio as _asyncio
    from pybluehost.cli.app.mitm.controllers import open_controller_pair
    from pybluehost.cli.app.mitm.orchestrator import MitmRelay

    logger.warning("⚠ MITM 仅限授权测试:确保你对目标设备与手机均有合法授权。")
    btsnoop = args.btsnoop or default_btsnoop_name()
    pairing = args.pairing
    numeric = (pairing == "numeric")
    specs = build_relays_from_args(args)

    pair = await open_controller_pair(args.upstream, args.downstream)
    relays = [
        MitmRelay(
            pair,
            target_addr=args.target,
            target_name=args.target_name,
            btsnoop=(btsnoop if len(specs) == 1 else f"{s.mode}-{btsnoop}"),
            clone_address=args.clone_address,
            delegate=_select_delegate(pairing),
            mode=s.mode,
            numeric=numeric,
        )
        for s in specs
    ]
    # NOTE (double-close): In "both" mode, two MitmRelay instances share the same
    # ControllerPair.  Each relay's teardown() calls pair.close(), which calls
    # _close_transport() for each transport.  _close_transport() wraps the close()
    # call in a try/except and swallows any exception, so repeated calls are safe.
    # We therefore rely on that guard and let each relay call teardown() normally,
    # avoiding the complexity of skipping pair.close() in one of them.
    try:
        for r in relays:
            await r.run_recon()
            await r.run_impersonate()
        await _asyncio.gather(*(r.run_relay() for r in relays))
    finally:
        for r in relays:
            await r.teardown()
