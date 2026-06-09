"""`pybluehost tools pics-gen` — generate PICS draft YAML files from a capability dump."""
import argparse
import json
import sys
from pathlib import Path


def register_pics_gen_command(subparsers: argparse._SubParsersAction) -> None:
    """Register the pics-gen subcommand."""
    p = subparsers.add_parser(
        "pics-gen", help="Generate PICS draft YAML files from a PyBlueHost capability dump"
    )
    p.add_argument(
        "--capability-file",
        "-c",
        required=True,
        help="Path to capability JSON (e.g. docs/hardware/intel-BE200.json)",
    )
    p.add_argument(
        "--output-dir",
        "-o",
        default="docs/pts/pics",
        help="Where to write <group>.draft.yaml files (default: docs/pts/pics)",
    )
    p.set_defaults(func=_run)


def _run(args) -> int:
    """Run PICS generation."""
    try:
        import yaml
    except ImportError:
        print(
            "error: pyyaml is required for PICS generation; install with `uv sync`",
            file=sys.stderr,
        )
        return 1
    from pybluehost.pts.pics_gen import generate_pics_draft

    caps_path = Path(args.capability_file)
    if not caps_path.exists():
        print(f"error: capability file not found: {caps_path}", file=sys.stderr)
        return 1
    capabilities = json.loads(caps_path.read_text())
    drafts = generate_pics_draft(capabilities)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for group, items in drafts.items():
        path = output_dir / f"{group.lower()}.draft.yaml"
        path.write_text(yaml.safe_dump({group: items}, sort_keys=False))
        print(f"wrote {path}")
    return 0
