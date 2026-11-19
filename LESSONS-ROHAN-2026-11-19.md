# Lessons from the 2026-11-19 Rohan run — mistakes made, and what to change

DRAFT for `0xSatwik/muse-pi-setup`, written 2026-11-19 by Muse after a
fresh setup run for a new user (Rohan) on a brand-new Altare account.
Purpose: fold these into SETUP-PROMPT.md / COMPLETE-SETUP.md / README.md
so the next new user does not hit the same traps. Nothing here contains
a secret value. IDs below are the run's real public identifiers (team,
server, tunnel, zone) so a future reader can match them against the
account; rotate nothing on their account.

## The run in one paragraph

New user, Altare host, fresh Altare account (team "Default"), fresh
Cloudflare tunnel account. Muse-VM part via `setup-muse.sh` went clean.
Sandbox `pi` created in the browser, Ubuntu 24.04, Bishkek, full free
pool (6 GiB / 150% / 10 GiB), Start queued 3 → 2 → 1 (~15 min), then
~10 min Docker image pull, then "Sandbox ready". Team token proved with
`GET /api-tokens/self`, servers list was ground truth. Named tunnel
`ratulbaba` created via the Cloudflare API plus a proxied CNAME
`ratulbaba.pitunnel.dpdns.org`. Bundle upload was in progress when
these notes were written. Model keys were NOT on the box yet (bundle
5/5 empty); they go in later through the Pi Admin page, per the guide.

## Mistakes the assistant made (own them, fix the prompt so they cannot repeat)

### 1. Treated the team API key as the setup path

