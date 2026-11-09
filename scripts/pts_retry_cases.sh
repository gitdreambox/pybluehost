#!/usr/bin/env bash
# Retry harness for flaky PTS cases (peripheral-connect flakiness makes verdicts
# non-deterministic: a case that is INDCSV in a back-to-back batch often PASSes
# when run alone in a clean session — confirmed SM/PER/KDU/BV-01 2026-08-26).
#
# Runs each given case INDIVIDUALLY (its own autoptsclient session) until PASS
# or max attempts. Best verdict wins; PASS short-circuits further attempts.
# PTS TIMEOUT is not retried (expensive ~350s and usually a real hang, not flaky).
#
# Usage:
#   scripts/pts_retry_cases.sh <max_attempts> <case-id> [case-id ...]
#   scripts/pts_retry_cases.sh 3 SM/PER/KDU/BV-01-C SM/PER/OOB/BV-02-C
#
# After it finishes, record results:
#   uv run python scripts/pts_import_verdicts.py /tmp/auto-pts/logs --date <YYYY-MM-DD>
set -uo pipefail

MAX="${1:?usage: pts_retry_cases.sh <max_attempts> <case-id> [...]}"; shift
[ "$#" -ge 1 ] || { echo "need at least one case-id" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUTOPTS="/tmp/auto-pts"
PY="$REPO/.venv/Scripts/python.exe"
cd "$REPO"

# Port pair shared with pts_run_batch.sh / pts_harvest.sh through $AUTOPTS/.pts_ports.
# A Windows reboot can put 65000 (server) and 60000 (XML-RPC callback) inside a
# Hyper-V/winNAT excluded range; binding then fails with WinError 10013 and the
# server exits 0 right after printing "Serving on port ...", which looks exactly
# like a harness crash. Resolve/repair the pair here so every script agrees.
PORTS_FILE="$AUTOPTS/.pts_ports"
if [ -f "$PORTS_FILE" ]; then
    # shellcheck disable=SC1090
    . "$PORTS_FILE"
fi
PTS_SRV_PORT="${PYBLUEHOST_PTS_PORT:-${PTS_SRV_PORT:-65000}}"
PTS_CLI_PORT="${PYBLUEHOST_PTS_CLI_PORT:-${PTS_CLI_PORT:-60000}}"

# The server port may legitimately be held by a running server, so only repair it
# when the port is unbindable AND nothing is listening (i.e. Windows reserved it).
repair_ports() {
    if [ -z "${PYBLUEHOST_PTS_PORT:-}" ] \
            && ! server_is_up \
            && [ -z "$("$PY" scripts/pts_pick_port.py "$PTS_SRV_PORT" --span 0 2>/dev/null)" ]; then
        local wanted="$PTS_SRV_PORT"
        PTS_SRV_PORT="$("$PY" scripts/pts_pick_port.py "$wanted")"
        if [ -z "${PYBLUEHOST_PTS_CLI_PORT:-}" ]; then
            PTS_CLI_PORT="$("$PY" scripts/pts_pick_port.py "$PTS_CLI_PORT")"
        fi
        printf 'PTS_SRV_PORT=%s\nPTS_CLI_PORT=%s\n' "$PTS_SRV_PORT" "$PTS_CLI_PORT" > "$PORTS_FILE"
        echo "[retry] server port $wanted is reserved by Windows — using $PTS_SRV_PORT (callback $PTS_CLI_PORT)"
    fi
    if [ -z "${PYBLUEHOST_PTS_CLI_PORT:-}" ] \
            && [ -z "$("$PY" scripts/pts_pick_port.py "$PTS_CLI_PORT" --span 0 2>/dev/null)" ]; then
        local wanted="$PTS_CLI_PORT"
        PTS_CLI_PORT="$("$PY" scripts/pts_pick_port.py "$wanted")"
        printf 'PTS_SRV_PORT=%s\nPTS_CLI_PORT=%s\n' "$PTS_SRV_PORT" "$PTS_CLI_PORT" > "$PORTS_FILE"
        echo "[retry] callback port $wanted is reserved by Windows — using $PTS_CLI_PORT"
    fi
    export PTS_SRV_PORT PTS_CLI_PORT
}

kill_leftovers() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process | ? {\$_.Name -match 'python' -and \$_.CommandLine -match 'autoptsclient|pts-tester'} | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1
    sleep 2
}

