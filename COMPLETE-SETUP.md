# Complete Setup — Pi Sandbox + Gateway + Admin Page + Search + Vault

One-go setup for the whole system, written from a full live run (2026-11-18)
so another Muse account can reproduce it end to end without rediscovering
anything. This document contains **setup and operational detail only — no
secret values, no deployed Worker URL, no account/team/server IDs**. Where a
value is needed it says where *you* get it and where *you* put it; never
paste a secret into chat.

Companion repos:

- `0xSatwik/muse-pi-setup` — the Pi bridge system (README + SETUP-PROMPT there
  are the base guide; this file records what the base guide misses).
- `0xSatwik/cf-d1-vault` — the secrets vault (this repo; its README is the
  vault's own guide).

---

## 0. What the finished system looks like

- **Pi 1.5.2** (the `@earendil-works/pi-coding-agent` CLI) runs on a free
  sandbox VM (Altare in this run; Hoody works the same). Pi is the worker:
  it codes, browses and calls tools.
- **Muse** (the assistant) plans, talks to the user, and drives Pi through
  a small HTTP **gateway** on the box (`pi-gateway.py`, stdlib Python,
  tmux session `pi-gateway`, port 8765) plus a file-queue **fallback bridge**
  (`muse-pi.py` + `watcher.py`) over the host's Files API.
- Muse reaches the gateway over **Tailscale** (primary). A **cloudflared
  quick tunnel** on the box is the public fallback path.
- **Models** are OpenAI-compatible providers in Pi's `models.json`; keys live
  only in `provider-keys.env` on the box. One provider/model is the default.
- **Pi Admin** is a single web page served by the gateway itself for managing
  keys, models, the default model and the search key (details in §7).
- **Search** inside the server is a combined tool (`search.py`): TinyFish via
  Monid **free endpoints only**, merged with DuckDuckGo, deduped by URL (§8).
- **Hallmark** is the default design skill on both sides (§9).
- The **vault** (this repo) holds third-party API keys encrypted in D1; Pi
  holds only a request-only token and calls keys through MCP `service_request`
  / GitHub tools after a time-boxed unlock from the admin (§10).
- **Code Mode** was evaluated and test-run; see §11 before adopting.

Ground rules that apply to every phase:

1. **Secrets never travel through chat.** The user enters keys on secure
   connector pages, in the app Settings, on the box itself, or into the
   named local files (§10.3). The assistant never prints a secret value;
   scripts read files directly.
2. **Browser logins are the user's.** The assistant opens pages; the user
   types passwords/codes and approves devices.
3. **Follow the repo scripts; when a step fails, stop, record the exact
   error and the fix** — several script bugs below were found exactly this
   way. Keep a running lessons file during setup and fold it back into the
   guides at the end.
4. **Verify live, then claim done.** Every phase ends with a check that
   proves the thing works, not just that files exist.

---

## 1. Accounts and connectors you need first

- The sandbox host account (Altare or Hoody), free tier is enough.
- **Tailscale** account (the tailnet is the private road between Muse's VM
  and the sandbox).
- **Cloudflare** account (free) for the vault Worker + D1 — and check whether
  a vault is *already deployed* before creating anything (§10.1).
- A **Monid** account + API key for search (§8).
- At least one model provider key to start (you can add the rest later from
  the Admin page).
- On the Muse side, register connectors so the assistant can act without
  handling raw secrets:
  - Host connector (Files API/console/power). Its registered name must be
    exactly what the bridge script looks up (for Altare:
    `custom.altare-platform`). Prove it before first use with its `self`
    call (token identity + scopes: files, console, view, power).
  - Cloudflare connector (API token) for vault deploys.
  - GitHub connector if repos must be edited.

---

## 2. Phase A — Muse VM side

Run the setup repo's `setup-muse.sh`. Gotchas from the live run:

- The script may lack the execute bit in a fresh clone — run it as
  `bash setup-muse.sh`.
- It installs: the bridge to `~/workspace/altare-pi-setup/pi-bridge/`
  (`pi-api.py`, `muse-pi.py`, `pi-gateway.py`, `watcher.py`), the search
  tool to `~/workspace/search/web.py`, the web-research skill, and the
  session registry `pi-sessions.json`.
- **It prints the generated gateway token in plain text at the end.** Treat
  script output as secret. The token's home is `gateway-token.txt`
  (chmod 600) next to the bridge and `gateway.env` in the sandbox bundle.
- It builds the sandbox bundle under `pi-bridge/sandbox-bundle/`. **A bundle
  whose provider keys are empty still looks ready.** Count the empty-key
  warnings before uploading; a model without a key on the box cannot answer.
- Model keys are only ever entered **on the box** (see §6). A key that only
  exists in a Muse-side connector cannot be reused on the box: connectors
  hand the assistant a surrogate that only the assistant's own egress can
  swap for the real key. The box calls providers directly and needs the
  real key, entered there.

Session discipline (from the setup repo's AGENTS.md, keep it): one Pi
session per topic, reused by default via the `pi-sessions.json` registry;
delegate heavy/long work to Pi; always search through the combined tool.

---

## 3. Phase B — create the sandbox (host web console)

Team API tokens **cannot** create sandboxes (403 by design). Create it in
the host's web console:

1. Add the assistant VM's SSH **public** key to the team first
   (Team → Settings → SSH keys) so the box trusts it.
2. Create the app: Sandboxes → name it `pi`, Ubuntu 24.04, take the whole
   free pool (in this run: 6 GiB RAM / 150% CPU / 10 GiB disk). Region may
   come pre-selected; any region works. SSH-keys only, no password. No
   payment step on the free plan.
3. **Undocumented gate: the first Start demands linking a Discord account**
   (anti-abuse; grants some credits). Only the user can do this. After
   linking, Start may sit in a queue ("waiting for room on the node") for a
   bit — that is normal, not a failure.
4. Record the **team ID** and **server UUID** from the console — the Files
   API calls need both (env `ALTARE_TEAM` / `ALTARE_SERVER` for the bridge).

Email-verification note: the host's "Getting started" checklist may mark
"Verify your email" as done even when the user never received a
confirmation mail. It blocked nothing in this run; do not treat the
checklist as proof either way.

---

## 4. Phase C — upload the bundle and run the sandbox setup

1. Upload every bundle file to `/root/work/setup/` on the box with the
   bridge (`muse-pi.py put <local> setup/<name>`). The bridge reads/writes
   only under `/root/work/`.
2. In the box's web console terminal run `bash /root/work/setup/setup-sandbox.sh`.

Bugs and behaviours found in this run — expect them:

- **The Pi install line is wrong in the script.** `npm install -g pi@1.5.2`
  can never work: the unscoped `pi` package is a different project (no
  1.5.2 exists; npm answers ETARGET). The real package is
  **`@earendil-works/pi-coding-agent@1.5.2`** (bin name `pi`). Patch the
  line in both setup scripts (`setup-sandbox.sh`, `setup-hoody.sh`) before
  running; keep the patch in the repo.
- **tzdata may ask an interactive timezone question** mid-install (the
  script doesn't set `DEBIAN_FRONTEND=noninteractive`). Answer it in the
  console (continent → city) and let the script continue.
- The script installs Node 22, Pi, Tailscale, starts `tailscaled` in tmux,
  then **waits at a Tailscale login URL** for the sandbox device (default
  name `pi-altare`). Give the URL to the user verbatim; they approve it.
- Muse's own VM also needs `tailscale up` once; its approval link may
  only surface via `tailscale status` output, not the up command.
- **The first request to a new tailnet address needs its own user
  approval** in the assistant runtime. A setup script health check that
  times out at this point is not a failure — retry the health call right
  after approval and it answers instantly.
- The Altare web console **lags about one command behind** — an apparently
  empty result may just not have rendered. Wait ~30 s / press Enter before
  concluding a command failed.
- Direct SSH from the assistant VM to the box is blocked by egress policy.
  Drive the box through the web console, the Files API and the tailnet
  only.
- The script also starts the cloudflared quick tunnel (tmux `pi-tunnel`);
  its public URL is in `/root/pi-bridge/tunnel.log` on the box and changes
  whenever the tunnel restarts.

Expected end state: tmux sessions `pi-gateway`, `pi-bridge` (watcher),
`pi-tunnel`, `tailscaled`; gateway health `{"ok": true}` from the box.

---

## 5. Phase D — first verification (do not skip)

1. Wire the tailnet address into the bridge
   (`setup-muse.sh --tailnet <sandbox-tailnet-ip>`), then
   `pi-api.py health` → `{"ok": true, "sessions_running": 0}`.
2. `pi-api.py models` lists every provider from `models.json`.
3. **"Say OK" test on BOTH paths**, using a model whose key is on the box:
   - gateway: `pi-api.py prompt "Say OK" --model <provider>/<model>`
   - fallback: `muse-pi.py ask --model <provider>/<model> --prompt "Say OK"`
   Both must answer OK. The fallback watcher requires `--model` explicitly;
   a watcher job without a model falls back to a hard-coded provider
   default in `watcher.py` that may have no key yet.

---

## 6. Phase E — keys and models, done properly

Layout on the box (all chmod 600, values never in `models.json`):

- `/root/pi-bridge/provider-keys.env` — `ENV_NAME=value` lines, one per
  provider key.
- `/root/.pi/agent/models.json` — providers with `baseUrl`, `api`
  (`openai-completions` or `anthropic-messages`) and `apiKey: "$ENV_NAME"`
  placeholders only; each model has `id`, `contextWindow`, `maxTokens`,
  optionally `name`, `reasoning`, `input` (`["text"]` or
  `["text","image"]`), `cost`.
- `/root/.pi/agent/settings.json` — `defaultProvider` + `defaultModel`.

Rules learned live:

- **Long-running processes do not see keys added later.** After any key or
  model change, restart the gateway (`pi-api.py restart`, or the Admin
  page button) — the restart respawns the gateway from the file on disk,
  which is also how gateway code updates go live.
- Some providers **reject non-coding clients** (HTTP 403
  `client_not_allowed` on chat endpoints while `/v1/models` still answers).
  Test such providers only *through Pi itself*, never with a bare HTTP
  client, and do not conclude the key is bad from a 403 of this shape. A
  401 everywhere, on every route, is a different signal: a dead key — only
  the user can re-enter/regenerate it, on the connector page, never in
  chat.
- Setting the default model = edit `settings.json` (`defaultProvider`,
  `defaultModel`), restart the gateway, then prove it with a prompt that
  names **no** model.
- The bridge ships a helper pattern worth keeping: a `setkey`/`add-model`
  CLI on the gateway client (key via stdin, stored 600; models.json keeps
  only the `$ENV` placeholder) plus a restart + Say OK test in one go.

---

## 7. Phase F — the Pi Admin page (gateway feature addition)

The stock gateway is API-only; driving it means console rituals for every
key and model. This setup adds a small admin UI **inside `pi-gateway.py`
itself** (same process, same auth), served at `GET /admin`:

- The page shell is public HTML; **every action** calls the API with the
  gateway token as a Bearer header. The page never stores keys: secret
  fields are write-only (the API returns names + set/not-set booleans,
  never values — there is no read-back endpoint by design).
- **Opening password:** `POST /admin-login` exchanges a human password for
  the gateway token. Only the password's **SHA-256 hash** is stored, as
  `PI_ADMIN_PASS_SHA256` in the box's `gateway.env`. The raw gateway token
  also works in the same field. Whoever holds either can also send prompts
  to Pi, and Pi runs as root in the sandbox — treat the password like a
  root password.
- **Login throttling (added after review):** 5 consecutive failed logins →
  10-minute lockout (HTTP 429); a success resets the counter.
- Endpoints added by this setup: `GET /admin`, `POST /admin-login`,
  `GET /secrets`, `DELETE /secrets/{env_name}`, `GET|POST /settings`
  (default provider/model), `GET|POST /monid` (§8),
  `POST /provider-models` (below). Stock gateway endpoints used by the
  page: `GET|POST|PATCH|DELETE /models`, `POST /secrets`,
  `POST /restart`, `POST /prompt`, `GET /health`.
- **Access paths:** tailnet URL (stable, private — the device must be
  running Tailscale; "page won't open" almost always means it isn't) and
  the cloudflared quick-tunnel URL (public; changes on every tunnel
  restart — find the current one in `/root/pi-bridge/tunnel.log`). The
  quick tunnel occasionally serves a Cloudflare bot-check ("Your request
  was blocked") to automated clients; a refresh in a normal browser
  clears it.
- Deploy pattern for gateway changes: edit the local copies (bridge dir +
  setup-repo bundle — keep them identical), upload via the bridge, copy
  into `/root/pi-bridge/` in the console (keep a `.bak`), `py_compile`,
  restart via the client, re-run the endpoint tests.

### 7.1 Proper model adding (the important part)

Adding a provider by hand-editing JSON is error-prone; the admin flow is:

1. `POST /provider-models {base_url, api_key? | env_name?}` — the **box**
   fetches the provider's live `GET {baseUrl}/models` (key from the body
   or from the stored env var; browser-like User-Agent; 25 s timeout) and
   normalizes each model to `{id, context, output, name}`, reading
   `context_length` / `contextWindow` / `max_context_tokens` and
   `max_output_tokens` / `maxTokens` / `max_completion_tokens`, including
   nested OpenRouter-style `top_provider` values.
2. The page shows a **searchable tick-list** of the provider's real
   models. Per ticked model: editable **context** and **output** fields
   (pre-filled from the provider — the advertised context can exceed the
   real hard cap; correct it when you know better, §7.2), an **R** toggle
   (`reasoning: true`) and a **V** toggle (`input: ["text","image"]`).
3. Adding writes the provider (if new) with `apiKey: "$ENV_NAME"` and the
   model with all chosen fields. **Bug fixed here:** an env-name-only add
   (no key in the same request) originally left `apiKey` unwired; it now
   always sets `"$" + env_name`.
4. Existing models render with a `ctx 198k · out 65k` summary plus
   reasoning/vision tags, and have **Edit** (contextWindow, maxTokens,
   name, reasoning, vision → PATCH), **Make default**, **Test** and
   **Remove**.
5. A manual-ID add (type the model id yourself, same fields) covers
   providers whose `/models` list is incomplete.

Page bug fixed during testing: the Test button crashed with
`txt.slice is not a function` — the gateway returns `last_assistant_text`
as an object (`{"text": "OK"}`), not a string; the page now extracts
`.text`. Lesson: match the page to the gateway's real response shapes,
and test every button against the live gateway, not a mock.

### 7.2 Per-model tuning example (verified numbers beat advertised ones)

For the 100milionseek DeepSeek model, a full benchmark audit (separate
guide: max-settings recipe with `reasoning_effort: "max"`, `max_tokens`
65536, streaming mandatory to avoid gateway 524s) produced the values
actually set in Pi: `contextWindow` **197488** (the provider advertises
198000, but 197,488 is the enforced hard cap — Pi must not plan prompts
past it), `maxTokens` **65536**, `reasoning: true`, `input`
`["text","image"]` (vision verified), plus
`"samplingParams": {"reasoning_effort": "max"}` on the model entry —
OpenAI-compatible model entries accept free-form `samplingParams`
defaults that Pi merges into every request, which pins the guide's
effort setting regardless of session thinking level (verified live: a
default-model prompt answers normally with this profile). Background:
providers also take a `compat` block (`supportsReasoningEffort`,
`thinkingFormat: "openai"` sends `reasoning_effort`); Pi thinking levels
are `off, minimal, low, medium, high, xhigh, max`, mapped per model via
`thinkingLevelMap`. When in doubt read the installed Pi's own
`docs/models-configuration.md` and `docs/models.md` on the box — they
are authoritative for the exact version.

---

## 8. Phase G — combined search inside the server (Monid + DuckDuckGo)

The agent's research tool merges **TinyFish via Monid (free endpoints
only)** with **DuckDuckGo**, dedupes by URL and uses all unique results;
a second mode adds an X/Twitter leg via FxEmbed. Files and rules:

- The tool is the setup repo's `search/web.py`. On Muse's side it lives
  at `~/workspace/search/web.py` (plus the web-research skill). **On the
  box it must be `/root/pi-bridge/search.py` — the sandbox setup script
  never installs it there** (the README says to copy it; the script
  doesn't). Install it manually and verify.
- Monid key file: `~/.config/monid/credentials.yaml` on **both** sides
  (chmod 600). The box needs the **real** key (entered by the user — the
  Admin page's Monid card writes this file). On Muse's side the file can
  hold the connector **surrogate** instead: the assistant's egress swaps
  it for the real key on calls to Monid's API host, so the raw key never
  sits in a file there. Surrogates do **not** work from the box or from
  URLs — anywhere a credential rides inside a URL path, splice the raw
  value, never the percent-encoded surrogate.
- **Free endpoints only, as a standing rule:** Monid's TinyFish
  `/free/search` and `/free/fetch` (live-verified $0). Never the paid
  `/search` / `/fetch`. `/free/search` returns browser-rendered snippets;
  pipe promising URLs into `/free/fetch` for full text.
- **DuckDuckGo returns `[]` from datacenter egress** (verified from both
  the sandbox and the assistant VM) — the Monid leg is load-bearing, not
  decorative. If search returns nothing, check the Monid key first
  (a placeholder or missing key shows up as a 401 from that leg).
- **Bug fixed:** the X leg (FxEmbed `/ai/2/ask`) regularly takes > 60 s;
  its timeout wasn't retried and crashed the whole `research` command.
  Fix: wrap the X call in try/except, warn on stderr, continue with the
  other legs (`x_pack_markdown: null`). Slowness is not an outage — a bare
  request returns 200 just after the client timeout.
- Verify on the box: `python3 /root/pi-bridge/search.py search
  "pi coding agent"` must return real results with no 401.

Cloudflare-blocked sites ladder (from the setup repo): TinyFish fetch →
assistant browser task → vault Worker fetch → Pi sandbox egress (the
box's IP is often not blocked where the assistant's is).

---

## 9. Phase H — Hallmark design skill (default for design work)

`nutlope/hallmark` is the standing default design skill. **The standard
install command fails in this environment** — `npx skills add
nutlope/hallmark -g` answers `[SKILLS_NO_VALID_SKILLS]` (plus a submodule
warning) because the skill lives at `skills/hallmark/` inside its repo,
not at the root. Manual route (verified):

1. Clone the repo; the skill is the `skills/hallmark/` folder
   (SKILL.md at its root).
2. Muse side: copy it to `~/workspace/custom-skills/hallmark` and to
   `~/.agents/skills/hallmark`.
3. Box side: the Files-API bridge is **text-only** — tar the skill,
   base64 it, upload the `.b64` as text, decode + untar in the console
   into `/root/.pi/agent/skills/hallmark/`. Verify `SKILL.md` exists
   there before claiming it's installed.

---

## 10. Phase I — the vault (this repo)

Architecture in one paragraph: keys are stored **AES-256-GCM-encrypted**
(AAD-bound) in D1. Pi holds only a **request-only bearer token** and calls
MCP tools — `github_read_file`, `github_list_issues`,
`github_create_issue` (only when `ENABLE_GITHUB_WRITES=true`) and generic
`service_request`. Nothing can read a key back: when a call is allowed,
the **Worker decrypts server-side, calls the third-party API itself, and
returns only the response**. Calls need a **grant**: the admin unlocks one
exact service + one exact key label for **2 hours (7200 s)**; anything
else returns `{"error":"unlock_required", ...}`. Admin routes
(`/admin/agents`, `/admin/keys`, `/unlock`, `/revoke`) are master-only.
The manual page has two passwords: human (key management) and master
(everything).

### 10.1 Before deploying anything: check what already exists

**The expensive lesson of this run:** a vault may already be deployed
(the user had built one in a *different* Cloudflare account than the one
connected to the assistant). The assistant, not checking, created a
duplicate empty D1 in the connected account before learning this. So:
ask, list the connected account's Workers/D1s, probe any candidate
deployment (`GET /` manual page, `/whoami` 401 without a bearer) — and
only create what is actually missing. Deleting a duplicate needs the
user's explicit word.

### 10.2 Fresh deploy (only if nothing exists)

Follow this repo's README: create the D1 database, note its id into
`wrangler.toml` (the shipped file contains the author's values — replace
them), set `PUBLIC_ORIGIN` to **your** deployment origin, apply both
migrations (`0001_init`, `0002_multi_service`), generate the secrets with
the repo's script (`scripts/gen-secrets.mjs` → master secret, human
password, DEK), set them as Worker secrets, deploy, and sanity-check with
the README's curl chain (root page 200, `/whoami` 401 → master role,
human login, add-key → 201, duplicate → 409, wrong-service unlock → 400,
locked MCP call → `unlock_required`, granted call → 200). Practical
notes from the live run: `npm install`, `npm run check` (tsc) and
`npm test` all pass clean on a fresh clone; if the assistant's Cloudflare
access is via a connector surrogate, wrangler needs it injected as
`CLOUDFLARE_API_TOKEN` by a small wrapper; MCP clients must send
`Accept: application/json, text/event-stream` or the Worker answers 406;
when testing the manual page's redirects with curl, use
`redirect: "manual"` semantics — a followed redirect hides the real
status.

### 10.3 Secret file layout (names and places — values never in chat)

On the assistant's VM, in the Pi setup workspace (`altare-pi-setup/`):

- `vault-master-secret.txt` — the master secret; the one value that gives
  full vault authority (chmod 600).
- `vault-dek-backup.txt` — DEK backup, disaster recovery only (chmod 600).
- `pi-request-token.txt` — **Pi's** request-only token (chmod 600). Not
  the assistant's credential; it belongs on the box (next step).
- `cf-vault/` — a copy of this repo's code for reference/redeploy.

The user pastes values into these files manually. Assistant scripts read
the files directly; values are never printed, echoed or copied into chat,
prompts or logs. Registration of the agent (if not already done) uses the
master: generate the agent token, store only its SHA-256 via
`POST /admin/agents {"id":"pi","token_hash":...,"request_id":<uuid>}`,
and keep the raw token solely in `pi-request-token.txt`.

### 10.4 Wire Pi to the vault

Create `/root/.pi/agent/mcp.json` on the box (chmod 600), following this
repo's `pi/mcp.json.example` shape:

```json
{
  "mcpServers": {
    "vault": {
      "url": "https://<your-vault-origin>/mcp",
      "headers": { "Authorization": "Bearer <PI_REQUEST_TOKEN>" },
      "exposure": "codemode",
      "description": "Scoped GitHub tools; ask Muse to unlock when a grant expires"
    }
  }
}
```

Build the file with a script that reads the token from
`pi-request-token.txt` (never type it), upload via the bridge, install
from the console. Then verify the whole chain with raw MCP calls using
Pi's token: `initialize` → 200 with serverInfo `cf-d1-vault`;
`tools/list` → the GitHub tools + `service_request`; a `github_read_file`
call with no grant open → **`unlock_required`**. That locked answer *is*
the success state. Separately verify the master file works:
`GET /whoami` → `{"role":"master"}` and `GET /admin/keys` lists the
stored keys (metadata only).

### 10.5 Day-to-day vault operations

- Pi hits `unlock_required` → the assistant (or user) unlocks the exact
  service + label with the master (`POST /unlock`), Pi retries; grants
  expire after 2 h; `/revoke` closes one early.
- Adding a key is a master/human action through the manual page or
  `/admin/keys` — never through Pi.
- If the master secret is ever lost, the DEK backup + database are the
  recovery path; if both are lost, stored keys are unrecoverable by
  design.

---

## 11. Code Mode — evaluated, not adopted (yet)

Cloudflare's Code Mode (from `cloudflare/agents`) collapses many MCP
tools into **one `code` tool**: the model writes a single async
TypeScript function calling typed `codemode.*` methods; it runs in an
isolated Worker sandbox and only the final value returns to context.
Verified live locally in this run (nothing deployed): the `codemode-mcp`
example under `wrangler dev` exposed 3 raw tools on `/mcp` and exactly
one `code` tool on `/codemode`; a chained snippet (add → list → greet)
executed in one call with **unwrapped** return values; `fetch()` inside
the sandbox is blocked. Gotchas: the monorepo needs `pnpm` (install it
globally first) and filtered install/build; the chat example needs a real
Cloudflare login even locally (its Workers AI binding is remote).

Fit notes: the simple `createCodeTool` path **silently drops
approval-required tools** — wallet/secret-class tools must never go
through it; the newer Durable-Object Runtime adds approval pause/replay,
rollback and audit. The vault's Pi config already declares
`"exposure": "codemode"`. The runtime is Workers technology — it does not
install into the self-hosted Node/Pi setup; only the pattern is portable
(the Executor interface is small). Treat adoption as its own project:
test Pi's MCP client against a codemode endpoint first.

---

## 12. Security posture of the whole setup (honest summary)

Protective: gateway token on every action; admin password stored as hash
only, with login lockout; keys write-only through every API; 600-perm key
files; `models.json` holds placeholders only; vault keys encrypted at
rest, grant-scoped, never present on the box; sandbox SSH is keys-only;
Muse-side Monid file holds a surrogate, not the raw key.

Weak points, stated plainly: the public quick-tunnel makes the admin
login page reachable by anyone who finds the (unguessable, rotating)
URL — the password is the only gate there; the tailnet path is the
private alternative and can be made the *only* path by killing the
tunnel. Whoever holds the gateway token or admin password can prompt Pi,
and Pi runs as root in its sandbox — inside that blast radius sit Pi's
own model-provider keys (`provider-keys.env`), which any program calling
those APIs must hold by design. The vault's keys are deliberately outside
that radius (§10). The master-secret file on the assistant's VM confers
full vault authority; it is 600 and never printed, and that is the
correct place for it — but know that it is there.

---

## 13. One-go acceptance checklist

- [ ] `pi-api.py health` → ok; `pi-api.py models` lists all providers.
- [ ] "Say OK" passes on the gateway path **and** the file-queue fallback.
- [ ] A no-model prompt answers via the configured default model.
- [ ] Admin page: login (wrong password → 401; 5 wrong → 429), secrets
      list shows names/booleans only, test prompt returns its text.
- [ ] Provider `/provider-models` returns real models with limits;
      add → PATCH → delete round-trip on a scratch provider is clean.
- [ ] On-box search returns real TinyFish results, no 401; research mode
      survives a slow X leg.
- [ ] Hallmark `SKILL.md` present on both sides.
- [ ] Vault: master `/whoami` → master; Pi-token MCP `tools/list` OK;
      locked call → `unlock_required`; one granted call → real response.
- [ ] No secret value appears in any chat, prompt, log or repo file.

## 14. Troubleshooting (every failure actually hit, symptom → fix)

| Symptom | Cause → fix |
|---|---|
| `npm ETARGET … pi@1.5.2` | Unscoped `pi` is a different package → install `@earendil-works/pi-coding-agent@1.5.2` (§4). |
| Sandbox Start blocked | Discord account must be linked first (§3). |
| Setup hangs at a prompt | tzdata timezone question → answer in console (§4). |
| First tailnet health check times out | New tailnet address needs its own approval → retry (§4). |
| Console output looks empty | Display lags one command → wait/Enter (§4). |
| Model answers on one path only | Key missing on the box, or gateway not restarted after a key change (§6). |
| Provider 403 `client_not_allowed` | Provider allows coding clients only → test through Pi, not curl (§6). |
| Provider 401 on everything | Dead key → user re-enters it on the connector page (§6). |
| Admin page won't open | Device not on Tailscale (tailnet URL), or tunnel URL rotated → check `tunnel.log` (§7). |
| "Your request was blocked" on tunnel URL | Cloudflare bot-check on automated clients → refresh in a real browser (§7). |
| Test button: `txt.slice is not a function` | Gateway returns text as an object → extract `.text` (§7.1). |
| Search returns nothing / 401 leg | Monid key missing/placeholder on that side (§8). |
| `research` crashes on X leg | FxEmbed > 60 s timeout uncaught → try/except fix (§8). |
| `npx skills add` finds no skills | Skill not at repo root → manual copy route (§9). |
| Binary won't upload via bridge | Bridge is text-only → base64 + decode on the box (§9). |
| Vault MCP answers 406 | Missing `Accept: application/json, text/event-stream` (§10.2). |
| Duplicate vault infra appears | Someone deployed already, maybe in another account → check first (§10.1). |

---

*Written 2026-11-18 from a complete live setup. Keep it current: when a
setup step changes or a new failure is found, update this file in the
same change — a stale guide is worse than none.*
