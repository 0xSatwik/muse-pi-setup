# Delegate long work to Pi on Altare

## The setup (from the muse-pi-setup repo, latest)

- Pi 1.5.2 runs on the Altare sandbox "pi" (Ubuntu 24.04, 6 GiB RAM, 175% CPU, 10 GiB disk) or a Hoody computer (Debian 13). Gateway on :8765, Admin page at the tunnel URL.
- **Default model is 100milionseek/deepseek-v4.1-flash-free** (set in settings.json as defaultProvider + defaultModel). A prompt that names no model uses it.
- 6 models: 100milionseek deepseek-v4.1-flash-free (default), xingchi gpt-6.1-sol + gpt-6-astra, tokenlab DeepSeek-V4.1-Flash, moss nex-n2.6, howtofix deepSeek-v4.1-flash-1017-sg.
- **Xingchi is BROKEN as of 2026-11-19**: /v1/chat/completions returns 400 chat_completions_disabled — the provider wants /v1/responses (Responses API) instead. Do NOT use xingchi models until fixed. Use 100milionseek for long work now.
- Never use Altare Inference models for Pi. Never put a model key in models.json, in chat, or in a workspace file — models.json holds $VAR placeholders only.

## Two paths to Pi (gateway first, bridge as fallback)

- **Primary: pi-api.py** (HTTP client to the gateway over the Tailscale tailnet, sandbox 100.82.51.43, via proxy :3130). `pi-api.py prompt "task" --session <id> [--model <m>]` — message is the FIRST positional arg, flags after. `pi-api.py status <id>` takes a positional id, NOT --session.
- **Fallback: muse-pi.py** (file-queue bridge via the Altare Files API, inbox/outbox JSON under /root/pi-bridge/). `muse-pi.py ask --model <m> --prompt "..."` for short work, `send` + `get <id>` for long work. `put <local> <remote>` uploads (lands at /root/work/<remote>), `getfile <remote> <local>` pulls back.
- The Altare Files API occasionally 502s — muse-pi.py retries after 65s; a getfile that fails twice is the API, not the file.
- The watcher (tmux `pi-bridge`) has no systemd — restart it after a sandbox restart. Ctrl-C ends the session (its only process is the watcher), so recreate it: `tmux new -s pi-bridge -d 'cd /root && exec python3 /root/pi-bridge/watcher.py'`. The gateway (tmux `pi-gateway`) and tunnel (tmux `pi-tunnel`) are separate sessions — do not touch them when restarting the watcher.
- Do NOT restart pi while the Altare node shows a "running short of resources" warning (host oversubscription, not pi's fault).

## Keys live in TWO places (lesson 2026-11-19)

- **Gateway store:** /root/pi-bridge/provider-keys.env (chmod 600). The Admin page writes keys here. Gateway sessions use these.
- **Watcher store:** /root/.profile (and /root/.bashrc) as `export KEY=...` lines. The ask-route watcher loads /root/.profile itself at startup (load_profile_env), so it ONLY sees keys that are there.
- **Admin-page keys do NOT reach the ask route.** After adding a key via the Admin page, copy it into /root/.profile too (Pi can read it from provider-keys.env — never print the value) and restart the watcher so it picks it up.
- After adding or rotating ANY key, restart the gateway (`pi-api.py restart`) AND the watcher — a long-running process started before the key was added cannot see the new key.
- To add a model + key in one call, use the gateway's POST /models route via `pi-api.py add-model ... --key-stdin` — the key goes in through stdin, never in a file or a prompt.

## Reuse one session per topic

- Look up the topic in the session registry at ~/workspace/altare-pi-setup/pi-bridge/pi-sessions.json before you start Pi work, and continue the registered session for that topic instead of starting a fresh one.
- Continue the registered session with pi-api.py prompt using the session id from the registry, so Pi remembers the topic and earlier decisions.
- Register a new topic in the registry when no session exists for it, and record its session id there for the next delegation.
- Compact a long session when it grows long instead of abandoning it, and start fresh only when a session dies or gets confused.
- Treat a reused session that returns empty twice with no saved file as dead, then start a fresh session for the topic and register the new session id. (2026-11-19: tunnel-search session 01a1f1d6 died empty 6x — replaced by fresh session 01a1f316.)
- Moss twice returned empty and died without saving on long work; Sol has now done the same on long reviews. Prefer the default 100milionseek model for long sessions until xingchi is fixed.

## Send the work so it survives

- Tell Pi to write its result to a named file on the sandbox and to save progress to that file as it goes, instead of holding the whole answer until the end.
- Ask Pi for a compact final report that fits in one save, since a very long report in one reply is the shape that died empty before.
- Send any files Pi needs with put before the work starts and pull results back with getfile after Pi reports the file exists.
- Tell Pi to use the web research search script (/root/pi-bridge/search.py) for any web research, so search and fetch stay on the free combined system (TinyFish + cf-search Worker + X via FxEmbed). The cf-search Worker URL lives in CF_SEARCH_URL (env export), never hardcoded.
- Update existing files in place — never a second live copy of a config; .bak backups fine, staging copies deleted.

## Report progress before the user chases

- Check the sandbox result file yourself at regular intervals while a long Pi session runs, instead of waiting for Pi to announce that it finished.
- Report real file level progress to the user before the user has to ask, and name the files that already exist and the files still missing.
- Say plainly when a Pi session died empty or produced no file, and state what you will recover or restart next.
- Answer a direct question about whether the work is running at once with the last check and the next check time.

## Recover a dead or empty session

- Treat an empty reply with no saved file as a failed session, not as a session that is still working.
- Recover the lost work from the session transcript when the file is missing, then restart the task on the default model with a shorter prompt and an earlier save.
- Split a task that died twice into smaller pieces with a saved file for each piece, instead of resending the same long prompt unchanged.
- Verify the recovered file by reading it back from the sandbox before telling the user the work is done.

## Available connectors

- Use muse.connector_search to find other connectors and muse.skill_search to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with Custom Connectors and MCPs, or build a custom connector.

## Alternatives for better results

- Do short work yourself in Muse instead of delegating it, since delegation adds a queue and a file round trip.
- Ask Pi for a second opinion on a design before you build it, instead of asking Pi to review a finished build only.
- Keep the file queue bridge as the fallback when the direct API fails, instead of retrying a blocked route.