# A case that stalls mid-flow (PTS stops writing the case log and never judges)
# wedges the server itself: every following case then dies in init_pts with
# ConnectionRefusedError [WinError 10061]. Nothing else restarts the server
# between attempts, so without this guard one stalled case poisons the whole
# retry run. Probe the listen port and bring the server back up if it is gone.
server_is_up() {
    powershell -NoProfile -Command \
        "if (Get-NetTCPConnection -LocalPort $PTS_SRV_PORT -State Listen -EA SilentlyContinue) { exit 0 } else { exit 1 }" \
        >/dev/null 2>&1
}

ensure_server() {
    server_is_up && return 0
    echo "[retry] autoptsserver is down — restarting ..."
    local dongle
    dongle="${PYBLUEHOST_PTS_DONGLE:-$(./.venv/Scripts/python.exe scripts/pybluehost_pts_dongle.py 2>/dev/null | sed -n 's/^PTS_DONGLE=//p')}"
    if [ -z "$dongle" ]; then
        echo "[retry] cannot resolve the PTS dongle role — aborting" >&2
        return 1
    fi
    powershell -NoProfile -Command \
        "Get-Process PTS -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue" \
        >/dev/null 2>&1
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process | ? {\$_.Name -match 'python' -and \$_.CommandLine -match 'autoptsserver'} | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1
    sleep 3
    ( cd "$AUTOPTS" && nohup "$REPO/.venv/Scripts/python.exe" -u autoptsserver.py \
        -S "$PTS_SRV_PORT" --dongle "$dongle" > /tmp/pts_retry_server.log 2>&1 & )
    sleep 22
    server_is_up
}

# PYBLUEHOST_RETRY_WAIT_ITERS overrides the verdict-wait window (iters × 4s).
# Default 60 (=240s) suits most cases; multi-bearer whole-db reads (GAR/BV-11/12)
# run for many minutes with a frozen case log while ATT traffic continues — give
# those a bigger window instead of declaring a stall.
wait_verdict() {  # $1=logfile  -> echoes verdict or empty on timeout of our wait
    local log="$1" i
    for i in $(seq 1 "${PYBLUEHOST_RETRY_WAIT_ITERS:-60}"); do
        local v
        v=$(grep -oE "\b(PASS|FAIL|INDCSV|INCONC|UNKNOWN VERDICT: NONE|PTS TIMEOUT|FATAL ERROR|BTP ERROR|BTP TIMEOUT|MISSING WID ERROR)\b" "$log" 2>/dev/null | head -1)
        [ -n "$v" ] && { echo "$v"; return; }
        sleep 4
    done
    echo ""
}

# Snapshot the IUT-side trace into the case's own session dir. pts-tester opens
# iut-pybluehost.log with "w" on every spawn, so it only ever holds the attempt
# that just finished — copy it out now or the evidence is gone. Only meaningful
# with PYBLUEHOST_IUT_LOG_LEVEL=DEBUG exported. Session dirs are named
# <tag>_<timestamp>, hence the prefix glob.
snapshot_iut_log() {  # $1=tag $2=attempt
    local tag="$1" att="$2" dest
    [ -f iut-pybluehost.log ] || return 0
    dest=$(ls -dt "$AUTOPTS"/logs/cli_port_${PTS_CLI_PORT}/*/"$tag"_* 2>/dev/null | head -1)
    if [ -n "$dest" ]; then
        cp -f iut-pybluehost.log "$dest/iut_att${att}.log"
    else
        cp -f iut-pybluehost.log "$AUTOPTS/iut_retry_${tag}_att${att}.log"
    fi
}

# The client summary log only prints "FATAL ERROR"; the exception text lives in
# the per-case log under logs/cli_port_${PTS_CLI_PORT}/<ts>/<tag>_<ts>/.
case_log_has() {  # $1=tag $2=pattern
    local dir
    dir=$(ls -dt "$AUTOPTS"/logs/cli_port_${PTS_CLI_PORT}/*/"$1"_* 2>/dev/null | head -1)
    [ -n "$dir" ] && grep -rq "$2" "$dir" 2>/dev/null
}

