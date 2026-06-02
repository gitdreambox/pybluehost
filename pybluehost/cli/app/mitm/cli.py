"""'app mitm' —— 目标设备与手机之间的 BLE/BR ACL 透传中间人(授权测试专用)。"""
from __future__ import annotations

import argparse
import asyncio
import logging

logger = logging.getLogger(__name__)


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
    from pybluehost.cli.app.mitm.controllers import open_controller_pair
    from pybluehost.cli.app.mitm.orchestrator import MitmRelay

    pair = await open_controller_pair(args.upstream, args.downstream)
    relay = MitmRelay(
        pair,
        target_addr=args.target,
        target_name=args.target_name,
        btsnoop=args.btsnoop,
        clone_address=args.clone_address,
    )
    try:
        await relay.run_recon()
        await relay.run_impersonate()
        await relay.run_relay()
    finally:
        await relay.teardown()
