# Zerostack — the agent on the box, behind the same /pi

Zerostack (`gi-dellav/zerostack`, GPL-3.0, Rust) replaced Pi as the
agent on the box on 2026-11-20. Pi is not deleted: it stays installed
as the fallback, and rollback is one tunnel port change. The `/pi`
address, login, and look did not change — only the engine behind it.

## Install

One binary, no build needed (the box has no Rust toolchain):

```sh
curl -fsSL https://raw.githubusercontent.com/gi-dellav/zerostack/main/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"   # add to ~/.profile and ~/.bashrc
zerostack --help
```

Config lives at `~/.config/zerostack/config.toml`. Copy
`zerostack/config.toml.example` there and fill in your own provider
keys (environment variables only, never in the file) and your vault
Worker URL. Verify with a prompt and a session resume:

```sh
zerostack -p --name smoke-test "Say OK"     # expect: OK
zerostack -c -p "What did I just ask you to say?"   # expect: OK.
```

## The gateway — same /pi, new backend

Zerostack is terminal-only: no web page, no admin page, no HTTP
gateway. The gateway is rebuilt against its ACP interface:

| File | Purpose |
|---|---|
| `bridge/zs-gateway-rs/` | **Rust gateway (live since 2026-11-21)** — std HTTP server, port 8766, speaks ACP to Zerostack. 9 MB RSS vs the Python gateway's 19 MB. Build: `cargo build --release` (needs Rust on the box); binary at `/root/pi-bridge/zs-gateway`. Includes the full model system in `src/admin.html` (Add provider → Load models → tick to add → manual add → default + fallback order with Up/Down → fallback on/off) and key rotation. |
| `bridge/zs-gateway.py` | Python gateway (backup) — same endpoints, kept in case the Rust binary is missing. `zs-supervise.sh` runs Rust when the binary exists, Python otherwise. |
| `bridge/zs.html` | `pi.html` + a Pi \| Zerostack switcher (all pi.html fixes kept) |
| `bridge/zs-supervise.sh` | respawn loop so `/restart` is reliable |

Endpoints mirror `pi-gateway.py` exactly (`/pi`, `/admin`, `/stats`,
`/sessions`, `/prompt`, `/models`, plus transcript/status/events,
`/stop`, `/rename`, `/model`, `/compact`, `/restart`, `/switch`),
so the front end barely changes. Login is the same gateway token as
Pi's. `/stats` reports disk the same way: the workspace footprint
against the 10 GiB plan quota, not the host overlay.

Start it its own tmux session (never inside the Pi gateway's):

```sh
tmux new -d -s zs-gateway /root/pi-bridge/zs-supervise.sh
```

The gateway starts one Zerostack process per session
(`--acp --acp-host 127.0.0.1 --acp-port 7300-7399`); a session idle
for 15 min releases its process, and the next prompt respawns it and
replays the transcript digest.

## ACP — what Zerostack actually speaks

Verified against the source (`src/extras/acp/`) and on the wire.
Zerostack registers exactly **three** methods: `initialize`,
`session/new`, `session/prompt`. Consequences:

- **`session/cancel` does not exist** (returns `-32601 Method not
  found`). `/stop` ends the session's Zerostack process; there is no
  other stop.
- **No `session/load`, `session/list`, `session/resume`, or
  `session/set_model`.** Sessions live in an in-process map and die
  with the process. The gateway owns the transcript and replays a
  text digest after any respawn. `/compact` sets where replay starts.
- **`session/prompt` answers only at turn end.** `/prompt` returns
  immediately with `accepted:true`; streaming comes from
  `/sessions/{id}/events`.
- **MCP is disabled in ACP mode** (`mcp_manager: None`). Vault tools
  work in the Zerostack TUI, **not** through the gateway. The gateway
  does not pretend otherwise.
- The ACP TCP listener accepts exactly once, so one client per
  process — hence one Zerostack process per session.

## Switch and rollback

The tunnel points at one gateway port. To switch, edit
`/root/.cloudflared/config.yml` (`service:` 8765 → 8766, or back),
then restart cloudflared the safe way — never inside its tmux
session:

```sh
tmux kill-session -t pi-tunnel
tmux new-session -d -s pi-tunnel 'cloudflared tunnel --config /root/.cloudflared/config.yml run'
```

Verified 2026-11-20: tunnel → 8766 serves Zerostack Chat on the
live URL; back to 8765 serves Pi Chat; back to 8766 serves Zerostack
again. Lesson: a search fetch can serve a cached copy of the page for
minutes after a repoint — verify a switch with a fresh browser load,
not a fetch.

The switcher's Pi button needs a public Pi address:
`ZS_PI_URL` (env, read at gateway startup; default is the box-local
`http://127.0.0.1:8765/pi`, which does not open from a phone). Until a
second hostname exists for the Pi gateway, the Pi side is reached by
the rollback port change, not by the button.

## Search — ours only

`enable-exa-mcp = false` (top-level in the TOML — after a `[table]`
header it would belong to that table) removes Zerostack's built-in
Exa search. The only other removal is in the bundled prompts
(`data/prompts/`): where a prompt told the agent to search the web
with Exa, it now says to use `web.py research`. Context7 and
Grep.app stay exactly as upstream ships them. Search is the combined
system: TinyFish via Monid + the Bing cf-search Worker + X via
FxEmbed, driven by `web.py` (see `search/`).

## Known limits (verified, not assumed)

- **xingchi returns 403 `client_not_allowed`** in Zerostack. The
  provider only admits named coding clients (Codex, Cursor, Pi…);
  the Responses API fix does not help. The error surfaces into the
  transcript instead of hanging.
- **Vault MCP is unavailable through the gateway** (see ACP above).
  The locked path was verified in the Zerostack TUI: a vault call
  without a grant returns `unlock_required`, and it works once Muse
  unlocks. Use the TUI for vault tools until Zerostack gains MCP in
  ACP mode.
- **Sessions do not survive a gateway restart** as live processes;
  transcripts are restored from disk and replayed as a digest.
- **tokenlab** returned one transient 429 ("at capacity") during
  testing.

## Files

- Gateway + page + supervisor: `bridge/zs-gateway.py`,
  `bridge/zs.html`, `bridge/zs-supervise.sh`
- Config template: `zerostack/config.toml.example`
- This doc: `docs/ZEROSTACK.md`

The full customised build — search workers, all skills, real Worker
URLs, INSTALL.md/FEATURES.md — lives in the private repo, not here.
