#!/usr/bin/env bash
# Harvest harness for PTS cases: runs each case in its OWN autoptsclient session
# (reliable) and restarts autoptsserver every few cases.
#
# Why: a single long batch session wedges after ~3-5 cases with a PTS-side state
# degradation that is not a dongle problem (see AGENTS.md "批量跑 PTS ... 卡死").
# Restarting the server clears it, and per-case sessions avoid the batch wedging
# entirely.
#
# Usage:
#   scripts/pts_harvest.sh [-n <cases-per-server>] <case-id> [case-id ...]
#
# After it finishes: scripts/pts_import_verdicts.py /tmp/auto-pts/logs --date <d>
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

N=${PYBLUEHOST_HARVEST_PER_SERVER:-2}
if [ "${1:-}" = "-n" ]; then N="$2"; shift 2; fi
[ "$#" -ge 1 ] || { echo "usage: pts_harvest.sh [-n N] <case> [case ...]" >&2; exit 1; }

AUTOPTS=/tmp/auto-pts

kill_iut() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process | ? {\$_.Name -match 'python' -and \$_.CommandLine -match 'autoptsclient|pts-tester'} | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1
    sleep 3
}

# Resolve both dongle roles from the live hardware instead of hardcoding them:
# the libusb occurrence (`usb:8087:0036#N`) and the PnP instance path both change
# on replug and reboot, and a stale value silently binds the IUT dongle as the
# PTS tester — every case then dies as "IUT (pts-tester) did not connect to BTP
# socket". scripts/pybluehost_pts_dongle.py keys the roles on the IUT's BD_ADDR.
# Run it with the IUT dongle free, hence after kill_iut. The transport is
# exported because pts_run_batch.sh passes no transport arg of its own and would
# otherwise probe once per case.
kill_iut
RIG="$(./.venv/Scripts/python.exe scripts/pybluehost_pts_dongle.py 2>/dev/null || true)"
DONGLE="${PYBLUEHOST_PTS_DONGLE:-$(echo "$RIG" | sed -n 's/^PTS_DONGLE=//p')}"
export PYBLUEHOST_IUT_TRANSPORT="${PYBLUEHOST_IUT_TRANSPORT:-$(echo "$RIG" | sed -n 's/^IUT_TRANSPORT=//p')}"
echo "[harvest] IUT=${PYBLUEHOST_IUT_TRANSPORT:-?} PTS dongle=${DONGLE:-?}"
if [ -z "$DONGLE" ] || [ -z "$PYBLUEHOST_IUT_TRANSPORT" ]; then
    echo "pts_harvest: could not resolve the dongle roles — run scripts/pybluehost_pts_dongle.py to see why" >&2
    exit 1
fi

