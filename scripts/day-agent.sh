#!/bin/bash
# Day-host night job for the agent evaluation (LM Studio models). Window 23:00-06:00 Europe/Stockholm, niced.
# Not scheduled by itself: start it by hand, or `FORCE=1` outside the window. Stops the LM Studio server at the end.
set -u
cd "$(dirname "$0")/.."
export PATH=$HOME/.lmstudio/bin:$HOME/.local/bin:/opt/homebrew/bin:$PATH
hour=$(TZ=Europe/Stockholm date +%H)
if [ "${FORCE:-0}" != 1 ] && [ "$hour" -ge 6 ] && [ "$hour" -lt 23 ]; then
  echo "waiting for 23:00 Europe/Stockholm"
  while [ "$(TZ=Europe/Stockholm date +%H)" -lt 23 ] && [ "$(TZ=Europe/Stockholm date +%H)" -ge 6 ]; do sleep 60; done
fi
lms server start >/dev/null 2>&1
curl -s -m 2 localhost:8765/v1/models >/dev/null || { (nohup nice jev-style serve --port 8765 --host 127.0.0.1 > runs/agent/jev-day.log 2>&1 &); sleep 20; }
[ -f runs/agent/cases.json ] || nice uv run --extra agent python scripts/agent_eval.py build --seeds 1,2,3 --days 7
run() {  # id per-class specs
  [ -f "runs/agent/$1/report.md" ] && return
  now=$(TZ=Europe/Stockholm date +%H%M); [ "$now" -ge 600 ] && [ "$now" -lt 2300 ] && { echo "window over"; return; }
  free=$(memory_pressure | awk '/free percentage/ {gsub("%","",$NF); print $NF}')
  if [ "${free:-0}" -lt "${MIN_FREE_PCT:-45}" ]; then echo "$(date '+%F %T') skip $1: only ${free}% memory free (need ${MIN_FREE_PCT:-45}%)"; return; fi
  echo "$(date '+%F %T') $1 (memory free ${free}%)"
  nice uv run --extra agent python scripts/agent_eval.py run --per-class "$2" --models "$3" --id "$1" --timeout 300 --until 06:00
}
run day-t1 100 "g1b=google/gemma-3-1b,e4b=google/gemma-4-e4b,j08=roster:config/roster-jev.json"
run day-t2 100 "g12b=google/gemma-4-12b"
run day-t3 100 "gpt20b=openai/gpt-oss-20b"
lms unload --all >/dev/null 2>&1; lms server stop >/dev/null 2>&1
echo "done $(date '+%F %T')"
