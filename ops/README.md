# Night schedule (not installed)

`scripts/nightly.sh` is safe to run by hand: it refuses to start outside 23:00-06:00 Europe/Stockholm
(`FORCE=1` overrides), runs niced, and ends each run at 06:00 with a checkpoint.

To schedule it, copy the plist below to `~/Library/LaunchAgents/` and load it. That is outside the
repo, so it needs the owner's approval. The Mac must be awake: either `pmset repeat wake` at 22:55
or leave the Mini on (it is always on).

```xml
<plist version="1.0"><dict>
 <key>Label</key><string>se.skylink.nightly</string>
 <key>ProgramArguments</key><array><string>/bin/bash</string><string>REPO/scripts/nightly.sh</string></array>
 <key>StartCalendarInterval</key><dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>0</integer></dict>
 <key>StandardOutPath</key><string>REPO/runs/nightly.log</string>
 <key>StandardErrorPath</key><string>REPO/runs/nightly.log</string>
 <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict></plist>
```
Replace `REPO` with the absolute path. launchd uses the machine's local timezone for the start time.