restart_server() {
    echo "[harvest] restarting autoptsserver ..."
    powershell -NoProfile -Command \
        "Get-Process PTS -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue" \
        >/dev/null 2>&1
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process | ? {\$_.Name -match 'python' -and \$_.CommandLine -match 'autoptsserver'} | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1
    sleep 3
    # Port pair shared with pts_run_batch.sh through $AUTOPTS/.pts_ports — a
    # Windows reboot can put 65000 inside a Hyper-V/winNAT excluded range, where
    # binding fails with WinError 10013 and the server exits 0 right after
    # printing "Serving on port ..." (indistinguishable from a harness crash).
    local ports_file="$AUTOPTS/.pts_ports"
    if [ -f "$ports_file" ]; then
        # shellcheck disable=SC1090
        . "$ports_file"
    fi
    local srv_port="${PYBLUEHOST_PTS_PORT:-${PTS_SRV_PORT:-65000}}"
    if [ -z "${PYBLUEHOST_PTS_PORT:-}" ] \
            && [ -z "$("$REPO/.venv/Scripts/python.exe" scripts/pts_pick_port.py "$srv_port" --span 0 2>/dev/null)" ]; then
        local wanted="$srv_port"
        srv_port="$("$REPO/.venv/Scripts/python.exe" scripts/pts_pick_port.py "$wanted")"
        echo "[harvest] server port $wanted is reserved by Windows — using $srv_port"
    fi
    printf 'PTS_SRV_PORT=%s\nPTS_CLI_PORT=%s\n' \
        "$srv_port" "${PYBLUEHOST_PTS_CLI_PORT:-${PTS_CLI_PORT:-60000}}" > "$ports_file"
    export PTS_SRV_PORT="$srv_port"
    ( cd "$AUTOPTS" && nohup "$REPO/.venv/Scripts/python.exe" -u autoptsserver.py \
        -S "$srv_port" --dongle "$DONGLE" > /tmp/pts_harvest_server.log 2>&1 & )
    sleep 22
    # A freshly-started server/PTS.exe misbehaves on its first case: PTS's
    # workspace still carries the previous test's state and PTS.exe doesn't
    # answer its own controller's LTK_Request, so a pairing case dies at
    # Encryption_Change with reason 0x08 (see AGENTS.md "PTS workspace 状态泄漏").
    # Absorb that with a throwaway case so every real case runs warm.
    if [ -n "${PYBLUEHOST_HARVEST_WARMUP:-}" ]; then
        echo "[harvest] warming up with $PYBLUEHOST_HARVEST_WARMUP ..."
        bash scripts/pts_run_batch.sh "$PYBLUEHOST_HARVEST_WARMUP" \
            "warmup_$(echo "$PYBLUEHOST_HARVEST_WARMUP" | tr '/.' '__')" >/dev/null 2>&1
        wait_verdict "$AUTOPTS/warmup_$(echo "$PYBLUEHOST_HARVEST_WARMUP" | tr '/.' '__').log" 120 \
            >/dev/null 2>&1 || true
        kill_iut
    fi
}

# A wedged PTS session produces no verdict AND stops writing to the case log
# (the client sits waiting on the Lower Tester). Bail out once the log has been
# silent for STALL seconds rather than burning the whole timeout on a dead case.
STALL=${PYBLUEHOST_HARVEST_STALL:-90}

wait_verdict() {  # $1=logfile $2=seconds
    local log="$1" deadline=$(( $(date +%s) + ${2:-420} ))
    local last_mtime=0 silent_since=0 now mt
    while [ "$(date +%s)" -lt "$deadline" ]; do
        local v
        v=$(grep -oE "\b(PASS|FAIL|INDCSV|INCONC|UNKNOWN VERDICT: NONE|PTS TIMEOUT|FATAL ERROR|BTP ERROR|BTP TIMEOUT|MISSING WID ERROR)\b" "$log" 2>/dev/null | head -1)
        [ -n "$v" ] && { echo "$v"; return; }
        now=$(date +%s)
        mt=$(stat -c %Y "$log" 2>/dev/null || echo 0)
        if [ "$mt" != "$last_mtime" ]; then
            last_mtime="$mt"; silent_since="$now"
        elif [ "$silent_since" != "0" ] && [ $((now - silent_since)) -ge "$STALL" ]; then
            echo ""; return          # stalled: no log growth for STALL seconds
        fi
        sleep 5
    done
    echo ""
}

declare -A BEST
i=0
for case in "$@"; do
    i=$((i + 1))
    if [ $(( (i - 1) % N )) -eq 0 ]; then restart_server; fi
    kill_iut
    tag="$(echo "$case" | tr '/.' '__')"
    log="$AUTOPTS/harvest_${tag}.log"
    echo "[harvest] ($i/$#) $case"
    bash scripts/pts_run_batch.sh "$case" "harvest_${tag}" >/dev/null 2>&1
    v=$(wait_verdict "$log" 420)
    echo "[harvest] $case -> ${v:-<no verdict>}"
    BEST[$case]="${v:-UNKNOWN}"
    # Snapshot the IUT-side trace. pts-tester opens iut-pybluehost.log with "w"
    # on every spawn, so it only ever holds the case that just finished — copy it
    # out now or the evidence is gone. Only meaningful with
    # PYBLUEHOST_IUT_LOG_LEVEL=DEBUG exported.
    [ -f iut-pybluehost.log ] && cp -f iut-pybluehost.log "$AUTOPTS/iut_${tag}.log"
    sleep 6   # let the dongle settle before the next session
done

echo "=== HARVEST SUMMARY ==="
for case in "$@"; do printf '%-40s %s\n' "$case" "${BEST[$case]}"; done
