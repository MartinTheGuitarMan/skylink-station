# Night schedule

`scripts/nightly.sh` is safe to run by hand: it refuses to start outside 23:00-06:00 Europe/Stockholm
(`FORCE=1` overrides), runs niced, and ends each run at 06:00 with a checkpoint.

## On the Mini (installed as system daemons, no login needed)
`sudo bash ops/install-daemons.sh` installs three LaunchDaemons that run as the user who called sudo, at boot (the `*.plist.template` files are filled in with that user and this checkout's path):
- `se.skylink.colima`: keeps the Docker VM up (restarts it if it dies). The containers have
  `restart: unless-stopped`, so the stack comes back by itself.
- `se.skylink.ollama`: the local model server on the Mini (127.0.0.1:11434, one model loaded at a time).
- `se.skylink.nightly`: starts `scripts/nightly.sh` at 23:00.
The earlier per-user agent (`~/Library/LaunchAgents/se.skylink.nightly.plist`) is renamed `.disabled`.
Remove: `sudo launchctl bootout system/se.skylink.colima system/se.skylink.nightly; sudo rm /Library/LaunchDaemons/se.skylink.*.plist`.
Logs: `runs/colima.log`, `runs/nightly.log`.
