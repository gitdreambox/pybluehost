#!/usr/bin/env bash
# Sequential batch driver: run one autoptsclient session per filter, back to
# back. Running a whole group in ONE session amortises the ~25 s PTS bring-up
# and the per-case connect overhead — far faster than one process per case.
#
# Usage: pts_batch_sequence.sh <filter> [<filter> ...]
# Verdicts land in /tmp/auto-pts/logs and are imported with
# scripts/pts_import_verdicts.py.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

for filter in "$@"; do
    tag="$(echo "$filter" | tr '/.' '__')"
    echo "=== [sequence] starting $filter ==="
    bash scripts/pts_run_batch.sh "$filter" "seq_${tag}" >/dev/null 2>&1
    echo "=== [sequence] finished $filter ==="
    # Brief settle so the dongle is released before the next session.
    sleep 8
done

echo "=== [sequence] all filters done ==="
