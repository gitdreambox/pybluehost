"""`pybluehost app pts-iut` — interactive PTS IUT REPL."""
import argparse
import asyncio

from pybluehost.cli._lifecycle import add_common_arguments, run_app_command, trace_kwargs_from_args


def register_pts_iut_command(subparsers: argparse._SubParsersAction) -> None:
    """Register the pts-iut subcommand."""
    p = subparsers.add_parser("pts-iut", help="Interactive PTS IUT control console (REPL)")
    add_common_arguments(p)
    p.add_argument(
        "--pts-disable-conn-updates",
        action="store_true",
        dest="pts_disable_conn_updates",
        default=False,
        help="Suppress LE conn-param-update auto-sends (defensive guard)",
    )
    p.add_argument(
        "--pts-secure-pair-only",
        action="store_true",
        dest="pts_secure_pair_only",
        default=False,
        help="Reject legacy pairing; SC-only mode",
    )
    p.add_argument(
        "--pts-disable-sdp-on-le-pair",
        action="store_true",
        dest="pts_disable_sdp_on_le_pair",
        default=False,
        help="Suppress auto SDP/CTKD-classic after LE pair",
    )
    p.add_argument(
        "--pts-smp-options",
        type=str,
        default=None,
        dest="pts_smp_options",
        help="Override SMP Pairing Request body — hex string, 6 bytes (e.g. 04000D100303)",
    )
    p.add_argument(
        "--pts-smp-failure-at",
        type=str,
        default=None,
        dest="pts_smp_failure_at",
        help="Inject SMPPairingFailed at named stage (e.g. confirm_value or 05:confirm_value)",
    )
    p.set_defaults(
        func=lambda args: asyncio.run(
            run_app_command(
                args.transport,
                _pts_iut_main,
                pts_config=_pts_config_from_args(args),
                **trace_kwargs_from_args(args),
            )
        )
    )


def _pts_config_from_args(args):
    """Create PTSModeConfig from CLI args."""
    from pybluehost.pts.config import PTSModeConfig

    if not any(
        [
            args.pts_disable_conn_updates,
            args.pts_secure_pair_only,
            args.pts_disable_sdp_on_le_pair,
            args.pts_smp_options,
            args.pts_smp_failure_at,
        ]
    ):
        return None
    return PTSModeConfig(
        disable_conn_updates=args.pts_disable_conn_updates,
        secure_pair_only=args.pts_secure_pair_only,
        disable_sdp_on_le_pair=args.pts_disable_sdp_on_le_pair,
        smp_options=bytes.fromhex(args.pts_smp_options) if args.pts_smp_options else None,
        smp_failure_at=args.pts_smp_failure_at,
    )


async def _pts_iut_main(stack, stop_event):
    """Main REPL entry point."""
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.repl import run_repl

    actions = IutActions(stack)
    print(f"PyBlueHost PTS IUT — connected via {stack.config}")
    print("Type 'help' for commands; 'quit' or Ctrl-D to exit.")
    repl_task = asyncio.create_task(run_repl(actions))
    stop_task = asyncio.create_task(stop_event.wait())
    done, _pending = await asyncio.wait(
        {repl_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if stop_task in done:
        repl_task.cancel()
    else:
        stop_task.cancel()
