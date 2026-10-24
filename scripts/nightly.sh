#!/bin/bash
# Nightly runner. Works through config/queue.txt inside the 23:00-06:00 Europe/Stockholm window,
# niced, resumable: every run resumes from its checkpoint and stops cleanly at the window end.
#
# queue.txt lines: <run-id> <scenario.toml> <seed> <days> <speed> [edge-config]   (# comments ok)
# Installed on the Mini as the system daemon se.skylink.nightly (ops/README.md).
# Stops early when free disk drops below MIN_FREE_GB (default 3) or the colima VM disk that holds InfluxDB below MIN_VM_FREE_GB (6). Writes runs/last-night.txt: one line per
# item (ok / stopped / cut / failed), read by the daytime loop (docs/daily-loop.md).
set -u
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export INFLUX_URL=http://localhost:8086
END="${WINDOW_END:-06:00}"
MIN_FREE_GB="${MIN_FREE_GB:-3}"
MIN_VM_FREE_GB="${MIN_VM_FREE_GB:-6}"   # InfluxDB lives on the colima VM disk (40 GB); it filled up on 2026-10-19 and voided dev-s2-drift
SUMMARY=runs/last-night.txt
ran=0

free_gb() { df -g . | awk 'NR==2 {print $4}'; }
vm_free_gb() { docker exec skylink-influxdb-1 df -Pk /var/lib/influxdb2 2>/dev/null | awk 'NR==2 {print int($4/1048576)}'; }
note() { echo "$*" >> "$SUMMARY"; }
# prints why simulations (the only InfluxDB writers) must not start, or nothing
vm_reason() { local vm; vm=$(vm_free_gb); [ -n "$vm" ] && [ "$vm" -lt "$MIN_VM_FREE_GB" ] && echo "VM disk low (InfluxDB volume: $vm GB free, need $MIN_VM_FREE_GB)"; }
# prints why the night must stop (window over, disk low), or nothing
stop_reason() {
  local now; now=$(TZ=Europe/Stockholm date +%H%M)
  if [ "$now" -ge "${END/:/}" ] && [ "$now" -lt 2300 ]; then echo "window over"; return; fi
  [ "$(free_gb)" -lt "$MIN_FREE_GB" ] && echo "disk low ($(free_gb) GB free, need $MIN_FREE_GB)"
}

hour=$(TZ=Europe/Stockholm date +%H)
if [ "${FORCE:-0}" != 1 ] && [ "$hour" -ge 6 ] && [ "$hour" -lt 23 ]; then
  echo "outside the night window (23:00-06:00 Europe/Stockholm); FORCE=1 overrides" >&2; exit 0
fi
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
echo "night $(TZ=Europe/Stockholm date '+%F %H:%M'), $(free_gb) GB free" > "$SUMMARY"
trap 'note "end $(TZ=Europe/Stockholm date +%H:%M), $(free_gb) GB free"; [ $ran = 0 ] && note "nothing ran"' EXIT
why=$(stop_reason); [ -n "$why" ] && { note "not started: $why"; echo "$why" >&2; exit 0; }
colima status >/dev/null 2>&1 || colima start --cpu 4 --memory 6 --disk 40 --vm-type vz >/dev/null 2>&1
docker compose up -d >/dev/null 2>&1 || { note "failed: docker stack not available"; echo "docker stack not available" >&2; exit 1; }

# ---- escalation inbox (C5e inbox run, docs/escalation.md): seconds of work, before anything long --------
# Applies answers sent back by the daily pass, scores applied nights, asks the next night in config/escalation-queue.txt.
if [ -f config/escalation-queue.txt ]; then
  if out=$(nice uv run python scripts/escalate.py night 2>&1); then ran=1; note "escalation: $(echo "$out" | tr '\n' ';' | cut -c1-200)"
  else note "escalation: failed ($(echo "$out" | tail -1 | cut -c1-120))"; fi
