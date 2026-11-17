# muse-pi-setup

MIT-licensed setup for **Muse controlling Pi on an Altare sandbox** — the
whole system, with all the code, so a friend can hand this repo to their
Muse and have it set up for them the same way.

Muse is the planner and the one that talks to you. Pi (open source,
MIT, `pi.dev`) is the second agent that runs on a free Altare sandbox
and does the long, heavy work on your own model APIs — so it costs your
API credits, not Muse tokens. Muse reaches Pi two ways: an HTTP gateway
over Tailscale (primary) and a file-queue bridge over the Altare Files
API (fallback). Pi never sees your keys for other services — for that,
see the companion vault below.

## What this is for

- You want a second coding agent that runs 24/7 on a free box.
- You want Muse to delegate long-running, heavy, or architecture work
  to it, and to keep one Pi session per topic.
- You want your own models (any OpenAI-compatible API) wired into Pi,
  with per-model settings.
- You want free web search/fetch for both Muse and Pi.
- You want the whole thing reproducible from one repo, not from memory.

## How it fits together

```text
You
  |
  v
Muse (your VM) — plans, talks to you, verifies
  |  pi-api.py (HTTP client)          |  muse-pi.py (Files API client)
  |  gateway-token.txt (chmod 600)    |  ALTARE_TEAM / ALTARE_SERVER
  v                                     v
Tailscale tailnet (100.x, :3130 proxy)   Altare Files API (console.altare.gg)
  |                                     |  inbox/*.json  ->  outbox/*.json
  v                                     v
Pi gateway (tmux `pi-gateway`, 127.0.0.1:8765)   Pi watcher (tmux `pi-bridge`)
  |  Bearer token in gateway.env              |  runs pi --model <m> -p "<prompt>"
  v                                             v
Pi 1.5.2 on the Altare sandbox "pi" (Ubuntu 24.04, free pool)
  models.json: 6 custom models, $VAR placeholders only
  provider keys: /root/pi-bridge/provider-keys.env (chmod 600) + /root/.profile
  settings.json: per-model contextWindow/maxTokens, compaction
```

The gateway is the primary path. The file-queue bridge is the fallback
(it also works when the tailnet is down). Both are included here.

