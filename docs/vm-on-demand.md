# The Docker VM is on only at night

Decided 2026-10-30. The colima VM on the night host held about 1.5 GB of the Mac's RAM around the clock (VM process 1.4 GB, plus
helpers) so that four containers could sit idle by day. Bigger local models need that memory in the 06:00 and 22:00 windows. So
the VM now lives only as long as a job needs it.

## How it works
- `scripts/vm.sh` is the one place that starts and stops it: `up` (colima start, wait for Docker, bounded), `stack`
  (`docker compose up -d`, wait for InfluxDB healthy, bounded), `down` (`docker compose stop`, then `colima stop`), plus leases.
- `scripts/nightly.sh` runs `up` and `stack` after the window check, and `down` from its EXIT trap, so it also runs after a failure,
  a window stop, or a TERM. A failed start writes `failed: docker VM did not start` or `failed: docker stack not available` into
  `runs/last-night.txt` and the night is logged in `runs/night-log.tsv` (a visible failed night, not a silent one).
- `down` never stops the VM under a job: it keeps it up while a lease holder is alive (`scripts/vm.sh lease <pid>`) or a
  `skylink-sim`, `agent_*`, `verdict` or `escalate` process runs, and says so in the summary (`vm: kept up: ...`).
- The switch: `VM_STOP_AFTER_NIGHT=0` in the night host's `.env` leaves the VM running after the night (old behaviour, minus the daemon).
- Waits: `VM_WAIT_S` (Docker, default 240 s) and `INFLUX_WAIT_S` (default 240 s). VM size: `VM_CPU=4`, `VM_MEMORY=6`, `VM_DISK=100`.
- Before stopping, the night writes `vm disk at end: influx data <size>; VM disk <n> GB free of <m>` to `last-night.txt`: by day there
  is no VM to ask, so the daily pass's disk watch reads that line.
- No daemon keeps the VM alive any more (`se.skylink.colima` is retired by `ops/install-daemons.sh`).

## Data survives a stop
InfluxDB, Grafana and Node-RED data sit in named Docker volumes on the VM disk (`docker-compose.yml`). `compose stop` keeps containers
and volumes, `colima stop` keeps the VM disk image; only `colima delete` or `docker compose down -v` (`make wipe`) removes them.
The containers are `restart: unless-stopped`; after a `compose stop` they stay stopped until `vm.sh stack` starts them.

## What is off by day
- Grafana (port 3000), Node-RED (1880), River (8000) and InfluxDB (8086) are not reachable by day. Start the VM by hand to look
  at a dashboard: `scripts/vm.sh up && scripts/vm.sh stack`, and `scripts/vm.sh down` afterwards (it refuses while a job runs).
- `scripts/night-sync.sh status` prints `VM off` instead of the size lines; sizes come from last night's `vm disk at end` line.
- `scripts/drop-raw.sh` starts the VM and stack itself when they are off, leases it while it runs and stops it again.
- Daytime uses that need no Docker: the daily pass (`night-sync.sh pull`, `verdict.py decide`, `escalate.py` answers, reports from
  files), `missed_passes.py`, `day-agent.sh` (LM Studio on the day host). Anything that reads InfluxDB (`verdict.py collect`, the sim,
  `escalate.py night`, agent and proposal runs) runs inside the night.

## Another job that needs Docker in the night window
The coding bench's sandbox in `mcp-minions` needs Docker around 22:00 and 06:00. It must start the VM itself, after its models have
generated, and stop it after:
`scripts/vm.sh up` (no `stack`: the sandbox needs Docker only), `scripts/vm.sh lease $$`, its work, `scripts/vm.sh unlease $$`,
`scripts/vm.sh down`. The lease stops the nightly job's `down` from pulling the VM at 06:00 under it; `down` is a no-op while a
lease is live. If the bench's own Docker VM is a different colima profile, none of this applies.

## Cold start and the pre-registered criteria
No threshold, metric, queue or locked seed changes. Results cannot change: the edge service rebuilds all stream state on `/config`,
which the simulator posts at the start of every run and every resume (`src/skylink/edge/engine.py` `configure`), and the checkpoint holds
generator state, not River state. A cold container is the same as the reset that already happens. Node-RED's link state is reset the
same way. What can change is timing: a cold start costs 1-3 minutes of the 23:00 window (the queue is sized by the 06:00 end, so a
run may be cut and resumed one block earlier than before), and the first minutes of a night have cold caches (Influx page cache,
River's Python imports). C2 is measured on the designated 1x run's mean core, max RSS and p99 step over the whole run, which is
hours long; a cold first minute is inside that. If a C2 reading is ever close to a budget, check the first minutes first.
Not yet observed on the real host.