fi

while read -r run scen seed days speed edge; do
  case "$run" in ""|\#*) continue;; esac
  if [ -f "runs/$run/summary.json" ] && grep -q '"finished": true' "runs/$run/summary.json"; then continue; fi
  why=$(stop_reason); [ -n "$why" ] && { echo "$why"; note "stop: $why"; break; }
  why=$(vm_reason); [ -n "$why" ] && { echo "$why"; note "sim queue skipped: $why"; break; }
  echo "$(date '+%F %T') run $run (seed $seed, $days d, ${speed}x)"; ran=1
  resume=""; [ -f "runs/$run/checkpoint.json" ] && resume="--resume"
  nice -n 15 uv run skylink-sim run --config "$scen" --run-id "$run" --seed "$seed" --days "$days" \
      --speed "$speed" --until "$END" $resume
  curl -s -XPOST localhost:8000/flush >/dev/null
  if grep -qs '"finished": true' "runs/$run/summary.json"; then note "sim $run: ok"; else note "sim $run: stopped (resumes next night)"; fi
done < config/queue.txt

# ---- agent evaluations (local models through mcp-minions), after the simulation queue --------------
# config/agent-queue.txt lines: <id>|<per-class cases>|<name=model-spec,...>   (ollama:<model> for Ollama)
if [ -f config/agent-queue.txt ] && command -v ollama >/dev/null; then
  curl -s -m 2 localhost:11434/api/version >/dev/null || { (nohup nice ollama serve >> runs/ollama.log 2>&1 &); sleep 8; }
  while IFS='|' read -r id per models; do
    case "$id" in ""|\#*) continue;; esac
    [ -f "runs/agent/$id/report.md" ] && continue
    why=$(stop_reason); [ -n "$why" ] && { echo "$why (agent)"; note "stop: $why"; break; }
    echo "$(date '+%F %T') agent eval $id ($models, $per per class)"; ran=1
    [ -f runs/agent/cases.json ] || nice uv run --extra agent python scripts/agent_eval.py build --seeds 1,2,3 --days 7
    nice uv run --extra agent python scripts/agent_eval.py run --models "$models" --per-class "$per" --id "$id" --timeout 300 --until "$END"
    if [ -f "runs/agent/$id/report.md" ]; then note "agent eval $id: ok"; else note "agent eval $id: stopped (resumes next night)"; fi
  done < config/agent-queue.txt
fi

# ---- job P closed-loop bench, live models (C5b/C5c on dev seeds), after the agent evaluations --------
# config/proposal-queue.txt lines: <id>|<seed>|<days>|<streams>|<name=model-spec,...>   (ollama:<model> for Ollama)
if [ -f config/proposal-queue.txt ] && command -v ollama >/dev/null; then
  curl -s -m 2 localhost:11434/api/version >/dev/null || { (nohup nice ollama serve >> runs/ollama.log 2>&1 &); sleep 8; }
  while IFS="|" read -r id seed days streams models; do
    case "$id" in ""|\#*) continue;; esac
    [ -f "runs/agent/proposals-$id/result.json" ] && continue
    why=$(stop_reason); [ -n "$why" ] && { echo "$why (proposals)"; note "stop: $why"; break; }
    echo "$(date "+%F %T") proposal bench $id (seed $seed, $days d, $streams, $models)"; ran=1
    nice uv run --extra agent python scripts/agent_proposals.py --seed "$seed" --days "$days" --streams "$streams" \
        --models "$models" --out "runs/agent/proposals-$id" --until "$END" > "runs/agent/proposals-$id.txt" 2>&1
    case $? in
      0) note "proposals $id: ok";;
      3) note "proposals $id: cut at $END (no checkpoint: starts over next night; shorten days or drop a model)";;
      *) note "proposals $id: failed (see runs/agent/proposals-$id.txt)";;
    esac
  done < config/proposal-queue.txt
fi
