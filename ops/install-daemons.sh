#!/bin/bash
# Run ON THE MINI as an admin: sudo bash ops/install-daemons.sh
# Replaces the per-user nightly agent with three system daemons that run as `USER` at boot,
# with nobody logged in: colima (Docker VM), ollama (local model server, localhost only) and the nightly job.
set -u
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
U=USER; UID_U=$(id -u $U)
sudo -u $U launchctl bootout gui/$UID_U/se.skylink.nightly 2>/dev/null || true
sudo -u $U mv /Users/$U/Library/LaunchAgents/se.skylink.nightly.plist /Users/$U/Library/LaunchAgents/se.skylink.nightly.plist.disabled 2>/dev/null || true
sudo -u $U env HOME=/Users/$U PATH=/opt/homebrew/bin:$PATH colima stop 2>/dev/null || true
for l in colima ollama nightly; do
  install -m 644 -o root -g wheel "$HERE/se.skylink.$l.plist" /Library/LaunchDaemons/se.skylink.$l.plist
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