**Optional companion:** [cf-d1-vault](https://github.com/0xSatwik/cf-d1-vault)
— a Cloudflare Worker + D1 secrets vault so Pi can call GitHub and any
other API without ever seeing the key. The vault is a separate repo;
this one does not include it. The search system below can also reach
APIs your machine cannot, through the vault's `service_request`.

## Prerequisites

- An Altare account (free tier is enough: 6 GB RAM, 150% CPU, 10 GB
  disk shared pool, up to 4 servers — see "Altare, the honest limits"
  below).
- A Muse VM (this repo assumes you are Muse, or an agent like it, with
  a Linux VM, Python 3, Node 20+, and `npx`).
- Tailscale on both machines (free personal plan).
- API keys for whichever models you want (see `pi/models.json`).
  Keys are never committed — they live only on the sandbox and in your
  own messages when you first supply them.
- A Monid account for free search (see `search/`).

## Setup

Give this repo to your Muse and have it follow these steps in order.
Each step ends with a check; do not skip the checks.

### 1. Create the Altare sandbox (manual — 10 minutes)

Team API tokens **cannot** create a sandbox (the API returns 403
`TOKEN_ROUTE_NOT_ALLOWED` by design). Create it in the Altare web
console while logged in:

1. Create a server in your team, region of your choice, using the full
   free pool (6 GiB RAM, 150% CPU, 10 GiB disk).
2. Add your SSH public key at creation. Note the server ID, the SSH
   host/port, and your team ID.
3. The console sometimes shows the server as "Offline" when it is
   actually alive — check by opening the web console terminal instead
   of trusting the status badge.

Altare sandboxes share the host kernel: **no Docker, no kernel
modules, no TUN device, no systemd**. Long-running processes go in
`tmux`, and must be restarted after a sandbox restart. Only one
network allocation exists (the SSH port); the gateway is reachable
only over Tailscale (step 5) or the cloudflared tunnel fallback.

Direct SSH from a Muse VM is usually blocked by the VM's egress proxy
(connection reset). Do not fight it — control the sandbox through the
web console, the Files API (`bridge/muse-pi.py`), and the tailnet.

### 2. Install Pi on the sandbox

In the sandbox web console (as root):

```bash
# Node 22 (Pi needs Node 22.19+)
# Install node via your preferred method, then:
npm install -g pi@1.5.2
pi --version   # expect 1.5.2
node --version # expect v22.x
```

Pi installs to `/root/.pi/agent/bin/pi`; make sure it is on PATH
(add it to `/root/.profile`).

### 3. Add your models

Pi's config lives in `/root/.pi/agent/` on the sandbox:

- `models.json` — providers and models. Copy `pi/models.json` from
  this repo as a starting point. It has **placeholders only**
  (`$XINGCHI_API_KEY`, ...). Never put a real key in this file.
- `settings.json` — per-model `contextWindow`/`maxTokens` and
  compaction. Copy `pi/settings.json` from this repo.

The six models this setup was built with (all OpenAI-compatible):

| Provider | Model | Base URL | Key env var |
| --- | --- | --- | --- |
| xingchi | gpt-6-astra | https://api.xingchiapi.com/v1 | `XINGCHI_API_KEY` |
| xingchi | gpt-6.1-sol | https://api.xingchiapi.com/v1 | `XINGCHI_API_KEY` |
| tokenlab | DeepSeek-V4.1-Flash | https://api.tokenlab.amd.com/v1 | `TOKENLAB_API_KEY` |
| moss | nex-n2.6 | https://api.mosi.cn/v1 | `MOSS_API_KEY` |
| howtofix | deepSeek-v4.1-flash-1017-sg | https://api.howtofix.id/v1 | `HOWTOFIX_API_KEY` |
| 100milionseek | deepseek-v4.1-flash-free | https://100milionseek.top/v1 | `HMS_API_KEY` |

Keys go in **two** places on the sandbox (both `chmod 600`, both
sandbox-only):

1. `/root/pi-bridge/provider-keys.env` — the gateway reads this at
   start. One line per provider, e.g. `XINGCHI_API_KEY=<key>`.
   A template is in `pi/provider-keys.env.example`.
2. `/root/.profile` and `/root/.bashrc` — `export XINGCHI_API_KEY=...`
   lines, so interactive shells and the file-queue watcher see them.

**Lesson:** a long-running process started *before* a key is added
does **not** see it — `.profile` only affects new shells. After adding
or rotating a key, restart the gateway (`pi-api.py restart`) and the
watcher. Use the gateway's `POST /models` route (via
`pi-api.py add-model ... --key-stdin`) to add a model + key in one
call — the key goes in through stdin, never in a file or a prompt.

Per-model settings (the values in `pi/settings.json`):

