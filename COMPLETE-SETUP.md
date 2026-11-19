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
  named tunnel** on the box is the permanent public path
  (`https://<name>.<domain>/admin`); a quick tunnel is only a
  fallback until the named one is verified loading.
- **Models** are OpenAI-compatible providers in Pi's `models.json`; keys live
  only in `provider-keys.env` on the box **and** as exports in
  `/root/.profile` + `/root/.bashrc` (the gateway reads the first, the
  watcher reads the second — §6). One provider/model is the default.
- **Pi Admin** is a single web page served by the gateway itself for managing
  keys, models, the default model and the search key (details in §7).
- **Search** inside the server is a combined tool (`search.py`): TinyFish via
  Monid **free endpoints only**, run together on every query with the
  cf-search Worker (Bing), merged and deduped by URL — never one engine
  with the other as a fallback (§8). DuckDuckGo was removed 2026-11-19:
  it returns nothing from datacenter / Cloudflare egress.
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

**The API key NEVER creates anything. It only reads files on a
sandbox that already exists. Every creation step happens in the
browser.** Team API tokens **cannot** create sandboxes (403 by
design). Create it in the host's web console:

1. Add the assistant VM's SSH **public** key to the team first
   (Team → Settings → SSH keys) so the box trusts it.
2. Create the app: Sandboxes → name it `pi`, Ubuntu 24.04, take the whole
   free pool (in this run: 6 GiB RAM / 150% CPU / 10 GiB disk). Region may
   come pre-selected; any region works. SSH-keys only, no password. No
   payment step on the free plan.
