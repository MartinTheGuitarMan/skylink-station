#!/bin/bash
# Nightly runner. Works through config/queue.txt inside the 23:00-06:00 Europe/Stockholm window,
# niced, resumable: every run resumes from its checkpoint and stops cleanly at the window end.
#
# queue.txt lines: <run-id> <scenario.toml> <seed> <days> <speed> [edge-config]   (# comments ok)
# Not installed anywhere by itself. See ops/README.md for the launchd job (needs the owner's yes).
set -u
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export INFLUX_URL=http://localhost:8086
END="${WINDOW_END:-06:00}"

hour=$(TZ=Europe/Stockholm date +%H)
if [ "${FORCE:-0}" != 1 ] && [ "$hour" -ge 6 ] && [ "$hour" -lt 23 ]; then
  echo "outside the night window (23:00-06:00 Europe/Stockholm); FORCE=1 overrides" >&2; exit 0
fi
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
colima status >/dev/null 2>&1 || colima start --cpu 4 --memory 6 --disk 40 --vm-type vz >/dev/null 2>&1
docker compose up -d >/dev/null 2>&1 || { echo "docker stack not available" >&2; exit 1; }

while read -r run scen seed days speed edge; do
  case "$run" in ""|\#*) continue;; esac
  if [ -f "runs/$run/summary.json" ] && grep -q '"finished": true' "runs/$run/summary.json"; then continue; fi
  now=$(TZ=Europe/Stockholm date +%H%M)
  if [ "$now" -ge "${END/:/}" ] && [ "$now" -lt 2300 ]; then echo "window over"; break; fi
  echo "$(date '+%F %T') run $run (seed $seed, $days d, ${speed}x)"
  resume=""; [ -f "runs/$run/checkpoint.json" ] && resume="--resume"
  nice -n 15 uv run skylink-sim run --config "$scen" --run-id "$run" --seed "$seed" --days "$days" \
      --speed "$speed" --until "$END" $resume
  curl -s -XPOST localhost:8000/flush >/dev/null
done < config/queue.txt

# ---- agent evaluations (local models through mcp-minions), after the simulation queue --------------
# config/agent-queue.txt lines: <id>|<per-class cases>|<name=model-spec,...>   (ollama:<model> for Ollama)
if [ -f config/agent-queue.txt ] && command -v ollama >/dev/null; then
  curl -s -m 2 localhost:11434/api/version >/dev/null || { (nohup nice ollama serve >> runs/ollama.log 2>&1 &); sleep 8; }
  while IFS='|' read -r id per models; do
    case "$id" in ""|\#*) continue;; esac
    [ -f "runs/agent/$id/report.md" ] && continue
    now=$(TZ=Europe/Stockholm date +%H%M)
    if [ "$now" -ge "${END/:/}" ] && [ "$now" -lt 2300 ]; then echo "window over (agent)"; break; fi
    echo "$(date '+%F %T') agent eval $id ($models, $per per class)"
    [ -f runs/agent/cases.json ] || nice uv run --extra agent python scripts/agent_eval.py build --seeds 1,2,3 --days 7
    nice uv run --extra agent python scripts/agent_eval.py run --models "$models" --per-class "$per" --id "$id" --timeout 300
  done < config/agent-queue.txt
fi
