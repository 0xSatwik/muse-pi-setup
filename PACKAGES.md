# Pi packages: context-mode, pi-mcp-adapter, pi-hermes-memory, pi-lens

Four Pi packages extend the agent on the sandbox. Each owns a different
layer, and together they are the ONLY packages installed — in particular,
**pi-hermes-memory is the one and only memory system** (do not add
pi-memory or any other memory package).

| Package | Layer it owns | Tools it adds |
|---|---|---|
| `context-mode` (mksglu) | Tool-output size: sandboxed code execution + FTS5 index of big outputs | `ctx_execute`, `ctx_batch`, `ctx_index`, `ctx_search`, `ctx_resume`, `ctx_stats`, `ctx_doctor` |
| `pi-mcp-adapter` (nicobailon) | MCP transport: replaces Pi's built-in MCP with one proxy tool | `mcp` |
| `pi-hermes-memory` (chandra447) | Durable memory (the only memory system) | `memory_add`, `memory_search`, `memory_update`, `memory_remove`, `session_search`, `skill_manage` |
| `pi-lens` (apmantza) | Edit-time code feedback: LSP, linters, formatters, ast-grep | `lens_diagnostics` + diagnostics injected into edit results |

No tool names collide (`ctx_*` vs `memory_*` vs `mcp` vs `lens_*`), and the
layers do not overlap:

- context-mode indexes *tool outputs* and keeps a tiny (≤2 KB) session
  state block. It stores no durable facts.
- Hermes stores *durable facts and session history* — nothing else does.
- The adapter *replaces* the built-in MCP; both never run at once.
- pi-lens only reacts to file edits.

## Install

On the sandbox (as root):

```bash
pi install npm:context-mode
pi install npm:pi-mcp-adapter
pi install npm:pi-hermes-memory
pi install npm:pi-lens
```

Then two required follow-ups:

1. **Re-add `+codemode` to `defaultTools`** in `~/.pi/agent/settings.json`.
   With the adapter replacing the built-in MCP, Pi's codemode (the way the
   cf-d1-vault MCP server is exposed) only turns on when `+codemode` is in
   `defaultTools`. Without it, vault access silently changes shape.
2. **Approve pi-lens's blocked install script** (npm blocks it by default):

   ```bash
   cd ~/.pi/agent/npm
   npm install-scripts approve @ast-grep/cli
   ```

   Verify: `~/.pi/agent/npm/node_modules/.bin/ast-grep --version`.

