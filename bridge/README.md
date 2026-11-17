# Muse → Pi bridge (Altare sandbox "pi")

## Standing delegation rule (2026-11-17)
Frequently delegate to Pi on Altare — token saving (Pi uses the user's
custom APIs, not Muse tokens), extra intelligence (second model /
second opinion), and better architecture (Pi double-checks designs).
Long-running, heavy, and architecture work goes to Pi by default.
Full policy: `~/workspace/altare-pi-setup/DELEGATION.md`.

Direct SSH from Muse's VM is blocked by its egress proxy, so Muse
doesn't SSH into the sandbox. Instead:

```
Muse --Files API--> /root/pi-bridge/inbox/<id>.json
watcher (tmux, on sandbox) --runs--> pi --model <model> -p "<prompt>"
watcher --writes--> /root/pi-bridge/outbox/<id>.json
Muse --Files API--> reads outbox, prints Pi's answer
```

## Files
- `watcher.py` — runs ON the sandbox at /root/pi-bridge/watcher.py
- `muse-pi.py` — runs HERE (Muse's VM), the tool Muse calls

## Start the watcher (once, after a sandbox restart too — no systemd)
In the sandbox web console / SSH:
```
tmux new -s pi-bridge -d 'python3 /root/pi-bridge/watcher.py'
```

## Use it (from Muse)
```
python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py ask --model moss/nex-n2.6 --prompt "Say OK"
python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py send --model xingchi/gpt-6.1-sol --prompt "long task..."   # returns id at once
python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py get <id>
python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py list
python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py status
python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py put ./code.py task1/code.py
python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py getfile task1/result.txt
```
Models: xingchi/gpt-6-astra, xingchi/gpt-6.1-sol,
tokenlab/DeepSeek-V4.1-Flash, moss/nex-n2.6,
howtofix/deepSeek-v4.1-flash-1017-sg, 100milionseek/deepseek-v4.1-flash-free

## Notes
- API keys live only as env exports in /root/.profile on the sandbox,
  never in models.json (which has $VAR references only) and never here.
- Altare Files API is flaky with transient Cloudflare 502s; muse-pi.py
  retries those after 65s.
- Files API paths are /rootfs/... (= sandbox /...). E.g. API
  /rootfs/root/pi-bridge/inbox = sandbox /root/pi-bridge/inbox.
- Long tasks: use `send`, then `get <id>` later. Pi runs in the
  watcher's subprocess, so Muse doesn't need to stay connected.
- After a sandbox restart, the watcher is gone — restart it in tmux.

## Web research (standing rule, 2026-11-17)
Pi must always use `/root/pi-bridge/search.py` for search/fetch — same
system as Muse: TinyFish free via Monid + DuckDuckGo + X via FxEmbed.
Default: `python3 /root/pi-bridge/search.py research "q"`.
Skill: `/root/pi-bridge/SKILL.md`, instructions in `/root/work/AGENTS.md`.