What happened: the assistant framed the Altare team API token as the
thing that would "do the setup", and only after the user corrected it
("the platform key will not able to do these, the key is for something
else") went back to the browser-first flow.

Why it is wrong: the repo already says it plainly — team API tokens
CANNOT create sandboxes (403 `TOKEN_ROUTE_NOT_ALLOWED` by design) and
Discord linking is user-only. The key is Files API access only
(upload the bundle, the Pi bridge). The assistant had read the repo
but acted from its own summary instead of the guide.

Fix for the prompt: make SETUP-PROMPT §1 question 1 and §3 say it in
one line a fresh assistant cannot miss: "The API key NEVER creates
anything. It only reads files on a sandbox that already exists. Every
creation step happens in the browser." Put the same line at the top of
COMPLETE-SETUP §3.

### 2. Sent the browser to create the sandbox without the name `pi`

What happened: the first browser instruction said "create the sandbox,
Ubuntu 24.04, whole free pool" but never gave the name. The browser
created it as "sandbox" and had to rename it to `pi` afterwards in
Settings — an extra step, and a rename is a second chance to break the
server record.

Fix for the prompt: the creation checklist in SETUP-PROMPT §1 must
list the name FIRST, as a copy-pasteable line: name `pi`, Ubuntu
24.04, whole free pool, SSH keys only, region = pre-selected default.
An assistant that has not read the name must not send the browser
anywhere.

### 3. Worked from memory of the guides instead of re-reading them

What happened: the assistant had read all 39 files hours earlier and
then drove the setup from its own summary. The user had to say "read
all github setup guide, dont try to do it yourself" before it re-read
SETUP-PROMPT.md and COMPLETE-SETUP.md in full — and only then found
mistake #2 and confirmed the local `setup-sandbox.sh` already carries
the correct `@earendil-works/pi-coding-agent@1.5.2` line.

Fix for the prompt: add a rule to SETUP-PROMPT §6: "Before you send
any browser task or run any host step, re-read SETUP-PROMPT.md and
COMPLETE-SETUP.md in full in this session. A summary from an earlier
turn is not a read." A fresh assistant should also verify the Pi
package line in the local `setup-sandbox.sh` with grep before running
it, not assume the patch is in.

### 4. Asked questions the user had already answered, and asked about things it could check itself

What happened: after the first report the assistant asked the host /
models / Monid / vault questions again through an options widget, and
asked whether the user already had a live Altare sandbox "pi" from the
author's 2026-11-18 run — without first checking the servers list,
which is the ground truth and takes one call.

Fix for the prompt: SETUP-PROMPT §1 already says "skip any question
already answered"; extend it: "and never ask whether a sandbox exists
— call `GET /tenants/<team>/servers` first; an empty list is the
answer." Same for the token: prove it with `/api-tokens/self` before
asking anything about it.

### 5. Left the sandbox name and the token name unverified

What happened: the browser reported a team token named "vcxvx"
created by the user, while `GET /api-tokens/self` later returned the
token name "bbcv". The assistant never resolved the mismatch and
moved on.

Status: unresolved at the time of writing. It may be a misread by the
browser, or two different tokens. Fix for the prompt: when two sources
disagree on a name or id, stop and say so in one line — do not carry
both silently. (Token name is metadata, not a secret; it is safe to
quote.)

### 6. Created the named tunnel before the gateway was running

What happened: the tunnel `ratulbaba` and its DNS CNAME were created
via the Cloudflare API while the gateway was still not installed on
the box. It worked — the API allows it — but the tunnel sits inactive
until cloudflared connects, and its credentials file now has to be
staged locally (chmod 600) and placed on the box later.

Why it matters: the guide's order is gateway first, named tunnel
after, precisely so the credentials go straight onto the box in one
step. Doing it early adds a staging file and a second handoff.

Fix for the prompt: keep the order, but add the exception the run
proved: "If the domain already exists as a zone, creating the tunnel
object and the proxied CNAME early is safe — they wait inactive.
Never stage the tunnel credentials anywhere except a chmod-600 file,
and place them at `/root/.cloudflared/` in the same step that starts
cloudflared."

## Learnings (things the run proved, worth adding to the guides)

### L1. Discord was already linked — check, do not assume the gate blocks

Account settings showed Discord "Linked" before any sandbox step.
The gate only blocks when it is unlinked. The browser check costs one
navigation; assuming it blocks costs a whole round trip with the user.

### L2. Free-tier Start takes ~25–30 minutes end to end

Observed: node queue 3 → 2 → 1 over ~15 minutes (node at 100%
processor time busy), then ~10 minutes pulling the Docker container
image, then "Sandbox ready". Tell the user this up front so the wait
does not read as a failure. The Apps page can briefly show "Your
server pi is unavailable right now... couldn't connect to the node"
while starting; it clears on its own.

### L3. Check existing tunnels and zones before creating anything

The tunnel account already held a healthy tunnel `hardeepwalia`
(4 live connections) and a zone `pitunnel.dpdns.org`. Same class of
mistake as the duplicate D1 in COMPLETE-SETUP §10.1: create only what
is actually missing. New prompt rule: "`tunnels` list and `zones`
list are the first two calls on any Cloudflare account, before any
create. Never touch a tunnel you did not create."

### L4. The Altare servers list is the only existence check that matters

`GET /tenants/<team>/servers` returned `items: []` before creation
and the full server record after (id, name `pi`, 6144 MB, 10240 MB,
150% CPU, location 4). The console Apps page agrees with it; the
"account created" banner does not. The single-server GET endpoint
(`GET /tenants/<team>/servers/<id>`) returned 403 for this token —
use the list endpoint, not the detail endpoint.

### L5. Files API 502s while the server starts

While Start was queued, the Files API answered HTTP 502 Bad Gateway.
That is "server not up yet", not a broken token. Poll every ~2
minutes; give up only after ~60 minutes of continuous failure.

### L6. API-created tunnels return everything needed in one response

`POST /accounts/<id>/tunnels {"name": ...}` returns the tunnel id,
the credentials file object (`AccountTag`, `TunnelID`, `TunnelName`,
`TunnelSecret`) and a `token` for `cloudflared tunnel run --token`.
Save the credentials file immediately to a chmod-600 file and never
print it. The DNS record is a separate call: CNAME
`<name>.<zone>` → `<tunnel-id>.cfargotunnel.com`, `proxied: true`,
`ttl: 1`.

### L7. A second Cloudflare account needs a second connector

The first Cloudflare account (`custom.cloudflare`) stays untouched.
A new account is connected as a separate connector
(`custom.cloudflare-tunnel`) with the same api_hosts and
bearer_header placement — the same pattern as a second GitHub account.
Never `reconnect` the first connector with a different account's
token; that would replace it.

### L8. Tailscale has no connector to hand over

The VM joins with the built-in client (`/opt/hatch/bin/tailscale up`,
device `muse`) and prints an approval link only the user can open.
The sandbox joins as `pi-altare` from `setup-sandbox.sh`. Three
approvals total, all by the user. There is no token or link the
assistant can "give" for Tailscale — the approval link IS the handoff.

### L9. Keys go in the Admin page — the user said it, the guide says it

Monid and all provider keys enter through the Pi Admin dashboard
(`<gateway-url>/admin`), write-only, never chat, never the bundle.
When the user repeats a guide rule back to you, confirm it and move
on — do not re-explain the rule as if it were new.

### L10. setup-sandbox.sh can fail once on apt and succeed on a plain re-run

First run failed after 15m27s at the Tailscale install: apt could not
fetch `libnfnetlink0` (Connection failed). Re-running the exact same
script once succeeded end to end (Node 22, Tailscale 1.104.7, Pi,
bundle placed, Monid template created). A transient apt failure is not
a broken script — re-run it once before diagnosing further.

### L11. The Altare web console lags badly

The terminal can show a shell prompt long before the running script's
output catches up. A "finished" appearance is display lag, not an
exit. Wait ~30 seconds and press Enter before concluding a command
failed or finished.

### L12. Never hand-transcribe a generated secret from tool output

On 2026-11-19 the assistant generated the Admin opening password
three times and mis-copied it every time (23 chars, then 29 chars,
then 3 words — the generator makes 24 chars / 4 words). The user
tried the wrong password and it failed, and the assistant's own
tests failed the same way. The hash check against
`PI_ADMIN_PASS_SHA256` in gateway.env caught each bad copy — but only
AFTER the wrong password had already been sent to the user the first
time. Rule: a generated secret is verified by hash BEFORE it is
given to anyone, and the reliable way to set one is for the assistant
to author the value itself (stdin, never output) so no transcription
is needed. A word passphrase (e.g. `mango-river-tiger-harbor-42`) is
the human-copyable form. The final password was verified over both
the tailnet and the tunnel URL before it was handed over.

### L13. Cloudflare 1010 blocks non-browser clients on the tunnel URL

A POST to `https://<tunnel>/admin-login` from Python urllib's
default User-Agent returns HTTP 403 error code 1010 (Cloudflare
"bad browser"). The gateway itself never returns 403 on that route
(it returns 401 wrong password, 429 locked out). Any scripted call
through a tunnel must send a real browser User-Agent. The Admin
page's own fetch in a real browser is fine.

### L14. Tunnel POSTs are flaky under node load — retry, do not re-diagnose

On the same afternoon the tunnel login POST variously timed out at
30s, closed the connection without a response, and then succeeded
in ~1s — with nothing changed on the box. The sandbox node was at
load ~112. A single failed tunnel POST proves nothing; retry twice
before concluding the password or the tunnel is broken. Note the
lockout: 5 failed logins lock the Admin page for 10 minutes, so
space retries out and count them — a restart of the gateway clears
the in-memory counter.

### L15. Browser pane != tunnel state

The console browser's `tmux capture-pane` on `pi-tunnel` showed the
log stuck at "precheck complete" with no "Registered tunnel
connection" line, while the tunnel was in fact registered: the
Cloudflare API listed `ratulbaba` healthy with 4 connections and a
direct SSH `capture-pane` showed the registration lines. Trust the
API + SSH over a lagging console pane.

### L16. Say OK "timeout" — two separate causes, neither is Pi being down

On 2026-11-19 the gateway-path Say OK first returned `timeout
waiting for pi response`, then the fixed run returned
`{"disposition": "started"}` with no reply text. Both are traps:
(a) `pi-api.py prompt` is ASYNC — the reply is never in the prompt
response; read it back with `pi-api.py status <id>`
(`last_assistant_text`) or `events <id>`. (b) The first timeout
happened because the gateway had NOT picked up the new model key —
the key was added via the Admin page AFTER the last gateway restart.
Restart the gateway after ANY key change. (c) Never call the gateway
URL with plain urllib: tailnet 100.x needs the VM's :3130 tunnel
proxy (pi-api.py handles it); a direct call comes back empty /
RemoteDisconnected and looks exactly like the gateway being down
when it is running fine. Check `ps` on the box before concluding
the gateway died — and note a /restart POST that drops its response
is normal, not a failure.

### L17. SSH host key lost after a VM replacement

SSH reads known_hosts from the PASSWD home (`/root/.ssh/` for uid
0), not from `$HOME`. `/root` is ephemeral across VM replacements,
so a replacement wipes `/root/.ssh/known_hosts` and SSH fails with
"Host key verification failed" even though the identity key and the
box are fine. Fix: re-add the keyscan key to `/root/.ssh/known_hosts`
(box key fingerprint SHA256
78aa0ad6b7f7ea9c9eda6c38a1d42f884071a9fab4358de5fec5606ad4d37d66) and
keep a persistent copy in `~/.ssh/known_hosts`. Verify the box
afterwards by checking for your own files (hostname is the container
id, `/root/pi-bridge/` holds the gateway files) — if a middleman
were proxying, those would not be there.

### L18. Fallback path needs keys in .profile too — the Admin page only writes one store

Model keys live in TWO places on the box: `/root/pi-bridge/provider-keys.env`
(read by the gateway) AND exports in `/root/.profile` + `/root/.bashrc`
(read by the watcher via `load_profile_env()` for the file-queue
fallback path). The Admin page / gateway writes `provider-keys.env`
ONLY. Result on 2026-11-19: Say OK passed on the gateway path while
the fallback path failed with "No API key found for 100milionseek".
Fix: sync the exports on the box from `provider-keys.env` (a script
that reads the file and appends `export NAME='...'` lines, never
printing a value) and restart the watcher (`tmux kill-session -t
pi-bridge`, then recreate it running watcher.py). Durable repo fix:
the gateway's `/secrets` handler should write both stores, or the
watcher should also load `provider-keys.env`.

### L19. muse-pi.py put prepends /root/work/ to the remote path

`put local /root/work/file` lands at `/root/work/root/work/file`.
Pass just the filename (or a path relative to `/root/work/`) as the
remote argument, and `ls` the box to confirm where it landed.

### L20. The vault was missed in the first pass — keep it on the checklist

The first setup run did gateway, search and packages but never
started the vault (§10 of COMPLETE-SETUP.md), and only the user's
prompt caught it. Do the vault before declaring setup done. Note for
the check itself: no vault Worker or D1 existed in either connected
Cloudflare account (QwenPaw account: Workers are only the six
qwenpaw-* ones, D1 only qwenpaw-state; tunnel account: no Workers,
no D1s), so a fresh deploy was correct — the check is what makes
that safe to say.

### L21. Delegation skill — install DELEGATION.md as a skill

`DELEGATION.md` in the repo is the skill for running Pi (ask/send/get
+ gateway sessions, one session per topic, the registry file). Install
it as a custom skill (`pi-delegation`) in Muse so the delegation
flow is the default for long/heavy work, not something remembered
from the repo each time.

### L22. Vault: ask which account, which Worker, whose keys — BEFORE deploying anything

On 2026-11-19 Muse deployed a FRESH vault (new Worker `cf-d1-vault`,
new D1 `cf-vault`, fresh master password + DEK + Pi token) in the
connected QwenPaw Cloudflare account — without asking. Rohan then
said the keys come from his OTHER account and he has his own Worker.
The fresh deploy was the wrong thing to build: its keys are not his
keys, and its D1 cannot be bound to a Worker in a different
Cloudflare account (D1 bindings are same-account only). The fix is
a question asked FIRST, before any vault work: which Cloudflare
account holds your Worker, what is the Worker's name/URL, and where
do the master password, DEK and Pi token come from (yours, or
generate fresh)? If the user has an existing Worker and keys, do NOT
create a fresh Worker/D1/keys — package the vault files for their
Worker instead (code + steps + key files in one folder, e.g.
`vault-your-worker/`), and let them deploy or hand over the Worker
name so the config can be finished for it. The §10.1 "check what
already exists" must cover OTHER accounts, not just the connected
one — listing one account's Workers/D1s can never find a vault in
another account.

### L23. `muse-pi.py get` 502 means "result not ready yet" — not "task failed"

Twice on 2026-11-19 `muse-pi.py get <id>` died with `Altare API
HTTP 502` while reading `/root/pi-bridge/outbox/<id>.json`. The
outbox file did not exist yet — the Files API returns 502 on a
missing path (same behaviour as the LIST 502 on a nonexistent
directory, L4). A 502 from `get` therefore says nothing about the
task: Pi may still be working, or may already have written its
deliverable without the outbox receipt landing yet. Do NOT retry
`get` in a loop and do NOT conclude the task failed. Check the box
directly over SSH instead: `ls /root/pi-bridge/outbox/` and `ls`
the deliverable file, and fetch it with `scp` when the file matters
more than the receipt.

### L24. Judge a Pi task by its deliverable on the box, not by its receipt

Pi wrote `/root/work/search-new.py` (34,727 bytes) at 09:12 UTC, but
the outbox JSON for that task still was not there minutes later
while `get` kept 502ing. The work was done; only the receipt was
missing. When a task's deliverable is a file, check for the file
first — the outbox result is a formality that can lag or fail
independently.

### L25. When the user owns the Worker, give them a paste-ready folder

Pattern that worked on 2026-11-19 for the vault: one folder
(`vault-your-worker/`) holding the whole program (`src/`,
`public/`, `migrations/`, `package.json`, `wrangler.toml` with
placeholders), a `00-START-HERE.md` with the exact steps, a
`KEYS.md` saying which secret goes where, and the key files
themselves (chmod 600). The user pastes from the folder into their
own Worker; nothing is deployed for them and no key value ever
appears in chat. Build the folder with the USER'S keys, not with
keys generated for a throwaway deploy.

### L26. The vault already exists — use it, never rebuild it (second Muse)

The vault at `https://cf-d1-vault.hardeepwalia77.workers.dev` already
exists, its D1 already holds the encrypted keys, and its Worker
secrets (master verifier + DEK) are already set. **Do NOT redeploy
the Worker and do NOT touch its secrets. No fresh Worker, no fresh
D1, no fresh keys — nothing to add again.** The owner gives the
master secret from his MAIN account (the first Muse's
`vault-master-secret.txt`); he pastes the value himself, never
through chat. The second Muse is **owner-equal** (owner decision
2026-11-19): it holds the same master secret and unlocks for
itself. What the second Muse copies from the first Muse is ONLY the
master secret value + the vault URL. **No key files, and NOT the DEK
backup** — that is disaster recovery for the Worker itself; a second
Muse never needs it. Muse's mistake on 2026-11-19 was doing the
opposite: it deployed a FRESH vault (new Worker + D1 + fresh master
+ DEK + token) in the QwenPaw account without asking, then built a
paste-ready folder for a fresh deploy — all of it duplicate and
wrong, because the vault already existed. The first question is
always: does the vault already exist at a known URL? If yes, stop
— use it.

### L27. Each Muse/agent gets its OWN agent_id and token — never reuse pi's

Holding the master secret, the second Muse registers **its own new
agent_id** in the vault and receives its own request-only bearer
token. Never reuse agent `pi`'s token and never give the second
agent the first agent's identity. The master secret makes it an
admin; the agent token is still what day-to-day service requests
use. Grants last exactly 2 hours (`expires_at = opened_at + 7200`);
re-unlocking is routine, not an error. Correction to an earlier
message in this chat: the Pi-token SHA-256 I handed Rohan was for
the token generated for the WRONG (fresh QwenPaw) vault — it must
NOT be registered on the real vault. The real vault gets a fresh
agent_id + token made with the real master secret.

## Checklist to fold into SETUP-PROMPT.md §6 (Rules while you work)

- Re-read SETUP-PROMPT.md and COMPLETE-SETUP.md in full before any
  browser task or host step. A summary is not a read.
- The API key never creates anything. Browser first, key second.
- Sandbox name `pi` is part of the creation instruction, not a
  correction afterwards.
- `GET /tenants/<team>/servers` before asking whether a sandbox exists.
- `tunnels` list + `zones` list before creating any tunnel or record.
- Never touch a tunnel you did not create.
- If two sources disagree on a name or id, say so at once.
- When a step fails, stop, report the exact error and the fix. Do not
  work around it silently. (Already in the guide — this run proved why.)
