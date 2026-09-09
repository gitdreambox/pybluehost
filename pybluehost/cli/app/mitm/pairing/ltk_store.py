"""LE LTK JSONL persistence (same file as SspTermination's link-key log, distinguished by type)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def load_ltks(path: str | Path) -> dict[tuple[str, str], bytes]:
    """Read (side, addr) → ltk; missing file, bad lines, and non-ltk records are skipped."""
    out: dict[tuple[str, str], bytes] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if not isinstance(rec, dict):
                        continue
                    if rec.get("type") != "ltk":
                        continue
                    out[(rec["side"], rec["addr"].upper())] = bytes.fromhex(rec["ltk"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass  # first run: file missing is normal
    return out


def append_ltk(path: str | Path, *, side: str, addr: str, ltk: bytes) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "ltk",
        "side": side,
        "addr": addr.upper(),
        "ltk": ltk.hex(),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("session[le]: LTK 落盘失败 path=%s: %s", path, exc)
