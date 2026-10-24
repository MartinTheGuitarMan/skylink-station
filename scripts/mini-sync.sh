#!/bin/bash
# Sync between the Air (dev copy, run this here) and the Mini (night host). Plain ssh + git bundles, no GitHub.
#
#   scripts/mini-sync.sh status   Mini HEAD, nightly daemon, running jobs, runs/last-night.txt, free disk
#   scripts/mini-sync.sh pull     Mini results -> runs/mini/ here (runs/ and untracked reports/), Mini's main -> refs/remotes/mini/main
#   scripts/mini-sync.sh answers  the daily pass's escalation answers (runs/escalation/outbox/*.jsonl) -> the Mini's runs/escalation/answers/
#   scripts/mini-sync.sh push     fast-forward the Mini's checkout to this main; refuses while a night job runs,
#                                 when the Mini has commits this main lacks, or has uncommitted changes to tracked files
set -eu
cd "$(dirname "$0")/.."
HOST=${MINI_HOST:-mini}
DIR=Code/skylink-station          # relative to the Mini user's home
on_mini() { ssh -o ConnectTimeout=10 "$HOST" "export PATH=/opt/homebrew/bin:\$PATH; cd $DIR && $1"; }

busy() { on_mini "pgrep -f 'scripts/nightly.sh|agent_proposals.py|agent_eval.py|skylink-sim run' >/dev/null" ; }

case "${1:-status}" in
status)
  on_mini 'git log -1 --format="HEAD %h %cr: %s"; launchctl print system/se.skylink.nightly 2>/dev/null | grep -m1 "state ="
           pgrep -fl "nightly.sh|agent_proposals.py|agent_eval.py|skylink-sim run" | cut -c1-120 || true
           echo "-- runs/last-night.txt"; cat runs/last-night.txt 2>/dev/null || echo "(none yet)"
           df -g . | awk "NR==2 {print \"free disk: \" \$4 \" GB\" (\$4 < 20 ? \"  WARNING: under 20 GB, tell the owner\" : \"\")}"
           PATH=/opt/homebrew/bin:$PATH docker exec skylink-influxdb-1 du -sh /var/lib/influxdb2/engine/data 2>/dev/null \
             | awk "{print \"influx data: \" \$1 \" (raw kept forever; owner said keep it, watch it)\"}" || true
           PATH=/opt/homebrew/bin:$PATH docker exec skylink-influxdb-1 df -Pk /var/lib/influxdb2 2>/dev/null \
             | awk "NR==2 {g=int(\$4/1048576); print \"VM disk (InfluxDB): \" g \" GB free of \" int(\$2/1048576) (g < 6 ? \"  WARNING: nightly runs stop under 6 GB\" : \"\")}" || true'
  ;;
pull)
  mkdir -p runs/mini/reports
  rsync -a --exclude ollama.log --exclude colima.log "$HOST:$DIR/runs/" runs/mini/
  on_mini 'git ls-files --others --exclude-standard reports' | while read -r f; do
    rsync -a "$HOST:$DIR/$f" runs/mini/reports/
  done
  on_mini 'git bundle create -q /tmp/skylink-back.bundle main'
  scp -q "$HOST:/tmp/skylink-back.bundle" runs/mini/back.bundle
  git fetch -q runs/mini/back.bundle main:refs/remotes/mini/main
  if git merge-base --is-ancestor mini/main main; then echo "pulled; the Mini has no commits missing here"
  else echo "pulled; the Mini has commits missing here: git log main..mini/main"; fi
  ;;
answers)
  shopt -s nullglob; files=(runs/escalation/outbox/*.jsonl)
  [ ${#files[@]} -gt 0 ] || { echo "no answers in runs/escalation/outbox"; exit 0; }
  on_mini 'mkdir -p runs/escalation/answers'
  rsync -a --ignore-existing "${files[@]}" "$HOST:$DIR/runs/escalation/answers/"
  echo "sent ${#files[@]} answer file(s); the Mini applies them next night"
  ;;
push)
  if busy; then echo "a night job is running on the Mini; push later" >&2; exit 1; fi
  [ -z "$(on_mini 'git status --porcelain --untracked-files=no')" ] || { echo "the Mini has uncommitted changes to tracked files" >&2; exit 1; }
  head=$(on_mini 'git rev-parse HEAD')
  git cat-file -e "$head" 2>/dev/null && git merge-base --is-ancestor "$head" main \
    || { echo "the Mini has commits missing here; run pull and merge mini/main first" >&2; exit 1; }
  [ "$head" = "$(git rev-parse main)" ] && { echo "the Mini is up to date"; exit 0; }
  b=$(mktemp -t skylink).bundle
  git bundle create -q "$b" main "^$head"
  scp -q "$b" "$HOST:/tmp/skylink.bundle"; rm -f "$b"
  on_mini 'git fetch -q /tmp/skylink.bundle main && git merge -q --ff-only FETCH_HEAD && rm /tmp/skylink.bundle && git log -1 --format="Mini now at %h: %s"'
  ;;
*) echo "usage: $0 status|pull|answers|push" >&2; exit 2;;
esac
