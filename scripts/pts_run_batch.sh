#!/usr/bin/env bash
# Launch one Phase B auto-PTS batch for a profile filter against the local
# autoptsserver. Canonical invocation for the v1.2 real-hardware campaign
# (CSR8510 = IUT, Intel dongle = PTS tester, PTS 8.13, all on one Windows host).
#
# Prerequisites (already running): autoptsserver.py -S 65000 --dongle <intel>
#
# Usage:
#   scripts/pts_run_batch.sh GATT                # run all GATT cases
#   scripts/pts_run_batch.sh L2CAP/LE            # subset filter
#   scripts/pts_run_batch.sh SM gatt_sm.log      # custom log name
#
# The client re-reads auto_pts_project/pybluehost_iut/ixit.py on every launch,
# so PIXIT edits (e.g. TSPX_time_guard) require a client restart to take effect.
# Per-case BTP fixes land live: iutctl spawns a fresh pts-tester per case from
# the editable-install working tree.
set -euo pipefail

FILTER="${1:?usage: pts_run_batch.sh <test-case-filter> [log-name]}"
LOGNAME="${2:-$(echo "$FILTER" | tr '/.' '__')}"
case "$LOGNAME" in *.log) ;; *) LOGNAME="$LOGNAME.log" ;; esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUTOPTS="/tmp/auto-pts"
WORKSPACE="${PYBLUEHOST_WORKSPACE:-$REPO/runs/phase2/workspace/zephyr-master/zephyr-master.pqw6}"
PY="$REPO/.venv/Scripts/python.exe"

# The IUT transport has to name the BE200 that is NOT the PTS dongle, and libusb
# enumeration order swaps on replug/reboot — a hardcoded occurrence silently
# spawns pts-tester on the PTS dongle, and every case then dies at ~13s with
# "IUT (pts-tester) did not connect to BTP socket" / FATAL ERROR, which reads
# like a stack bug but is not. Resolve it by BD_ADDR instead; pts_harvest.sh
# exports the same value so the probe runs once per harvest, not per case.
if [ -z "${PYBLUEHOST_IUT_TRANSPORT:-}" ]; then
    PYBLUEHOST_IUT_TRANSPORT="$("$PY" scripts/pybluehost_pts_dongle.py 2>/dev/null \
        | sed -n 's/^IUT_TRANSPORT=//p' || true)"
fi
TRANSPORT="${PYBLUEHOST_IUT_TRANSPORT:-}"
if [ -z "$TRANSPORT" ]; then
    echo "pts_run_batch: could not resolve the IUT dongle — check scripts/pybluehost_pts_dongle.py, or set PYBLUEHOST_IUT_TRANSPORT" >&2
    exit 1
fi

[ -f "$WORKSPACE" ] || { echo "workspace not found: $WORKSPACE" >&2; exit 1; }
[ -x "$PY" ] || PY="python"

cd "$REPO"

# After a Windows reboot Hyper-V/winNAT randomly reserves ephemeral TCP ranges
# (netsh int ipv4 show excludedportrange protocol=tcp). A port inside one fails
# to bind with WinError 10013: autoptsserver dies right after printing
# "Serving on port N ..." (exit code 0 — the wrapper sees nothing), and
# autoptsclient dies on the LT1-callback socket while every case times out.
# The netsh listing is localized, so probe by binding instead (pts_pick_port.py)
# and share the outcome through $AUTOPTS/.pts_ports so the server and the client
# always agree on the pair.
PORTS_FILE="$AUTOPTS/.pts_ports"
# NOTE: this script runs under `set -e`, so a bare `[ -f ... ] && . file` would
# abort with status 1 the first time the file is missing. Keep it an if-block.
if [ -f "$PORTS_FILE" ]; then
    # shellcheck disable=SC1090
    . "$PORTS_FILE"
fi
PTS_SRV_PORT="${PYBLUEHOST_PTS_PORT:-${PTS_SRV_PORT:-65000}}"
PTS_CLI_PORT="${PYBLUEHOST_PTS_CLI_PORT:-${PTS_CLI_PORT:-60000}}"
if [ -z "${PYBLUEHOST_PTS_CLI_PORT:-}" ] \
        && [ -z "$("$PY" scripts/pts_pick_port.py "$PTS_CLI_PORT" --span 0 2>/dev/null)" ]; then
    _wanted="$PTS_CLI_PORT"
    PTS_CLI_PORT="$("$PY" scripts/pts_pick_port.py "$_wanted")"
    printf 'PTS_SRV_PORT=%s\nPTS_CLI_PORT=%s\n' "$PTS_SRV_PORT" "$PTS_CLI_PORT" > "$PORTS_FILE"
    echo "[pts_run_batch] callback port $_wanted is reserved by Windows — using $PTS_CLI_PORT" >&2
fi

echo "[pts_run_batch] filter=$FILTER log=$AUTOPTS/$LOGNAME"
echo "[pts_run_batch] server port $PTS_SRV_PORT, callback port $PTS_CLI_PORT"
nohup "$PY" autoptsclient-pybluehost.py "$WORKSPACE" \
    -i 127.0.0.1 -l 127.0.0.1 -S "$PTS_SRV_PORT" -C "$PTS_CLI_PORT" \
    --pybluehost-transport "$TRANSPORT" \
    -c "$FILTER" > "$AUTOPTS/$LOGNAME" 2>&1 &
echo "[pts_run_batch] client pid $! — tail with: tail -f $AUTOPTS/$LOGNAME"