# PTS's own verdict is the ground truth. The client summary can report "BTP
# TIMEOUT"/"BTP ERROR" for a case PTS already judged PASS (GAP/SEC/AUT/BV-17/18/
# 26 on 2026-11-02), so scraping only the summary would retry a passing case to
# exhaustion and record an abort. Read the FINAL_VERDICT block from the case log
# once the client has produced its summary.
pts_verdict() {  # $1=tag
    local tag="$1" dir log
    dir=$(ls -dt "$AUTOPTS"/logs/cli_port_${PTS_CLI_PORT}/*/"$tag"_* 2>/dev/null | head -1)
    [ -n "$dir" ] || return 0
    log=$(find "$dir" -maxdepth 1 -name "${tag}_*.log" -print -quit 2>/dev/null)
    [ -n "$log" ] || return 0
    "$PY" scripts/pts_case_verdict.py "$log" 2>/dev/null
}

# Cold PTS.exe (after a server restart) poisons the first pairing case: PTS
# does not answer its own controller's LTK request and the case dies with
# Encryption_Change status 0x08 / LL supervision timeout (see AGENTS.md
# "GAP/SEC（AUT+SEM）整簇 <no verdict> / FAIL" — fix ①). pts_harvest.sh has
# always run a discard warmup case first; this script needs the same guard.
repair_ports
echo "[retry] server port $PTS_SRV_PORT, callback port $PTS_CLI_PORT"
if [ -n "${PYBLUEHOST_HARVEST_WARMUP:-}" ]; then
    wtag="warmup_$(echo "$PYBLUEHOST_HARVEST_WARMUP" | tr '/.' '__')"
    echo "[retry] warming up with $PYBLUEHOST_HARVEST_WARMUP ..."
    kill_leftovers
    ensure_server || { echo "[retry] server unavailable for warmup"; exit 1; }
    bash scripts/pts_run_batch.sh "$PYBLUEHOST_HARVEST_WARMUP" "$wtag" >/dev/null 2>&1
    wait_verdict "$AUTOPTS/${wtag}.log" >/dev/null 2>&1
    echo "[retry] warmup done (verdict discarded)"
fi

declare -A BEST
for case in "$@"; do
    tag="$(echo "$case" | tr '/.' '__')"
    best=""
    for att in $(seq 1 "$MAX"); do
        kill_leftovers
        ensure_server || { echo "[retry] $case: server unavailable, skipping"; break; }
        log="$AUTOPTS/retry_${tag}.log"
        # The verdict is parsed from this log; a stale one from a previous
        # session makes wait_verdict return instantly with a phantom verdict
        # while the freshly launched client is still booting.
        rm -f "$log"
        bash scripts/pts_run_batch.sh "$case" "retry_${tag}" >/dev/null 2>&1
        sleep 15
        if [ ! -e "$log" ]; then
            # pts_run_batch bailed before spawning the client (guard failure,
            # e.g. the IUT transport could not be resolved) — its stderr said
            # why; surface it instead of silently waiting on nothing.
            echo "[retry] $case: client never started (pts_run_batch guard failed)" >&2
            break
        fi
        v=$(wait_verdict "$log")
        snapshot_iut_log "$tag" "$att"
        # Let PTS finish writing its FINAL_VERDICT block, then prefer it over
        # the client summary. A client-side BTP TIMEOUT/ERROR is not the
        # conformance result when PTS has already judged the case.
        sleep 10
        pts_v=$(pts_verdict "$tag")
        if [ -n "$pts_v" ] && [ "$pts_v" != "$v" ]; then
            echo "[retry] $case attempt $att: PTS verdict $pts_v overrides client summary ${v:-<none>}"
            v="$pts_v"
        fi
        # A FATAL whose text is "Not connected" is the peripheral-connect flaky
        # (PTS never connected to the advertising IUT, or dropped the link
        # mid-wid) — retryable, unlike a FATAL from a real stack crash which
        # the no-retry rule guards against.
        if [ "$v" = "FATAL ERROR" ] && case_log_has "$tag" "Not connected"; then
            v="INDCSV"
        fi
        echo "[retry] $case attempt $att -> ${v:-<no verdict>}"
        case "$v" in
            PASS) best=PASS; break ;;
            "PTS TIMEOUT"|"FATAL ERROR") [ -z "$best" ] && best="$v"; break ;;  # don't retry
            "") break ;;                                                          # harness issue
            *) [ -z "$best" ] && best="$v" ;;                                     # INDCSV/FAIL/etc: retry
        esac
    done
    BEST[$case]="${best:-UNKNOWN}"
done

echo "=== RETRY SUMMARY ==="
for case in "$@"; do
    printf '%-28s %s\n' "$case" "${BEST[$case]}"
done
