#!/bin/bash
# Run ON THE MACHINE THAT RUNS THE STACK, as an admin: sudo bash ops/install-daemons.sh
# The daemons run as the user who called sudo (SUDO_USER) and point at this checkout.
# Replaces the per-user nightly agent with two system daemons that run as your user at boot,
# with nobody logged in: ollama (local model server, localhost only) and the nightly job.
# The Docker VM (colima) has no daemon any more: scripts/nightly.sh starts it for the night and stops it after
# (scripts/vm.sh, docs/vm-on-demand.md). An old se.skylink.colima daemon is retired here (it would restart the VM at once).
set -u
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
U=${SUDO_USER:?run with sudo from your own account}; UID_U=$(id -u $U)
REPO="$(dirname "$HERE")"
sudo -u $U launchctl bootout gui/$UID_U/se.skylink.nightly 2>/dev/null || true
sudo -u $U mv /Users/$U/Library/LaunchAgents/se.skylink.nightly.plist /Users/$U/Library/LaunchAgents/se.skylink.nightly.plist.disabled 2>/dev/null || true
# retire the always-on VM daemon first (KeepAlive would start the VM again), then bring the stack and the VM down
if [ -f /Library/LaunchDaemons/se.skylink.colima.plist ] || launchctl print system/se.skylink.colima >/dev/null 2>&1; then
  launchctl bootout system/se.skylink.colima 2>/dev/null || true
  rm -f /Library/LaunchDaemons/se.skylink.colima.plist
  echo "retired: se.skylink.colima"
fi
sudo -u $U env HOME=/Users/$U PATH=/opt/homebrew/bin:$PATH bash -c "cd '$REPO' && docker compose stop; colima stop" 2>/dev/null || true
for l in ollama nightly; do
  sed -e "s|__REPO__|$REPO|g" -e "s|__USER__|$U|g" "$HERE/se.skylink.$l.plist.template" > "/tmp/se.skylink.$l.plist"
  install -m 644 -o root -g wheel "/tmp/se.skylink.$l.plist" /Library/LaunchDaemons/se.skylink.$l.plist; rm -f "/tmp/se.skylink.$l.plist"
  launchctl bootout system/se.skylink.$l 2>/dev/null || true
  sleep 3                                   # bootout is asynchronous; bootstrapping too early fails with I/O error
  ok=0
  for try in 1 2 3 4; do
    if launchctl bootstrap system /Library/LaunchDaemons/se.skylink.$l.plist 2>/dev/null; then ok=1; break; fi
    sleep 4
  done
  [ $ok = 1 ] && echo "loaded: se.skylink.$l" || echo "FAILED to load se.skylink.$l (see: sudo launchctl print system/se.skylink.$l)"
done
sleep 5
launchctl list | grep skylink || true