3. **Discord gate — check first, do not assume it blocks.** Look at
   Account → Discord: if it already says "Linked", there is no gate
   and Start works. Only if it is unlinked must the user link it
   (anti-abuse; grants some credits) — only the user can do this.
   After linking, Start may sit in a queue ("waiting for room on the
   node") for a bit — that is normal, not a failure. **Free-tier
   Start takes ~25–30 minutes end to end** (node queue ~15 min,
   then ~10 min pulling the container image, then "Sandbox ready").
   Tell the user this up front so the wait does not read as a
   failure. The Apps page can briefly show "Your server pi is
   unavailable right now... couldn't connect to the node" while
   starting; it clears on its own.
4. Record the **team ID** and **server UUID** from the console — the Files
   API calls need both (env `ALTARE_TEAM` / `ALTARE_SERVER` for the bridge).
   Ground truth for existence is the servers LIST endpoint
   (`GET /tenants/<team>/servers`) — it returns `items: []` before
   creation and the full server record after. Do not use the
   single-server GET endpoint (`GET /tenants/<team>/servers/<id>`);
   it returns 403 for this token.

Email-verification note: the host's "Getting started" checklist may mark
"Verify your email" as done even when the user never received a
confirmation mail. It blocked nothing in this run; do not treat the
checklist as proof either way.

---

## 4. Phase C — upload the bundle and run the sandbox setup

1. Upload every bundle file to `/root/work/setup/` on the box with the
   bridge (`muse-pi.py put <local> setup/<name>`). The bridge reads/writes
   only under `/root/work/`. **Put paths are relative to `/root/work/`:**
   `put <local> setup/<name>` lands at `/root/work/setup/<name>`, but
   `put <local> /root/work/setup/<name>` lands at
   `/root/work/root/work/setup/<name>` — the bridge prepends the root.
   Never pass an absolute `/root/work/...` path; `ls` the box to confirm
   where a file landed.
2. In the box's web console terminal run `bash /root/work/setup/setup-sandbox.sh`.

Bugs and behaviours found in this run — expect them:

- **The Pi install line is wrong in the script.** `npm install -g pi@1.5.2`
  can never work: the unscoped `pi` package is a different project (no
  1.5.2 exists; npm answers ETARGET). The real package is
  **`@earendil-works/pi-coding-agent@1.5.2`** (bin name `pi`). Patch the
  line in both setup scripts (`setup-sandbox.sh`, `setup-hoody.sh`) before
  running; keep the patch in the repo. Verify with grep before running —
  do not assume the patch is in.
- **A transient apt failure is not a broken script.** The first run can
  fail at the Tailscale install (apt could not fetch a package,
  "Connection failed") and succeed end to end on a plain re-run of the
  exact same script. Re-run once before diagnosing further.
- **The Files API 502s while the server starts.** While Start is queued
  or the box is still coming up, Files API calls answer HTTP 502 Bad
  Gateway — that is "server not up yet", not a broken token. Poll every
  ~2 minutes; give up only after ~60 minutes of continuous failure.
  (The same 502 appears later when reading a file that does not exist
  yet — see §14, `muse-pi.py get`.)
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
- Direct SSH from the assistant VM to the box is **blocked by default**
  by the VM's egress policy — but it works once the user enables the
  egress settings (verified live: `ssh -i ~/.ssh/id_ed25519 -p <port>
  root@<node>.altare.global`, host and port from the console's server
  details). Try SSH; if it is blocked, drive the box through the web
  console, the Files API and the tailnet only.
- **SSH host keys are lost on VM replacement.** SSH reads known_hosts
  from the PASSWD home (`/root/.ssh/` for uid 0), not from `$HOME` —
  and `/root` is ephemeral across VM replacements, so a replacement
  wipes `/root/.ssh/known_hosts` and SSH fails with "Host key
  verification failed" even though the identity key and the box are
  fine. Fix: re-add the keyscan key to `/root/.ssh/known_hosts` and
  keep a persistent copy in `~/.ssh/known_hosts`. Verify the box
  afterwards by checking for your own files (hostname is the container
  id, `/root/pi-bridge/` holds the gateway files).
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
   - gateway: `pi-api.py prompt "Say OK" --model <provider>/<model>` —
     the prompt call is ASYNC: it returns
     `{"disposition": "started", "session_id": ...}`, NOT the reply.
     Read the reply back with `pi-api.py status <id>` — the OK is in
     `last_assistant_text` (`{"text": "OK"}`), or use `events <id>`.
     A prompt that returns "started" with no text is not a failure
     and not an answer — it only means the turn was accepted.
   - fallback: `muse-pi.py ask --model <provider>/<model> --prompt "Say OK"`
     → `OK`
   Both must answer OK. The fallback watcher requires `--model` explicitly;
   a watcher job without a model falls back to a hard-coded provider
   default in `watcher.py` that may have no key yet. **If the gateway
   path times out right after a key was added, the gateway has not
   picked the key up yet** — restart the gateway after ANY key change
   (§6) and re-test; the gateway is not down. And never call the
   gateway URL with plain urllib: tailnet 100.x needs the VM's :3130
   tunnel proxy (`pi-api.py` handles it); a direct call comes back
   empty / RemoteDisconnected and looks exactly like a dead gateway
   when it is running fine.

---

## 6. Phase E — keys and models, done properly

Layout on the box (all chmod 600, values never in `models.json`):

- `/root/pi-bridge/provider-keys.env` — `ENV_NAME=value` lines, one per
  provider key. **The gateway reads this file at start.**
- `/root/.profile` **and** `/root/.bashrc` — `export ENV_NAME='value'`
  lines, one per provider key. **The file-queue watcher reads these**
  (`load_profile_env()`), and so do interactive Pi shells.
- `/root/.pi/agent/models.json` — providers with `baseUrl`, `api`
  (`openai-completions` or `anthropic-messages`) and `apiKey: "$ENV_NAME"`
  placeholders only; each model has `id`, `contextWindow`, `maxTokens`,
  optionally `name`, `reasoning`, `input` (`["text"]` or
  `["text","image"]`), `cost`.
- `/root/.pi/agent/settings.json` — `defaultProvider` + `defaultModel`.

**The two key stores must stay in sync — this is the trap.** Model keys
live in TWO places and each path reads only one: the gateway reads
`provider-keys.env`, the watcher reads `/root/.profile`. The Pi Admin
page / gateway writes `provider-keys.env` ONLY. A key added in the Admin
page therefore works on the gateway path while the fallback path fails
with "No API key found for <provider>". After ANY key change: (1) sync
the exports into `/root/.profile` + `/root/.bashrc` on the box (a script
that reads `provider-keys.env` and appends `export NAME='...'` lines,
never printing a value), (2) restart the gateway (`pi-api.py restart`,
or the Admin page button), (3) restart the watcher (`tmux kill-session
-t pi-bridge`, then recreate it running `watcher.py`). Durable repo
fix, not yet done: the gateway's `/secrets` handler should write both
stores, or the watcher should also load `provider-keys.env`.

Rules learned live:

- **Long-running processes do not see keys added later.** After any key or
  model change, restart the gateway (`pi-api.py restart`, or the Admin
  page button) — the restart respawns the gateway from the file on disk,
  which is also how gateway code updates go live. Restart the watcher
  too (above) — it also loads keys only at start.
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
  **Never hand-transcribe a generated secret from tool output.** A
  generated password mis-copied by one character fails for the user and
  for your own tests alike — and the hash check only catches it after
  the wrong value has already been handed over. Verify a generated
  secret by hash against `PI_ADMIN_PASS_SHA256` BEFORE giving it to
  anyone. The reliable way to set one is for the assistant to author
  the value itself (stdin, never output) so no transcription is needed;
  a word passphrase (e.g. `mango-river-tiger-harbor-42`) is the
  human-copyable form. Verify the login over both the tailnet and the
  tunnel URL before handing the password over.
- **Login throttling (added after review):** 5 consecutive failed logins →
  10-minute lockout (HTTP 429); a success resets the counter. A gateway
  restart clears the in-memory counter.
- **Scripted calls through the tunnel need a browser User-Agent.**
  A POST to the tunnel URL from Python urllib's default User-Agent
  returns HTTP 403 error code 1010 (Cloudflare "bad browser"). The
  gateway itself never returns 403 on that route (401 wrong password,
  429 locked out). The Admin page's own fetch in a real browser is fine.
- **Tunnel POSTs are flaky under node load — retry, do not re-diagnose.**
  A tunnel login POST can time out at 30 s, close the connection without
  a response, and then succeed in ~1 s with nothing changed on the box.
  A single failed tunnel POST proves nothing; retry twice before
  concluding the password or the tunnel is broken. Count the retries:
  5 failed logins lock the page for 10 minutes, so space them out.
- **A lagging console pane is not the tunnel state.** A `tmux
  capture-pane` on `pi-tunnel` can show the log stuck at "precheck
  complete" with no "Registered tunnel connection" line while the
  tunnel is in fact registered. Trust the Cloudflare API (tunnel
  listed healthy with live connections) and a direct SSH
  `capture-pane` over a lagging console pane.
- **Named tunnel, not quick tunnel, for the permanent URL.** The
  quick tunnel's URL rotates on every restart; the named tunnel's
  (`https://<name>.<domain>/admin`) never changes. Create the named
  tunnel only after the gateway is running (its credentials go
  straight onto the box in the same step) — exception: if the domain
  already exists as a zone, creating the tunnel object and the
  proxied CNAME early is safe; they wait inactive. Before creating
  anything, list `tunnels` and `zones` on the account first and
  create only what is missing — never touch a tunnel you did not
  create. The DNS CNAME (`<name>.<zone>` →
  `<tunnel-id>.cfargotunnel.com`) MUST be proxied (orange cloud);
  DNS-only gives `ERR_CONNECTION_RESET`, and DNS needs ~60 s to
  propagate. Save the tunnel credentials to a chmod-600 file and
  place them at `/root/.cloudflared/` in the same step that starts
  cloudflared. **Never restart cloudflared inside its tmux
  session:** a tmux session closes when its main process exits, and
  cloudflared IS the main process — always `tmux kill-session -t
  pi-tunnel`, then recreate the session running cloudflared. The
  CNAME only works inside the SAME Cloudflare account as the tunnel.
- Endpoints added by this setup: `GET /admin`, `POST /admin-login`,
  `GET /secrets`, `DELETE /secrets/{env_name}`, `GET|POST /settings`
  (default provider/model), `GET|POST /monid` (§8),
  `POST /provider-models` (below). Stock gateway endpoints used by the
  page: `GET|POST|PATCH|DELETE /models`, `POST /secrets`,
  `POST /restart`, `POST /prompt`, `GET /health`.
- **Access paths:** tailnet URL (stable, private — the device must be
  running Tailscale; "page won't open" almost always means it isn't) and
  the cloudflared tunnel URL (named tunnel: permanent; quick tunnel:
  public, changes on every tunnel restart — find the current one in
  `/root/pi-bridge/tunnel.log`). The quick tunnel occasionally serves a Cloudflare bot-check ("Your request
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

## 8. Phase G — combined search inside the server (Monid + Bing)

The agent's research tool runs **TinyFish via Monid (free endpoints
only) AND the cf-search Worker (Bing) together on every query**,
merges the URLs and dedupes them. Neither engine is a fallback for
the other: if one fails, the other's results are still returned and
the failure is reported on stderr (and in `--meta`). A third leg
adds X/Twitter via FxEmbed. **DuckDuckGo was removed 2026-11-19**
(it returns `[]` from datacenter egress and a 202 bot-challenge from
Cloudflare's network) — any guide text still naming it as a search
leg is stale. Files and rules:

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
- **The Monid leg is load-bearing, not decorative.** Without a Monid
  key, in-server search returns nothing, silently. If search returns
  nothing, check the Monid key first (a placeholder or missing key shows
  up as a 401 from that leg). The Monid credentials file format matters:
  `web.py` reads it with the regex `key:\s*"([^"]+)"` — the file must
  contain `key: "<value>"` (with quotes). A file that says
  `api_key: <value>` is silently ignored and search returns nothing.
- **The cf-search Worker (Bing)** — `https://cf-search.akamithun-search.workers.dev/search`,
  plain text, one line per result, no key. Full filter set on
  `search-cf` (and on `search`/`research` via `--widen` variants):
  `vertical` web|images|videos|news, `count` (web/news max 10),
  `setlang`/`lang`, `cc`/`region`/`country`, `mkt`, `safesearch`
  off|moderate|strict, `time` day|week|month|year, `sort` date|relevance
  (news), `size`/`color`/`imgtype`/`face`/`license` (images),
  `duration`/`resolution` (videos). Country-wise filtering genuinely
  changes results (setlang+cc); use different filters — not another
  page — for more web/news results.
- **Pagination does NOT work for Bing web/news — never request page > 1
  for those verticals.** Bing ignores the `first` offset in every form
  tested; page=2 returns the IDENTICAL results as page=1. The tool
  refuses page>1 for web/news rather than wasting the call. For more
  web/news results use `--widen` (extra calls with different
  country/language/time filter sets, merged + deduped) or change the
  filters. Page>1 is only sent for images/videos. Google News (503)
  and DuckDuckGo (202 bot-challenge) do NOT work from Cloudflare's
  network. Bing only.
- **An `Error: upstream_failed` line in a 200 response means NO RESULTS,
  not a crash.** Parse it out, retry once after ~3 s, then return an
  empty result list for that engine — the other engine's results still
  stand.
- **Bug fixed:** the X leg (FxEmbed `/ai/2/ask`) regularly takes > 60 s;
  its timeout wasn't retried and crashed the whole `research` command.
  Fix: wrap the X call in try/except, warn on stderr, continue with the
  other legs (`x_pack_markdown: null`). Slowness is not an outage — a bare
  request returns 200 just after the client timeout.
- Verify on the box: `python3 /root/pi-bridge/search.py search
  "pi coding agent"` must return real results with no 401, and
  `--meta` must show both engines contributing (tinyfish count and
  cf-search count both > 0). `search-cf "q" --vertical news --sort date
  --time day` exercises the news filters.

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

**Ask FIRST, before any vault work — three questions, all three
answered before anything is created:**

1. Which Cloudflare account holds your Worker? (The connected
   account may not be it.)
2. What is the Worker's name / URL — do you already have one?
3. Where do the master password, the DEK and Pi's token come from —
   yours from an existing setup, or generate fresh?

**Why the questions matter:** a D1 database can only be bound to a
Worker in the SAME Cloudflare account — a D1 in account A cannot be
attached to a Worker in account B. And keys generated for a fresh
deploy are not the user's keys: if the user has an existing Worker
and keys, a fresh deploy builds the wrong vault. Listing one
account's Workers/D1s can never find a vault in another account, so
the check is a question to the user, not just an API list. If the
user has an existing Worker, do NOT create a fresh Worker/D1/keys —
use the existing-Worker path (§10.2b) instead.

### 10.1a Vault already deployed (second Muse) — use it, rebuild nothing

If the vault already exists at a known URL (for example
`https://cf-d1-vault.hardeepwalia77.workers.dev`, MCP at `/mcp`),
**stop: do NOT redeploy the Worker, do NOT touch its secrets, do
NOT create a fresh D1 or fresh keys — nothing to add again.** The
D1 already holds the encrypted keys; the Worker's secrets (master
verifier + DEK) are already set. The flow is:

1. The owner gives the master secret from his MAIN account (the
   first Muse's `vault-master-secret.txt`). He pastes the value
   himself into this Muse's `vault-master-secret.txt` (chmod 600) —
   never through chat, never printed, logged or committed.
2. This Muse is **owner-equal** (owner decision 2026-11-19): it
   holds the same master secret and unlocks for itself. It copies
   ONLY the master secret value + the vault URL from the first
   Muse. **No key files, and NOT the DEK backup** — that is disaster
   recovery for the Worker itself; a second Muse never needs it.
3. Holding the master secret, this Muse registers **its own new
   agent_id** in the vault (never reuse agent `pi`'s token, never
   take the first agent's identity) and stores its own request-only
   bearer token in its MCP client config, pointing at the existing
   `/mcp` URL.
4. It records the unlock procedure (POST `/unlock` with the master
   bearer, `agent_id` + `service` + `key_label` + a fresh UUID
   `request_id`; grants last exactly 2 hours), the service +
   key_label pairs it may use, and the never-print rule for the
   master secret — in a connector doc / skill.
5. Verify: MCP `initialize` with its own token → serverInfo
   `cf-d1-vault`; `tools/list` OK; a locked call →
   `unlock_required`; one granted call → real response.

### 10.2 Fresh deploy (only if no vault exists anywhere)

Follow this repo's README: create the D1 database, note its id into
`wrangler.toml` (the shipped file contains the author's values — replace
them), set `PUBLIC_ORIGIN` to **your** deployment origin, apply all
three migrations in order (`0001_init`, `0002_multi_service`,
`0003_rename`), generate the secrets with
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

### 10.2b Existing Worker path (the user has their own Worker/keys)

Do not deploy anything. Build one paste-ready folder (e.g.
`vault-your-worker/`) holding the whole program (`src/`, `public/`,
`migrations/`, `package.json`, `tsconfig.json`, `wrangler.toml` with
the Worker's name and `PUBLIC_ORIGIN` filled in — or placeholders if
the user has not named it yet), a `00-START-HERE.md` with the exact
steps (copy files in, `npm install`, `npm run check`, `npm test`,
deploy, set secrets, register agent `pi`, add keys on the manual
page, point Pi at the Worker's URL), a `KEYS.md` saying which secret
goes where, and the USER'S key files (chmod 600) — never keys
generated for a throwaway deploy. If the Worker's account already
has a `cf-vault` D1 with the migrations applied, bind it (keep its
`database_id` in `wrangler.toml`) and skip the migrations; if the
Worker is in a different account, the D1 must be created in THAT
account and all three migrations run there — a D1 cannot be bound
cross-account. The user deploys, or hands over the Worker name so
the config can be finished for them. No key value ever appears in
chat, a prompt, a log or the repo.

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
- [ ] Search is combined on every call: `search` runs TinyFish AND the
      cf-search Worker together and merges/dedupes (never one as a
      fallback); `search-cf` exposes the full Bing filter set; web/news
      never request page > 1.
- [ ] Named tunnel URL loads the Admin page; its DNS CNAME is proxied;
      cloudflared was never restarted inside its tmux session.
- [ ] Model keys are in BOTH box stores (`provider-keys.env` for the
      gateway, `/root/.profile` + `/root/.bashrc` for the watcher) and
      both paths answer after a gateway + watcher restart.
- [ ] No generated secret was hand-transcribed: the Admin password was
      hash-verified against `PI_ADMIN_PASS_SHA256` before handover.
- [ ] Hallmark `SKILL.md` present on both sides.
- [ ] Vault: account, Worker and key source confirmed with the user
      BEFORE any deploy (§10.1); if the vault already exists at a
      known URL, use it — no redeploy, no fresh keys (§10.1a); master `/whoami` → master; Pi-token MCP `tools/list` OK;
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
| Sandbox Start takes ~25–30 min | Normal on the free tier (node queue ~15 min + ~10 min image pull). The Apps page may briefly show "server unavailable" while starting; it clears on its own (§3). |
| Files API 502s while the server starts | Server not up yet, not a broken token — poll every ~2 min, give up only after ~60 min of continuous failure (§4). |
| `setup-sandbox.sh` fails once on apt | Transient fetch failure — re-run the exact same script once before diagnosing (§4). |
| `muse-pi.py get` dies with Altare API 502 | The outbox result file does not exist yet — the Files API 502s on a missing path. The task may still be running, or its deliverable may already be on the box. Do not loop `get` and do not call the task failed: check the box over SSH (`ls /root/pi-bridge/outbox/`, `ls` the deliverable) and fetch it with `scp`. Judge a Pi task by its deliverable on the box, not by its receipt. |
| `pi-api.py prompt` returns "started", no text | That is the async reply, not a failure and not an answer — read it back with `pi-api.py status <id>` (`last_assistant_text`) (§5). |
| Gateway path times out right after a key change | The gateway has not picked the key up yet — restart the gateway after ANY key change (§6). |
| Direct tailnet call returns empty / RemoteDisconnected | Tailnet 100.x needs the VM's :3130 proxy (`pi-api.py` handles it) — never test the gateway with plain curl to the tailnet IP (§5). |
| SSH "Host key verification failed" after a VM replacement | `/root/.ssh/known_hosts` was wiped with ephemeral `/root` — re-add the keyscan key there (and keep a persistent copy in `~/.ssh/known_hosts`) (§4). |
| `muse-pi.py put` file lands in a doubled path | `put` prepends `/root/work/` — pass paths relative to it, never absolute `/root/work/...` paths (§4). |
| Tunnel login POST 403 error 1010 | Cloudflare "bad browser" — scripted calls through the tunnel need a real browser User-Agent (§7). |
| Tunnel login POST times out / drops, then works | Node load flakiness — retry twice before concluding anything is broken; count the retries against the 5-failure lockout (§7). |
| Tunnel shows "precheck complete", no registration line | Lagging console pane — trust the Cloudflare API + direct SSH `capture-pane` over it (§7). |
| Admin password you handed over fails | It was hand-transcribed wrong — never hand-transcribe a generated secret; verify by hash BEFORE giving it to anyone (§7). |
| A tunnel/worker already exists on the account | List `tunnels` + `zones` (or Workers/D1s) before creating anything; never touch a tunnel you did not create (§7, §10.1). |
| A second Cloudflare/GitHub account is needed | Connect it as a SEPARATE connector — never `reconnect` the first connector with a different account's token, or it is replaced (§1). |
| Vault keys come from the user's other account | Never deploy a fresh vault with fresh keys on assumption. Ask which account, which Worker, whose keys (§10.1) — a D1 cannot be bound cross-account, so a Worker in another account needs its own D1 + migrations, and the folder must be built with the user's keys (§10.2b). |
| Vault MCP answers 406 | Missing `Accept: application/json, text/event-stream` (§10.2). |
| Granted vault `github_read_file` fails with `{"error":"operation_failed","kind":"ZodError"}` | The vault caps file reads at 32 KB (`size: z.number().max(32768)` in `src/github.ts`) — the file is too big (e.g. README.md at 47,658 B). The grant, key and token are fine; read a smaller file, or fetch the big file another way (§10). |
| Duplicate vault infra appears | Someone deployed already, maybe in another account → check first (§10.1). |

---

*Written 2026-11-18 from a complete live setup. Keep it current: when a
setup step changes or a new failure is found, update this file in the
same change — a stale guide is worse than none.*

## Lessons — 2026-11-19 (AgentX PR #84 night)

- **curl `-d` with a big body in argv breaks at ~128 KB.** Linux caps a single
  argument (MAX_ARG_STRLEN); a 126 KB JSON body passed as `-d "$body"` fails
  every attempt with `[Errno 7] Argument list too long`, and a retry loop just
  fails identically four times. Fix: write the body to a temp file and send
  `-d @file`. (Found in seek.sh, the 100milionseek DeepSeek consult wrapper;
  fixed and smoke-verified the same night.)
- **Background jobs and /tmp do not survive a VM/sandbox replacement.** A long
  review job launched with nohup died silently when the VM was replaced; its
  prompt and log lived in /tmp and vanished with it, so the run looked
  "still going" for hours. Rules: keep prompts, logs and state files in
  persistent workspace paths, never /tmp; if the output file AND the log are
  both missing, the job is dead, not running; verify liveness by the real
  child process (e.g. the curl doing the work), never by `pgrep -f <pattern>`
  — the pattern also matches your own checking shell and reports a false
  "running".

# Part II — Pi as the coding engine (2026-11-19) + every lesson from that night

Purpose: a fresh Muse with this file (plus README.md and SETUP-PROMPT.md)
can run the whole system in one shot — set up nothing twice, hit no known
trap twice. IDs, IPs and keys are placeholders; the real values live in the
owner's connectors, the box's files, and Muse's memory — never in this repo.

## The operating playbook (how production work runs through Pi)

1. **Knowledge pack first, code never first.** Write a BRIEFING.md for the
   project (mission, current state with exact shas/counts, the queue in
   order, house rules, hard boundaries) and put it on the box with the
   project's own source-of-truth files (for AgentX: TODO.md + STATUS.md)
   at /root/work/<project>/ via `muse-pi.py put`. Prompt 1 to Pi is always:
   read all of it, report your understanding, VERIFY the state against
   GitHub yourself, list everything you cannot verify or do not
   understand. Pi's verification round caught real pack errors (stale
   "AutoClaw builds" tags, a stale STATUS) before any code existed.
2. **Answer every question, then provision.** A fresh box has **no git, no
   pnpm, no docker** — only node + npm + corepack. Pi is root on its own
   box and provisions itself: `apt-get update && apt-get install -y git`
   (with DEBIAN_FRONTEND=noninteractive), `corepack enable && corepack
   prepare pnpm@latest --activate`. Inside a repo, the repo's
   `packageManager` pin wins over the activated pnpm (rakazo pins
   pnpm@12.18.0) — that is correct, not a conflict.
3. **Confirm the write path in a THROWAWAY session before the work session
   commits anything.** One tiny file, one new test branch, nothing else.
   Verify the commit sha from outside the box (GitHub API). Only then does
   the work session get told the mechanism. (Mechanics below.)
4. **Small prompts, one step each, same session.** Each prompt ends with
   "report what you changed / ran / resulted, then stop". Muse tests
   everything Pi ships (CI + independent checks, never Pi's word alone);
   every bug found goes back into the SAME session as the next prompt.
   That loop — Pi commits, Muse tests, bugs return as prompts — is the
   whole method. One session per topic, registered in pi-sessions.json;
   reuse it, never respawn per task.
5. **Merges and deploys stay with Muse.** Pi opens PRs and gets CI green.
   Risky PRs additionally get a DeepSeek (100milionseek) pre-merge review.
   A PR the owner has put on hold is not merged even when green.

## How Pi reaches GitHub — the vault write path (verified 2026-11-19)

- The vault MCP exposes exactly three GitHub tools:
  `vault_github_read_file` and `vault_github_list_issues` (read-only) and
  **`vault_service_request`** — a generic authenticated HTTP proxy. That
  proxy IS the write path: any method (GET/POST/PUT/PATCH/DELETE), the
  Worker decrypts the stored credential server-side, the secret never
  reaches Pi.
- Parameters: `key_label`, `service`, `path`, optional `method`, `body`.
  The label is whatever the vault entry was named when it was stored
  (typically `<github-username> github`). It is deliberately NOT written
  in this guide — every setup has its own. Record YOUR label in your
  private memory and in the project briefing, never in a shared repo:
  in the run this guide is based on, the label was written down nowhere
  and had to be recovered from a prior session, and a model left to
  guess picks a wrong label and gets `unlock_required`.
- `service: "github"` maps `path` 1:1 onto the GitHub REST API, so the
  token's full permission set is reachable (refs, contents, PRs, merges).
- **Contents-API writes: ALWAYS set `"branch"` in the body.** Omit it and
  the write lands on the DEFAULT branch (main). This is the single most
  dangerous default in the whole system.
- Body cap: **32,768 chars per service_request** (base64 inflates file
  content ~33%, so ~24 KB raw per file per call). Larger files need the
  git-data API in pieces or a report back — never silent splitting.
- Errors are masked: failures come back as `{"error":"upstream_failed"}`
  with no HTTP status. A 404 and a 403 are indistinguishable — diagnose by
  READING STATE BACK (does the ref/file exist now?), never from the error.
- **Vault read_file fails on ~40 KB files** (response-size validation):
  README.md and AGENTS.md reads were silently swallowed. Workaround for
  PUBLIC repos: `curl raw.githubusercontent.com/...` — and a public repo
  clones with no credential at all, which is how Pi got its working copy.
- Vault admin/unlock calls made from the Muse VM need a **browser
  User-Agent** (a plain urllib UA gets a Cloudflare 403), and `/unlock`
  requires a `request_id` (a fresh UUID).

## Gateway mechanics (pi-api.py) worth knowing before you drive it

- `prompt` is ASYNC: it returns a session_id and `disposition: "started"`.
  Poll `status <id>`; while a turn runs, `last_assistant_text` is `{}`.
  A finished turn shows `running: false` and the full final text. Long
  DeepSeek turns (40 KB of reading + max reasoning) legitimately take
  10–20 minutes — a quiet session is not a dead one.
- Live progress: `GET /sessions/{id}/events?since=N`.
- The gateway's `/files` listing can hang on huge directories
  (node_modules) — fetch individual files with `muse-pi.py getfile`
  (Files API) instead.
- Pi packages installed on the box (2026-11-19): context-mode (needs
  Node ≥ 24.15 — box Node 24 lives in /opt/node24, installed from the
  .tar.gz dist because the box has no xz; pin exact versions, prerelease
  dist entries crash naive parsers), pi-mcp-adapter (settings.json
  `defaultTools` must include `"+codemode"` or the vault's codemode
  exposure silently changes), pi-hermes-memory (the only memory system),
  pi-lens (needs `npm install-scripts approve @ast-grep/cli` inside
  ~/.pi/agent/npm). Full notes: PACKAGES.md.

## Lessons from the PR #84 night (CI, reviews, deployment state)

- When CI logs are unreachable, **check-run annotations** are the only
  failure detail — and a failure with NO annotations is usually the
  lint/typecheck job dying outside annotated steps. Reproduce locally
  with the repo's own per-package `pnpm check` (tsc): Biome does not
  typecheck, and a bad cast (TS2352) passed every test while failing CI
  for two rounds.
- Local `tsc` without `prisma generate` floods **phantom implicit-any
  errors** across db files (the generated client is missing). Trust only
  errors in files you actually changed; the rest is fallout.
- A **closed `vi.mock`** of a shared module breaks with 500s the moment
  that module gains a new import (the mock returns undefined for the new
  export). When you add an export to a shared module, grep for closed
  mocks of it and give them pass-through implementations.
- A rerun of ONE failed CI job can restart the WHOLE workflow as a new
  attempt — read `run_attempt` and per-attempt conclusions before
  declaring anything red or green.
- **Pipeline state files and watchdogs:** never set the pipeline phase
  to `watching-ci` before the merge exists. The watchdog keys its
  rollout off `main_sha` + `merged_at_utc`; a premature watching-ci
  nearly redeployed the currently-live build (and restarted the sandbox
  for nothing). Pre-merge steps need their own phase name.
- **InstaBox `maxRunMinutes` is volatile** — the same run read 120, then
  240, then 480 minutes, changing mid-run. Never schedule a restart or
  a warning off a single reading.
- **Deployment compose files do NOT follow image pulls.** If a PR adds
  env passthrough lines to the repo compose, the same lines must be
  hand-inserted into the machine's compose file (timestamped backup
  first), the stack recreated, and the vars verified INSIDE the
  containers (print booleans, never values). Values in .env alone never
  reach the containers — this exact gap killed every MCP sign-in on the
  live app for a day (origins pointed at the raw sandbox URL instead of
  the public one). Rule: WEB_ORIGIN / BETTER_AUTH_URL / API_URL always
  equal the public origin.
- seek.sh body-via-temp-file and background-jobs-die-on-VM-replacement
  lessons: see the 2026-11-19 lessons section earlier in this file —
  they were learned the same night, on this same PR.

## Setup lessons 1–20, condensed (full text: LESSONS-LEARNED.md locally)

1. Skip any setup question the user already answered; say what you assumed.
2. `setup-muse.sh` prints the gateway token ONCE in its final output —
   treat all script output as secret; the token lives only in
   gateway-token.txt (600) and gateway.env.
3. A bundle with empty model keys still "succeeds" — gate on the
   empty-keys warning count before uploading, or every model but one
   fails later and looks broken. Keys live on the box in TWO stores
   (/root/pi-bridge/provider-keys.env for the gateway AND exports in
   /root/.profile + /root/.bashrc for the watcher — §6), never in models.json.
4. Files-API auth has two routes: an `ALTARE_API_TOKEN` env var, or the
   `custom.altare-platform` connector (surrogate). The token is created
   in the Altare console (Team → Settings → API tokens) with scope
   `servers:files`, and is entered ONLY through Muse's secure
   connector page — never chat. Team ID and server ID are NOT secrets.
5. Altare console login is a USER step: Muse opens the page, the user
   signs in themselves; Muse then works from that browser session.
6+7. Altare email verification has NO badge anywhere. The only signal is
   the Getting-Started checklist marking "Verify your email" Done — and
   that does NOT prove a confirmation mail was sent or clicked (the user
   never received one). Report exactly that; it blocked nothing.
8. "Account created" is NOT "sandbox created". On Altare a sandbox IS an
   app: if Apps is empty and resources read zero, creation did not
   happen — redo it, don't continue. Verify before every next step.
9. Prove a new Altare token with `GET /api-tokens/self` first — it
   returns name, prefix, team and scopes, never the value. The servers
   list (`GET /tenants/<team>/servers`) is ground truth for existence.
10. **Discord must be linked before Start works** — an undocumented
    anti-abuse gate. Link it (Account → Discord) BEFORE creating the
    sandbox. The console's stopped / "Connecting…" / "unavailable"
    trio all mean this one gate. The URL UUID is the API server ID;
    the short Overview ID is not.
11. Creation path: Apps → Create app → Software → Sandboxes. Region is
    a pre-selected default, not a real picker; the sandbox takes the
    whole team free pool (no sliders); team SSH keys must be added
    BEFORE creation to be selectable; no card prompt on the free tier.
12. `tailscale up` may not print its approval link inside a short shell
    window — the pending link is in `tailscale status`. Don't re-run
    `up` blindly.
13. **The npm package is `@earendil-works/pi-coding-agent`.** The
    unscoped `pi` package is a different project with no 1.5.2 — every
    `npm install -g pi@1.5.2` fails ETARGET forever. Pre-flight any
    install with `npm view <pkg>@<ver> version`.
14. After Discord linking the sandbox is still stopped — press Start,
    expect a node queue ("number 2 in line") on the free tier. And
    apt-get in setup scripts needs `DEBIAN_FRONTEND=noninteractive`
    or tzdata stops the run with an interactive timezone prompt.
15. Monid on the Muse VM: write the connector's SURROGATE into
    ~/.config/monid/credentials.yaml (600) — never a raw key. With no
    key, search returns nothing — DuckDuckGo was removed 2026-11-19
    (it returns [] from datacenter egress); the Monid/TinyFish leg is
    load-bearing, not a fallback.
16. `web.py research`: wrap the slow FxEmbed X call in try/except. One
    >60 s X timeout otherwise kills the whole research command even
    after the web half succeeded — slowness, not an outage.
17. `setup-sandbox.sh` never installed the search tool on the box: copy
    web.py to /root/pi-bridge/search.py and create the Monid
    credentials template (600) by hand, or Pi has NO search at all.
    Search is combined on every call — TinyFish AND the cf-search
    Worker (Bing) together, never one as a fallback — and without a
    Monid key pasted on the box (via the Pi Admin page), in-server
    search returns nothing.
18. **Read your own repos before "discovering" their features.** The
    Cloudflare vault, Monid search and Code Mode were all already
    built and documented in these repos. Check what's in an account
    (workers, D1 list) BEFORE creating anything — a duplicate empty
    D1 in the wrong Cloudflare account was created by skipping this.
    The user's vault Worker lives in a DIFFERENT Cloudflare account
    than the connected one; do not redeploy it.
19. `npx skills add <repo> -g` fails in this environment ("No valid
    skills found"). Install skills by copying the repo's
    `skills/<name>/` folder into place. `muse-pi.py put` is TEXT-only —
    binary payloads ride base64 and are decoded on the box.
20. Give the gateway a face: the /admin page (opening password = its
    SHA-256 in gateway.env as PI_ADMIN_PASS_SHA256; 5 failed logins =
    10-minute lockout) with /secrets, /settings and /monid endpoints
    replaced every console ritual for keys and models. ALL key/model
    management goes through that page; the raw gateway token also works
    as the login. Never paste a key into chat, a prompt, or a browser
    task — keys enter via the Admin page, Muse's secure pages, or
    stdin helpers only.

## If you remember only five things

1. Knowledge pack + verification round before any code (playbook step 1).
2. `"branch"` on every vault contents write — or you just wrote to main.
3. `@earendil-works/pi-coding-agent` — the unscoped `pi` package is a trap.
4. Durable paths only: background jobs and /tmp die on VM replacement.
5. Verify from OUTSIDE the system you're testing (GitHub API, live site,
   the database) — never from the worker's own report.

## Lesson 21 — A Pi turn can die silently at the provider, and the fix is the retry window (2026-11-19)

**Symptom.** An 18-minute turn (64 tool calls: a 2 m 24 s `pnpm install`
plus deep research) ended with the session idle and `last_assistant_text`
EMPTY. No error anywhere the gateway shows you. The work was all done;
only the final report was missing.

**Wrong first guesses** (all disproven): the prompt was too big / the
turn "ran out" (the model's own self-diagnosis said exactly this — it
was wrong); a gateway timeout (the gateway has none for turns — its
RPC timeouts are per-command, 15–60 s); a context or token limit (no
`length` stop anywhere in the log).

**Evidence trail — where the truth lives.** The gateway's `/events`
buffer is in-memory and only holds the latest page; its on-disk events
file is keyed by the spawn name (`new.events.jsonl` for a first spawn),
not the session id. The AUTHORITATIVE record is Pi's own session file:
`~/.pi/agent/sessions/<cwd-slug>/<timestamp>_<session-id>.jsonl` on the
box (also named by `$PI_SESSION_FILE` inside the session). It records
every message with its `stopReason`. Readable from outside via the
Files API — path traversal works (`../.pi/agent/sessions/...` relative
to the work root). Rule: **when a worker's self-diagnosis and the log
disagree, the log wins — pull the log before theorising.**

**Root cause.** The provider (100milionseek) returned HTTP 503
`{"code":"upstream_busy","retry_after_s":20}` four times in ~41 s at
the very end of the turn. Pi's agent-level retry then had the DEFAULT
policy: `maxRetries: 3`, `baseDelayMs: 2000`, cap 60 s — a total retry
window of roughly **14 seconds**. All retries burned inside the busy
window, the turn ended on an assistant message with
`stopReason: "error"` and `content: []`, and an empty-content final
message is indistinguishable from "nothing happened" in the status API.

**The fix (two parts, both verified live 2026-11-19).**

1. **Retry settings** in `~/.pi/agent/settings.json` (schema:
   `retry.*`, no server-side caps). Two independent layers exist:
   agent level (`retryAssistantCall`: pure exponential backoff, never
   reads `retry-after`) and provider level (`retryProviderRequest`:
   reads `retry-after`/`retry-after-ms` headers, fails fast if the ask
   exceeds `provider.maxRetryDelayMs`). Note the observed 20 s ask was
   in the JSON BODY (`retry_after_s`), not a header — so the agent
   layer is what actually carries recovery. Set:
   ```json
   "retry": { "enabled": true, "maxRetries": 12, "baseDelayMs": 15000,
              "maxAgentDelayMs": 120000,
              "provider": { "maxRetries": 4, "maxRetryDelayMs": 90000 } }
   ```
   Backoff 15→30→60→120→120… = a **19.8-minute** retry window.
   Settings are read at process construction and there is NO file
   watcher — a running session keeps the old policy until its process
   restarts (sessions resume from disk, so a restart is safe).
2. **No more silent turns:** patch `pi-gateway.py` so `reader_thread`
   records `last_error` when an assistant `message_end` has
   `stopReason == "error"` (cleared on `agent_start`), the session
   entry initialises it to `None`, and `/sessions/{id}/status` returns
   it. Eight lines. Any future dead turn now states its cause in the
   status call itself — no diagnostic round-trip.

**Standing protocol that follows from this:** size prompts in steps
anyway (a shorter turn has less exposure to a provider window), have
every step write its deliverable to a FILE incrementally (work emitted
as tool calls survives a dead turn; a report held in the model's head
does not), and when a turn ends with empty text, send the
continue-and-explain prompt immediately — do not wait for a human to
notice. With the retry window at ~20 minutes, a busy spell should now
be ridden out inside the turn instead of ending it.

## Lesson 22 — Long streams die silently, and detached jobs get reaped (2026-11-19)

Two separate failure layers killed the same job (a one-shot DeepSeek
review of a PR: 126 KB prompt, max reasoning, up to 65 K output tokens)
five times in one night. Small calls to the same provider answered in
seconds the whole time — the provider was never "down".

**Layer 1 — the long silent stream.** Each attempt ran ~4–5 minutes and
then ended with ZERO content. Mechanism: at `reasoning_effort: max` a
huge prompt sits silent for minutes (queue + prefill + thinking, and
the gateway does not flush early), and somewhere between client and
origin an idle/age limit ends the connection before the first content
token. First-byte latency was 7 s even for a trivial prompt that night.
Defences, all now in `seek.sh` v2 (committed in this repo):
- **Cap the output for verdict-style work** (`SEEK_MAX_TOKENS`; the owner
  set 32000 for PR reviews — a max-reasoning review of a full diff
  measurably completes at ~25–30 K tokens, so 16000 could cut the
  verdict itself): the answer a review needs is a few KB; a 65 K-token ceiling
  only buys stream lifetime you do not need. Shorter generation =
  a stream that finishes before anything can kill it.
- **Truncation is failure.** v1 accepted any non-empty content — a
  stream cut mid-answer looked like a finished one. v2 requires a
  `finish_reason` (`stop`/`length`); partial output is saved to
  `<out>.partial-<n>` and the attempt is retried.
- **Reasoning is evidence.** A dead attempt's reasoning trace is saved
  to `<out>.reasoning.partial-<n>`, never discarded.
- **Diagnosable deaths.** Every attempt logs duration, curl exit code,
  first-byte time, chunk count, reasoning/content sizes and
  finish_reason — the next death explains itself from the log alone.
- Backoff grew up: 6 attempts, 15→30→60→120 s (was 4 × 10/20/30 s).

**Layer 2 — detached jobs get reaped.** The review was relaunched
three times with `setsid nohup … &` from agent shell sessions. Every
instance later vanished WITHOUT a final log line — the retry loop
never got to finish, because the process died with (or shortly after)
the session that launched it. `nohup`+`setsid` is not durability in
this environment. Durable runners, in order of preference: a systemd
service; a runtime-tracked background job; a cron supervisor that
checks and relaunches (the 30-minute Pi supervisor does exactly this
for the review now). Rule: **if a job must outlive the turn that
started it, give it a supervisor, not a prayer** — and verify liveness
by the real child process (name match, e.g. `ps -C curl`), never by
`pgrep -f` (it matches your own checking shell) and never by "the log
hasn't complained".

**Pi side of the same class.** Pi's calls are many and small, so its
exposure is one response streaming long, plus hung silent requests.
The Lesson 21 retry window covers the retry side; v2 of the settings
adds the missing bound on a single silent request:
`retry.provider.timeoutMs: 300000` — a request with no bytes for
5 minutes errors out and the agent-level retry takes over, instead of
hanging a turn indefinitely. The repo's `pi/settings.json` now carries
the full fixed retry block so a fresh setup starts fixed; remember
settings are read at process construction — a running session picks
them up only at its next restart (sessions resume from disk, so that
restart is safe).

**Verification that counted:** seek.sh v2 probe (small prompt) —
`dur=7s first_byte=5s finish=stop`; settings re-downloaded from the
box after writing (values byte-identical); the capped review re-run
through v2 either completes or its log now states exactly how it died.


## Lesson 23 — A max-reasoning review can think forever and never answer; chunk it, and run long jobs behind a resumable wrapper + a cron supervisor (2026-11-19)

The PR #84 final review (126 KB prompt, reasoning_effort=max) failed across five
full runs and one 45 KB chunk before the pattern was proven from seek.sh v2's
per-attempt logs:

- The streams were NOT dying of silence. One chunk attempt streamed 23.6 min /
  59K chunks and produced 818,583 chars of reasoning and ZERO content, ending
  finish=length; another produced 250K reasoning chars and a spurious
  finish=tool_calls with no content. The model spends the entire budget
  thinking — it got stuck re-deriving one question (whether files import a
  symbol the diff hunk didn't show) — and the answer never starts.
- The output cap does NOT save you: the gateway does not bind reasoning to
  max_tokens the way you would expect (818K chars of reasoning sailed past a
  32000 cap). The owner-set 32000 review cap stays, but the binding fix is
  SCOPE, not the cap.
- What works: (1) split the review into scoped chunks (e.g. RLS core vs call
  sites) with an explicit scope note — "points whose evidence is in the other
  part = not established in this part"; (2) add a reviewer-discipline addendum:
  "CI is green and the code compiles — if a hunk doesn't show an import, it
  already exists; do not re-derive it. Be decisive per point; write each
  section as you finish it."; (3) keep every dead attempt's reasoning trace
  (.reasoning.partial-<n>) — it is real analysis and evidence even when the
  verdict never lands.
- seek.sh bug found by its own diagnostics: when a stream died before the
  first byte, first_byte stayed None and the stats line crashed ("unsupported
  format string passed to NoneType.__format__"), burning an attempt with a
  misleading error. Stats formatting is now None-safe; the seek.sh in this
  repo carries the fix.
- Muse's own runtime restarts (frequent deployments) kill background exec
  sessions silently — twice in one hour — and detached setsid/nohup jobs get
  reaped too. Durable pattern for long local jobs: a small IDEMPOTENT wrapper
  script (skips steps whose outputs already exist, assembles the final
  artifact) + a scheduled supervisor job that checks liveness and relaunches
  THE WRAPPER. The wrapper alone dies; the cron alone has nothing resumable
  to relaunch; together they self-heal.
- Driving pattern (owner-confirmed): all build work happens in Pi; every step
  prompt opens "Continue from where you left off", one step per prompt; the
  finish of a step triggers verification + the next prompt — by the supervisor
  on its 30-min pass or immediately — never left idle waiting to be reminded.


## Lesson 24 — unlock_required is routine: the admin agent unlocks, grants last 2 hours (2026-11-19)

Pi finished a fix, tried to push, and reported the push "blocked — the vault
refuses every key label with unlock_required". The assistant initially passed
this to the owner as an owner-only blocker. WRONG — the owner had to remind
the assistant how its own vault works (§10.5 of the vault guide already said
it plainly: "Pi hits unlock_required → the assistant unlocks").

The mechanics, so no future instance repeats the mistake:

- A grant authorizes ONE agent to use ONE service + key label for **2 hours**
  (expires_at = opened_at + 7200). Expiry mid-program is normal and expected.
- The agent (Pi) holds a request-only bearer and **cannot unlock itself** —
  a locked call returns {"error":"unlock_required", ...} by design.
- **The assistant IS the vault admin.** The master secret lives in a
  600-perm file in the assistant's own workspace (vault-master-secret.txt —
  never print it). Unlocking is one call:
  POST <vault-origin>/unlock, header `Authorization: Bearer <master>`,
  body {"agent_id":"pi","service":"<service>","key_label":"<label>",
  "request_id":<fresh uuid>} → 200 with the grant id and expires_at.
  Replaying a request_id returns the original grant; use a fresh one per
  unlock.
- Correct handling when a worker reports unlock_required: unlock immediately,
  prompt the worker to retry, move on. Never present it as an owner blocker,
  never leave work parked on it. The standing supervisor job carries the same
  instruction, so the unlock happens even between conversations.

## Lesson 25 — Pi has no auto reasoning mode; route difficulty at the driver (2026-11-19)

- Pi's reasoning effort is a FIXED per-profile value (`samplingParams.reasoning_effort`
  in models.json), sent identically on every call. A one-line file read thinks as
  hard as a security design. Neither Pi 1.5.2 nor the gateway has a
  difficulty-adaptive "auto" mode, and the model cannot scale itself — the
  client picks the level. A max-effort agent step is a loop of dozens of these
  calls, which is why steps take 10–30 minutes while a single consult takes
  seconds.
- Fix: driver-level routing. Register a TWIN provider for the same model with
  `reasoning_effort: "high"` (same baseUrl, same `$ENV` key reference, same
  context/output limits; here: provider `100milionseek-fast` next to
  `100milionseek`). Whoever sends a step prompt classifies the step first:
  mechanical steps (tests/checks, plan-mechanical edits, git/commit/push,
  exact-instruction config edits) run on the fast profile; design,
  security-sensitive code, unknown-cause debugging and reviews stay on max;
  when unsure, use max.
- Switching is mid-session, context preserved, via the gateway's generic RPC
  passthrough: POST /rpc {"session_id": ..., "command": {"type": "set_model",
  "provider": "<provider>", "modelId": "<model id>"}}. Verify with
  {"type": "get_state"} — data.model.provider and data.model.samplingParams
  show what is actually live.
- WARNING: the gateway's dedicated POST /sessions/{id}/model route is BROKEN —
  it nests the model inside a "model" field, while Pi's RPC wants top-level
  provider + modelId, so every shape sent through that route fails with
  "Model not found: undefined/undefined". Always switch via /rpc.
- Verified live both directions 2026-11-19 (fast profile answers; switch to max
  and back confirmed by get_state). The standing supervisor job carries the
  classification rule as its step 5c and sets the model before every prompt it
  sends.
