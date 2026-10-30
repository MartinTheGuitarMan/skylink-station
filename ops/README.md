# Night schedule

`scripts/nightly.sh` is safe to run by hand: it refuses to start outside 23:00-06:00 Europe/Stockholm
(`FORCE=1` overrides), runs niced, and ends each run at 06:00 with a checkpoint.

## On the night host (installed as system daemons, no login needed)
`sudo bash ops/install-daemons.sh` installs two LaunchDaemons that run as the user who called sudo, at boot (the `*.plist.template` files are filled in with that user and this checkout's path):
- `se.skylink.ollama`: the local model server on the night host (127.0.0.1:11434, one model loaded at a time).
- `se.skylink.nightly`: starts `scripts/nightly.sh` at 23:00. The script starts the Docker VM (colima) and the stack, runs the night,
  and stops both on exit (`scripts/vm.sh`, `docs/vm-on-demand.md`). `VM_STOP_AFTER_NIGHT=0` in `.env` turns the stop off.
There is no VM daemon: the former `se.skylink.colima` (KeepAlive, RunAtLoad) would restart the VM the moment it stops. The installer retires it.
The earlier per-user agent (`~/Library/LaunchAgents/se.skylink.nightly.plist`) is renamed `.disabled`.
Remove: `sudo launchctl bootout system/se.skylink.nightly system/se.skylink.ollama; sudo rm /Library/LaunchDaemons/se.skylink.*.plist`.
Logs: `runs/colima.log`, `runs/nightly.log`; one line per item of the last night in `runs/last-night.txt`.

## Switching the night host to a VM that is off by day (owner, on the night host)
Do it in the day (07:00-21:00), with no night job running. No sudo is needed for steps 1-3; only step 4 is admin.
1. From the day host: `scripts/night-sync.sh status` (nothing running), then `scripts/night-sync.sh push` once this branch is merged to main.
2. On the night host, in the checkout: `git log -1 --oneline` shows the merged commit. `grep -c VM_ .env` may be 0; the defaults are right
   (4 CPU, 6 GB, 100 GB disk, stop after the night). Nothing to add.
3. Optional dry run of the new path, still in the day: `scripts/vm.sh state` (on), `scripts/vm.sh down` (compose stop, colima stop,
   about 20 s), `scripts/vm.sh state` (off), then `scripts/vm.sh up && scripts/vm.sh stack` (cold start, a few minutes) and
   `docker ps` (four containers healthy/up), then `scripts/vm.sh down` again. Check the data: `docker volume ls` shows `skylink_influx-data`
   before and after.
4. As an admin: `sudo bash ops/install-daemons.sh`. It retires `se.skylink.colima` (bootout, removes its plist), runs `docker compose stop`
   and `colima stop`, reinstalls `se.skylink.ollama` and `se.skylink.nightly` (the nightly plist now has `AbandonProcessGroup`).
   Then `launchctl list | grep skylink` lists `se.skylink.nightly` and `se.skylink.ollama`, not `se.skylink.colima`, and `colima status` says
   it is not running.
5. After the first night: `scripts/night-sync.sh status` (VM off, last night's lines end with `vm: stopped` and a `vm disk at end` line)
   and `scripts/night-sync.sh pull`.
Back out: set `VM_STOP_AFTER_NIGHT=0` in the night host's `.env` (the VM then stays on after a night, started by the script) and, to get
the always-on VM back, `git revert` the commit and run the installer again.
