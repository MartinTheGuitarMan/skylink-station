#!/bin/bash
# Sync between the day host (dev copy, run this here) and the night host. Plain ssh + git bundles, no GitHub.
# The night host's ssh name comes from NIGHT_HOST (environment, or a NIGHT_HOST= line in .env).
#
#   scripts/night-sync.sh status   night host HEAD, nightly daemon, running jobs, runs/last-night.txt, free disk
#                                  (Influx and VM disk sizes live only while the VM is on; by day see last night's "vm disk at end" line)
#   scripts/night-sync.sh pull     night results -> runs/night/ here (runs/ and untracked reports/), its main -> refs/remotes/night/main
#   scripts/night-sync.sh answers  the daily pass's escalation answers (runs/escalation/outbox/*.jsonl) -> the night host's runs/escalation/answers/
#   scripts/night-sync.sh push     fast-forward the night host's checkout to this main; refuses while a night job runs,
#                                  when the night host has commits this main lacks, or has uncommitted changes to tracked files
set -eu
cd "$(dirname "$0")/.."
[ -n "${NIGHT_HOST:-}" ] || NIGHT_HOST=$(sed -n 's/^NIGHT_HOST=//p' .env 2>/dev/null | tail -1)
HOST=${NIGHT_HOST:?set NIGHT_HOST (environment or .env) to the ssh name of the night host}
DIR=${NIGHT_DIR:-Code/skylink-station}   # relative to the night host user's home
on_night() { ssh -o ConnectTimeout=10 "$HOST" "export PATH=/opt/homebrew/bin:\$PATH; cd $DIR && $1"; }

busy() { on_night "pgrep -f 'scripts/nightly.sh|agent_proposals.py|agent_eval.py|skylink-sim run' >/dev/null" ; }

case "${1:-status}" in
status)
  on_night 'git log -1 --format="HEAD %h %cr: %s"; launchctl print system/se.skylink.nightly 2>/dev/null | grep -m1 "state ="
           pgrep -fl "nightly.sh|agent_proposals.py|agent_eval.py|skylink-sim run" | cut -c1-120 || true
           echo "-- runs/last-night.txt"; cat runs/last-night.txt 2>/dev/null || echo "(none yet)"
           df -g . | awk "NR==2 {print \"free disk: \" \$4 \" GB\" (\$4 < 20 ? \"  WARNING: under 20 GB, tell the owner\" : \"\")}"
           export PATH=/opt/homebrew/bin:$PATH
           if colima status >/dev/null 2>&1; then
             docker exec skylink-influxdb-1 du -sh /var/lib/influxdb2/engine/data 2>/dev/null \
               | awk "{print \"influx data: \" \$1 \" (raw leaves by run, after a verified cold export; docs/daily-loop.md)\"}" || true
             docker exec skylink-influxdb-1 df -Pk /var/lib/influxdb2 2>/dev/null \
               | awk "NR==2 {g=int(\$4/1048576); print \"VM disk (InfluxDB): \" g \" GB free of \" int(\$2/1048576) (g < 6 ? \"  WARNING: nightly runs stop under 6 GB\" : \"\")}" || true
           elif pgrep -f "limactl hostagent" >/dev/null; then
             echo "VM NOT ANSWERING: its process runs but colima status fails; containers: $(docker ps --format "{{.Names}}={{.Status}}" 2>&1 | tr "\n" " " | cut -c1-160)"
           else
             echo "VM off (by design by day, docs/vm-on-demand.md): influx data and VM disk sizes are the \"vm disk at end\" line of last night, above"
           fi'
  ;;
pull)
  mkdir -p runs/night/reports
  rsync -a --exclude ollama.log --exclude colima.log "$HOST:$DIR/runs/" runs/night/
  on_night 'git ls-files --others --exclude-standard reports' | while read -r f; do
    rsync -a "$HOST:$DIR/$f" runs/night/reports/
  done
  on_night 'git bundle create -q /tmp/skylink-back.bundle main'
  scp -q "$HOST:/tmp/skylink-back.bundle" runs/night/back.bundle
  git fetch -q runs/night/back.bundle main:refs/remotes/night/main
  if git merge-base --is-ancestor night/main main; then echo "pulled; the night host has no commits missing here"
  else echo "pulled; the night host has commits missing here: git log main..night/main"; fi
  ;;
answers)
  shopt -s nullglob; files=(runs/escalation/outbox/*.jsonl)
  [ ${#files[@]} -gt 0 ] || { echo "no answers in runs/escalation/outbox"; exit 0; }
  on_night 'mkdir -p runs/escalation/answers'
  rsync -a --ignore-existing "${files[@]}" "$HOST:$DIR/runs/escalation/answers/"
  echo "sent ${#files[@]} answer file(s); the night host applies them next night"
  ;;
push)
  if busy; then echo "a night job is running on the night host; push later" >&2; exit 1; fi
  [ -z "$(on_night 'git status --porcelain --untracked-files=no')" ] || { echo "the night host has uncommitted changes to tracked files" >&2; exit 1; }
  head=$(on_night 'git rev-parse HEAD')
  git cat-file -e "$head" 2>/dev/null && git merge-base --is-ancestor "$head" main \
    || { echo "the night host has commits missing here; run pull and merge night/main first" >&2; exit 1; }
  [ "$head" = "$(git rev-parse main)" ] && { echo "the night host is up to date"; exit 0; }
  b=$(mktemp -t skylink).bundle
  git bundle create -q "$b" main "^$head"
  scp -q "$b" "$HOST:/tmp/skylink.bundle"; rm -f "$b"
  on_night 'git fetch -q /tmp/skylink.bundle main && git merge -q --ff-only FETCH_HEAD && rm /tmp/skylink.bundle && git log -1 --format="night host now at %h: %s"'
  ;;
*) echo "usage: $0 status|pull|answers|push" >&2; exit 2;;
esac