Restart the gateway afterwards (`POST /restart` on the gateway, or the
Admin page's restart) so sessions pick up the packages.

## Prerequisite: Node 24

**context-mode requires Node ≥ 24.15.0** (`engines` in its package.json).
The sandbox image ships Node 22, which is fine for Pi itself and for the
other three packages (pi-lens needs ≥ 22.19). Install Node 24 alongside —
do not remove Node 22:

```bash
VER="v24.22.3"   # latest clean 24.x ≥ 24.15.0 at time of writing
curl -fsSL -o /tmp/node.tar.gz "https://nodejs.org/dist/$VER/node-$VER-linux-x64.tar.gz"
mkdir -p /opt/node24
tar -xzf /tmp/node.tar.gz -C /opt/node24 --strip-components=1
ln -sf /opt/node24/bin/node /usr/local/bin/node
ln -sf /opt/node24/bin/npm  /usr/local/bin/npm
ln -sf /opt/node24/bin/npx  /usr/local/bin/npx
```

`/usr/local/bin` precedes `/usr/bin` in PATH, so `pi` (a `#!/usr/bin/env
node` script) now runs on Node 24. Verify with `node --version` and
`pi --version`.

## How memory stays tiny (pi-hermes-memory)

Hermes is used in its default **policy-only** mode, which is the
token-light design:

- The system prompt carries only a compact `<memory-policy>` note telling
  the agent *when* to call `memory_search`. Full memories are **never**
  injected into the prompt — recall is a tool call, so a memory lookup
  costs a few hundred tokens, not a context dump.
- The curated core is a Markdown file (`~/.pi/agent/pi-hermes-memory/MEMORY.md`),
  capacity-capped with automatic consolidation. Measured on the live box
  after the first stored memory: **193 bytes**.
- Extended/session history lives in a SQLite FTS5 database
  (`sessions.db`, same folder). Measured: 4 KB main file plus a ~2.4 MB
  write-ahead log before checkpoint (the WAL shrinks back on checkpoint;
  the stored text itself is small). Per-project memory lives in
  `~/.pi/agent/projects-memory/` (468 KB measured, mostly FTS index).
- Do **not** set `memoryMode: "legacy-inject"` — that restores the old
  inject-everything behavior and burns tokens on every turn.

## Problems faced (all hit and fixed on 2026-11-19, live box)

### Node upgrade for context-mode

1. **Version picker crashed on prereleases.** Parsing `nodejs.org/dist/index.json`
   naively (`int()` on each version part) dies on entries like
   `v25.0.0-alpha` (`ValueError: invalid literal ... '0-alpha'`). Fix: only
   accept versions matching `^v\d+\.\d+\.\d+$`, or pin the exact version
   (we pinned `v24.22.3`).
2. **The sandbox has no `xz`.** The `.tar.xz` Node archive fails with
   `tar (child): xz: Cannot exec`. Fix: use the `.tar.gz` archive instead —
   same release, no extra packages needed.

### pi-lens

3. **`@ast-grep/cli` postinstall is blocked by npm** (`npm warn
   install-scripts`). The package "installs" but the ast-grep binary never
   gets set up. Fix: `npm install-scripts approve @ast-grep/cli` inside
   `~/.pi/agent/npm`, then verify `ast-grep --version`.
4. **First diagnostics probe can time out.** On a cold language-server
   start, pi-lens reported `inconclusive=1` ("check didn't complete within
   the wait budget") — which it correctly distinguishes from "clean". A
   retry with a 60 s wait returned the real findings. Files outside any
   tsconfig project are checked with inferred settings (noted in the
   output); add the folder to a tsconfig for authoritative checking.

### context-mode

5. **A naive `ctx_execute` test shows 0% saved — that is expected, not a
   bug.** Running `ctx_execute` with `seq 1 3000` as the code returns the
   full 13.9 KB: ctx_execute returns whatever the script *prints*, and the
   output was under the 16,384 B output cap. The savings come from using it
   as Code Mode (script processes data in the sandbox, prints only a
   summary) and from the hooks on the *regular* tools: Pi's normal bash
   call for the same command returned a short indexed notice instead of
   the output (9.8 KB → 186 B, **98.2% kept out**; `ctx_stats` showed
   **97.8% kept out** for the session). Teach the agent: process in the
   sandbox, print summaries; never dump raw output through ctx_execute.

### pi-mcp-adapter + the vault

6. **Vault tools need an explicit `key_label`, and the model will guess
   one if you don't give it.** Through the adapter the vault tools appear
   as `vault_github_read_file` / `vault_github_list_issues`, take
   `repository` as one `"owner/repo"` string, and require `key_label`.
   Asked without a label, Pi guessed `muse` (from the server description)
   and got `unlock_required` for that label. Always pass the exact label
   of the key you unlocked (grants are per service + label, 2 hours).
   The locked response itself proves the adapter path works end-to-end.
7. **First vault call in a session may need a reconnect** — the adapter
   reported the `vault` server "unconnected (fetch failed)" once and
   reconnected before listing tools. Servers are lazy (start on first
   use, stop after 10 idle minutes), so a first-call hiccup is normal.
8. **Do not enable the adapter's classifier-based semantic search.** It
   can optionally use a classifier model (e.g. Jev). Jev was removed from
   this setup by decision; the default word search is enough.

### Vault admin calls from the Muse VM

9. **Plain script user-agents get HTTP 403 from the vault Worker**
   (Cloudflare bot rules). The same request with a normal browser
   User-Agent succeeds. Any script that calls the vault's `/admin/*` or
   `/unlock` endpoints must send a browser-like `User-Agent` header.
10. **`/unlock` requires a `request_id`** (a fresh UUID per call) in
    addition to `agent_id`, `service`, `key_label` — omitting it returns
    `400 invalid_request`.

## Verified live (2026-11-19, default DeepSeek model)

- `Say OK` → `OK` with all four packages loaded.
- context-mode: JS in `ctx_execute` processed 5,000 records in the sandbox
  and returned only a 40-byte JSON summary; regular bash output indexed
  (98.2% kept out); `ctx_stats` reports the savings.
- pi-hermes-memory: `memory_add` stored a fact in one session; a **fresh**
  session answered correctly from `memory_search` alone.
- pi-lens: a planted TypeScript file produced TS2365 (number + boolean)
  and two TS6133 unused-variable findings at exact columns.
- pi-mcp-adapter + vault + GitHub, end-to-end: with a 2-hour grant open
  for the `github` key labeled `gogibeta github`, Pi called
  `github_read_file` through the adapter and returned the README's first
  heading exactly (`# Muse Pi setup`); `github_list_issues` returned 0
  issues. With the wrong (guessed) label it returned `unlock_required`,
  as designed — the key itself never reaches Pi.
- Web search (Monid free endpoints) still returns results after the
  installs.
