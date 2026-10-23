#!/usr/bin/env bash
# ApplyPilot, unattended: LinkedIn -> company contacts -> local-LLM drafts -> REAL emails.
#
#   ./run.sh          live run: emails real recipients (default target: 10 companies)
#   ./run.sh --dry    same flow, but prints what it WOULD send and sends nothing
#   JOBS=5 ./run.sh   change the number of companies
#   touch STOP        halts a run in progress (checked before every email)
set -uo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
MODE=live
[ "${1:-}" = "--dry" ] && MODE=dry
JOBS="${JOBS:-10}"

mkdir -p logs output
LOG="logs/run-$(date +%Y%m%d-%H%M%S).log"
ls -1t logs/run-*.log 2>/dev/null | tail -n +11 | xargs rm -f --  # keep only the 10 most recent run logs
LOCK=output/.run.lock

if [ -e STOP ]; then echo "A STOP file exists. Delete it first (rm STOP)."; exit 1; fi
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another run is in progress. If that's wrong: rmdir $LOCK"; exit 1
fi
# keep the Mac awake (display, idle, disk, system-on-AC) for as long as this script lives
caffeinate -dims -w $$ &
CAFFEINATE_PID=$!
cleanup() {
  kill "$CAFFEINATE_PID" 2>/dev/null
  rmdir "$LOCK" 2>/dev/null
  # close only the automation Brave (own data dir); your normal Brave is untouched
  pkill -f "user-data-dir=$HOME/.applypilot/brave-profile" 2>/dev/null
}
trap cleanup EXIT

echo "== preflight"
$PY -m applypilot.cli preflight || exit 1

queued=$($PY -c "import json,os;p='output/emails.json';print(len(json.load(open(p))) if os.path.exists(p) else 0)")
if [ "$MODE" = live ]; then
  echo
  echo "!! LIVE RUN: real emails to real recipients. Target: $JOBS companies."
  echo "!! $queued draft(s) from earlier runs are already queued and WILL be sent too."
  echo "!! Press Ctrl+C within 15 seconds to abort."
  sleep 15
  FLAG="--live"
else
  FLAG=""
fi

echo "== running (log: $LOG)"
# unbuffered so the log is live
PYTHONUNBUFFERED=1 $PY -m applypilot.cli run --jobs "$JOBS" $FLAG 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}

left=$($PY -c "import json,os;p='output/emails.json';print(len(json.load(open(p))) if os.path.exists(p) else 0)")
echo
echo "== finished (exit $rc). $left entr(ies) left in output/emails.json. Log: $LOG"
osascript -e "display notification \"Finished (exit $rc). $left left to send.\" with title \"ApplyPilot\"" 2>/dev/null
exit "$rc"