- tokenlab DeepSeek-V4.1-Flash: `contextWindow` 1,048,576 (verified
  via the provider's `/v1/models`), `maxTokens` 16,384.
- 100milionseek deepseek-v4.1-flash-free: `contextWindow` 198,000,
  `maxTokens` 65,536. Real-world note: the API's pre-check
  overestimates tokens (~0.303 tok/char vs ~0.2 real), so the practical
  max input is ~645K characters, not 198K tokens; every request is
  charged ~630 prompt tokens even for a tiny prompt.
- All other models: `contextWindow` 128,000, `maxTokens` 16,384
  (documented values where verifiable, kept as-is otherwise).
- Compaction is on (`reserveTokens` 16384, `keepRecentTokens` 20000),
  with an override for xingchi/gpt-6.1-sol (`reserveTokens` 65536).
  Use original documented values only — do not inflate them.

Check: `pi-api.py models` lists all six. Then test each one:
`pi-api.py prompt "Say OK" --model <provider/model>` should answer
`OK`.

**Provider quirks found the hard way:**

- **Xingchi rejects scripted/SDK clients** (`403 client_not_allowed`).
  Only coding clients (Pi itself) may call it. Test harnesses that
  call the API directly will score 0 — test Xingchi models through Pi
  instead (see `eval/`).
- **Xingchi model availability is per-account.** If a model returns
  `404 model_not_found` ("not supported by any configured account"),
  the key's account does not include that model — a different key
  (different account) is the fix.
- **Astra can also 503** ("Service temporarily unavailable") when the
  provider is having trouble — a smoke test can pass while a batch
  fails. Retry later; it is provider-side, not your setup.
- **moss dies empty on long sessions** (twice returned empty content
  and died without saving on 80+ message runs). Prefer
  xingchi/gpt-6.1-sol for long, multi-step work.
- **100milionseek keys can die without warning** (one key 401'd
  mid-test). If a model starts 401ing, rotate its key.

### 4. Install the bridge and the gateway on the sandbox

Copy `bridge/pi-gateway.py` and `bridge/watcher.py` to
`/root/pi-bridge/` on the sandbox (via the web console or
`muse-pi.py put` once the bridge is up — chicken-and-egg: use the
console the first time).

**Gateway** (primary path, HTTP API over the tailnet):

```bash
# on the sandbox, in tmux
tmux new -s pi-gateway
cd /root/pi-bridge
# generate a long random Bearer token, save it to gateway.env (chmod 600)
python3 -c "import secrets; print(secrets.token_hex(32))"  # put it in gateway.env as GATEWAY_TOKEN=<token>
python3 pi-gateway.py   # listens on 127.0.0.1:8765
```

The gateway wraps Pi in RPC mode. Endpoints: `/health`,
`/sessions`, `/prompt`, `/sessions/{id}/prompt|status|events|stop|
rename|model|compact`, `/models` (GET/POST/PATCH/DELETE), `/secrets`
(rotate a provider key), `/restart`, `/rpc`, `/files` (pulls from
`/root/work` only). Auth is the Bearer token. **Restart the gateway
after adding or rotating a key** (`POST /restart`, or
`pi-api.py restart`).

**Watcher** (fallback path, file queue):

```bash
# on the sandbox, in tmux
tmux new -s pi-bridge
cd /root/pi-bridge
python3 watcher.py   # watches /root/pi-bridge/inbox/, runs pi, writes outbox/
```

The watcher has no systemd — restart it in tmux after every sandbox
restart. The Altare Files API occasionally 502s; `muse-pi.py`
retries after 65 seconds.

### 5. Tailscale (the primary path)

1. Install Tailscale on the sandbox and on the Muse VM, and join both
   to the same tailnet.
2. Note the sandbox's tailnet IP. Save it as
   `bridge/tailnet-url.txt` next to `pi-api.py`, in the form
   `http://<sandbox-tailnet-ip>:8765` (a template is in
   `bridge/tailnet-url.txt.example`).
3. The **first** request to a new tailnet address needs one user
   approval — the user approves it once, then it works.
4. From the Muse VM, a direct connection to the tailnet IP comes back
   empty — `pi-api.py` routes it through the VM's tunnel proxy on
   port 3130 (derived from `HTTPS_PROXY`, overridable with
   `PI_GATEWAY_PROXY`). Do not remove that logic.
5. Fallback: a cloudflared tunnel on the sandbox gives a public URL
   (save it as `bridge/public-url.txt`). Note: some Muse VMs get 403
   on `trycloudflare.com` from their egress proxy, so the tunnel is a
   fallback only, not the primary path.

Check: `pi-api.py health` returns `{"ok": true}`.

### 6. Muse-side clients

Copy `bridge/` to your Muse VM (e.g.
`~/workspace/altare-pi-setup/pi-bridge/`). Two clients:

- **`pi-api.py`** — the gateway client (primary). Reads the URL from
  `tailnet-url.txt` (or `public-url.txt`) and the token from
  `gateway-token.txt` (chmod 600) in its own directory. Commands:
  `health`, `sessions`, `models`, `prompt "msg" [--session ID]
  [--model M]`, `status`, `events`, `stop`, `files`,
  `add-model <provider> <model-id> --base-url URL --env-name NAME
  [--key-stdin]`, `setkey <ENV_NAME>` (key via stdin), `restart`.
  `prompt` is async: it returns a session id and `started`; poll
  with `status`/`events`.
- **`muse-pi.py`** — the file-queue bridge client (fallback). Needs
  `ALTARE_TEAM` and `ALTARE_SERVER` in the environment (your Altare
  team and sandbox server IDs), and either `ALTARE_API_TOKEN` or the
  connected Altare Platform credential (Muse connector) for the Files
  API. Commands: `ask`, `send`, `get`, `list`, `status`, `put`,
  `getfile` (reads only under `/root/work/` on the sandbox).

Copy the gateway token into `bridge/gateway-token.txt` (chmod 600).
Generate it fresh — never reuse someone else's, never put it in chat.

Check: `pi-api.py prompt "Say OK" --model xingchi/gpt-6.1-sol`
answers `OK`, and `muse-pi.py ask --model moss/nex-n2.6 --prompt
"Say OK"` also answers `OK`.

### 7. Search and fetch (both Muse and Pi)

Both agents use the same free system — never the paid endpoints, never
a key written literally in a file. See `search/SEARCH.md` and the skill
in `skills/web-research/`:

- **Tool:** `search/web.py` — TinyFish free search+fetch via a Monid
  key (`$0`; search 12k/day, fetch 1k/day) + DuckDuckGo Lite fallback
  + X/social via FxEmbed (descriptive User-Agent mandatory).
- **Default command:** `python3 search/web.py research "query"` —
  web results from both engines (deduped) + an X ask pack + fetch of
  the top 5 URLs. If it times out on the X leg, `search` (web-only)
  is the fallback.
- **Monid key:** only in `~/.config/monid/credentials.yaml`
  (chmod 600) on the Muse VM, and as `$MONID_API_KEY` on the sandbox.
  Pi uses the same file at `/root/pi-bridge/search.py` (copy
  `search/web.py` there).
- **Cloudflare-blocked sites:** when a site 403s every direct request
  (even no-auth, even the site root), the egress is blocked, not the
  key. Ladder: (1) `web.py` TinyFish fetch/search first (server-side,
  often gets pages direct fetch cannot); (2) a browser task — a fresh
  browser/route can clear the block; (3) the vault Worker's
  `service_request` (it runs on Cloudflare's own network); (4) Pi
  sandbox egress, last resort. Never paste keys into browser tasks or
  Pi prompts — put the key in the vault, unlock it for Pi, and let Pi
  call it via `service_request`.

### 8. Sessions and delegation rules

These are the rules that make the two-agent setup work day to day
(full text in `AGENTS.md` and `DELEGATION.md` — include them in your
Muse's own operating manual):

- **Delegate frequently.** Long-running, heavy, or architecture work
  goes to Pi — it saves Muse tokens (Pi runs on your own APIs), gives
  a second opinion, and double-checks designs.
- **One Pi session per topic, reuse by default.** Never a fresh
  session when a topic already has one. Keep a registry
  (`pi/pi-sessions.template.json` — start from this). Continue with
  `pi-api.py prompt --session <id>`; compact a session when it gets
  long; start fresh only if a session dies or gets confused.
- **Prefer xingchi/gpt-6.1-sol for long sessions** (moss dies empty
  on long runs).
- **Report real progress.** Silence during delegated work reads as
  stalled work — check the session, report file-by-file progress, and
  say plainly when a model died empty.
- **Verify before trusting.** A claim counts once it is confirmed
  (on-chain, on the page, in the file), not when it is asserted.

## Verify the whole setup

Run these in order; all of them should pass:

```bash
pi-api.py health                                  # {"ok": true}
pi-api.py models                                  # all six models listed
pi-api.py prompt "Say OK" --model xingchi/gpt-6.1-sol   # OK
pi-api.py prompt "Say OK" --model xingchi/gpt-6-astra   # OK
pi-api.py prompt "Say OK" --model moss/nex-n2.6         # OK
muse-pi.py ask --model moss/nex-n2.6 --prompt "Say OK"  # OK (fallback path)
python3 search/web.py research "pi agent"         # web results + fetches
```

If the gateway path fails but the bridge path works, the tailnet is
the problem (check Tailscale on both machines and the `:3130` proxy).
If both fail, check the tmux sessions on the sandbox
(`tmux ls` — `pi-gateway` and `pi-bridge` must both be alive).

## Optional: the secrets vault

If Pi needs to call GitHub or any other API, do **not** give it the
key. Use the companion repo
[cf-d1-vault](https://github.com/0xSatwik/cf-d1-vault): a Cloudflare
Worker + D1 vault (free tier) where keys are AES-256-GCM encrypted,
Pi holds only a request-only token, and Muse unlocks one service + one
key label for two hours at a time. Pi never sees a key. The vault is a
separate repo with its own full guide.

## Optional: test your models

`eval/` has the harness setup used to rate the six models — promptfoo
(config + assertions), EvalScope, and Orq Arena — plus the Pi-way
runner. The key lesson: **Xingchi blocks harness clients**, so
harness scores for Xingchi models are 0 by policy, not by quality.
Score them through Pi itself (`eval/run-pi-way.py`), and keep the
Pi-way numbers separate from direct-harness numbers — the same model
scores differently through Pi (the control proved it: moss scored
23/30 ARC direct, 30/30 through Pi). Example results from the
author's run are in `eval/SUMMARY.md`: tokenlab DeepSeek-V4.1-Flash
first (ARC 28/30), 100milionseek second (27/30), moss third (23/30);
howtofix was down, Xingchi unscored by the harnesses.

## Lessons baked in

- **Workers fetch rejects `redirect: 'error'`.** Only `'follow'` or
  `'manual'` are valid at the edge (vault lesson, but the same applies
  to any Worker you write).
- **Deploy propagation is not instant.** Edge nodes can serve the
  previous version for seconds; retry once before debugging.
- **The locked path is not the whole test.** A locked call returning
  `unlock_required` proves authorization; only a granted call against
  a real upstream proves the full chain.
- **A site 403ing everything is an egress block, not a key problem.**
  See the ladder in step 7.
- **Long-running processes do not see keys added later.** Restart
  the gateway and the watcher after any key change.
- **The events endpoint is unreliable for monitoring.** File state
  (`/root/work/model-eval/`, the outbox) is the ground truth; a
  session can be progressing while events look frozen.
- **One session per topic.** Fresh sessions lose context; the registry
  is the source of truth, not the gateway's session list.

## Security

- No secret is ever in this repo: no API keys, no tokens, no
  passwords, no private keys. Files that hold them
  (`gateway-token.txt`, `provider-keys.env`, `tailnet-url.txt`,
  `public-url.txt`) are in `.gitignore` — only `.example` templates
  are committed.
- Keys live only on the sandbox (`chmod 600`) and in your own
  messages when you first supply them. They are passed to the gateway
  through stdin (`--key-stdin` / `setkey`), never as arguments, never
  in a file on the Muse VM, never in chat beyond your own message.
- A Pi *model* key is visible to the Pi process by design (it has to
  call the provider). The vault exists for keys Pi *calls via MCP* —
  those Pi never sees.
- Rotate a key with `pi-api.py setkey <ENV_NAME>` (stdin), keep a
  backup of `provider-keys.env` on the sandbox first, and restart the
  gateway afterwards.

## Repository layout

```text
README.md            this guide
LICENSE              MIT
AGENTS.md            the author's operating manual: delegation, search, lessons
DELEGATION.md        the Pi delegation + sessions rules
bridge/
  pi-api.py          Muse-side gateway client (primary path)
  muse-pi.py         Muse-side file-queue bridge client (fallback path)
  pi-gateway.py      the gateway that runs on the sandbox (tmux pi-gateway)
  watcher.py         the file-queue watcher that runs on the sandbox (tmux pi-bridge)
  README.md          bridge notes
  tailnet-url.txt.example / public-url.txt.example
pi/
  models.json        Pi models (placeholders only) — copy to ~/.pi/agent/
  settings.json      per-model contextWindow/maxTokens + compaction
  models-multi.json  provider reference (base URLs, env var names)
  provider-keys.env.example
  pi-sessions.template.json
search/
  web.py             free search/fetch (TinyFish + DuckDuckGo + X)
  SEARCH.md          search system notes
skills/
  web-research/SKILL.md   the research skill (Muse + Pi)
docs/
  pi-per-model-settings-applied.md
  atria-recheck-20261117.md
  research/          the Cloudflare-vault research reports
eval/
  promptfoo.config.json, assertions.cjs   promptfoo setup
  run-pi-way.py      score models through Pi itself
  SUMMARY.md         example results from the author's run
```

## License

MIT.
