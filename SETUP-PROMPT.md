# SETUP PROMPT — paste this to your Muse

Copy everything below the line into a chat with your Muse. It will ask
you the questions in section 1, then set the whole thing up for you
using the scripts and guide in this repo. You stay in the loop only for
the steps that need you: the Altare console, and the Tailscale approvals.

---

You are setting up **Muse controlling Pi on an Altare sandbox** for me,
from the repo `https://github.com/0xSatwik/muse-pi-setup` (public, MIT).
Follow the repo's `README.md` as the guide and use its scripts
(`setup-muse.sh` on my VM, `setup-sandbox.sh` on the sandbox). Do not
improvise the setup — the repo is the source of truth, and its scripts
are already tested. If a script step fails, stop, tell me the exact
error and the fix, and do not work around it silently.

## 1. Ask me these questions FIRST, before doing anything

Ask them all in one message, then wait for my answers:

1. **Altare:** Do you have an Altare account? (Free tier, no card.) If
   you have not created the sandbox yet, I cannot create it for you —
   team API tokens cannot create sandboxes (403
   `TOKEN_ROUTE_NOT_ALLOWED` by design). Create it in the Altare web
   console with the full free pool (6 GiB RAM, 150% CPU, 10 GiB disk),
   any region, and add your SSH public key. Then give me the **team ID**
   and **server ID** (console → server details).
2. **Tailscale:** Do you have a Tailscale account? (Free personal
   plan.) You will need to approve three things later: my VM's device,
   the sandbox device, and the first connection to the sandbox's
   tailnet IP. Nothing else is needed from you for Tailscale.
3. **Models:** Which of these do you want? (Give me the API key for
   each one you want; keys go to the sandbox only.)
   - xingchi gpt-6-astra + gpt-6.1-sol (https://api.xingchiapi.com/v1)
   - tokenlab DeepSeek-V4.1-Flash (https://api.tokenlab.amd.com/v1)
   - moss nex-n2.6 (https://api.mosi.cn/v1)
   - howtofix deepSeek-v4.1-flash-1017-sg (https://api.howtofix.id/v1)
   - 100milionseek deepseek-v4.1-flash-free (https://100milionseek.top/v1)
   You can add more later with `pi-api.py add-model`. Any
   OpenAI-compatible provider works.
4. **Search (optional):** Do you have a Monid key for free search?
   Without it, web search still works through the DuckDuckGo fallback
   but the TinyFish path is off. If you have one, paste it.
5. **Secrets vault (optional):** Do you also want the Cloudflare
   Worker + D1 secrets vault so Pi can call GitHub and other APIs
   without ever seeing the key? It is a separate repo
   (`0xSatwik/cf-d1-vault`) with its own guide — say yes and I will do
   it after this setup, or no and we skip it.
6. **Sandbox device name:** What should the sandbox be called on your
   tailnet? Default is `pi-altare`.

Do not start the setup until I have answered. If I skip a question,
use the default and tell me what you assumed.

## 2. What to save, and where (never break these rules)

- **Gateway token:** generate one fresh random token
  (`python3 -c "import secrets; print(secrets.token_hex(32))"`).
  Save it to `gateway-token.txt` next to `pi-api.py` (chmod 600) and
  to `/root/pi-bridge/gateway.env` on the sandbox as
  `PI_GATEWAY_TOKEN=<token>` (chmod 600). Never print it in chat
  beyond the one time you show it to me, never put it in the repo.
- **Model keys:** sandbox only — `/root/pi-bridge/provider-keys.env`
  (chmod 600, `KEY=value` lines) AND `export KEY='value'` lines in
  `/root/.profile` and `/root/.bashrc`. The gateway reads
  `provider-keys.env` directly; the watcher and interactive Pi read
  `/root/.profile`. Never put a real key in `models.json` (it holds
  `$VAR` placeholders only), never in a file on my VM, never in the
  repo, never in a Pi prompt, never in a browser task.
- **Monid key:** `~/.config/monid/credentials.yaml` on my VM
  (chmod 600, format `key: "<value>"` then `label: main`) and
  `$MONID_API_KEY` on the sandbox.
- **Tailnet URL:** `tailnet-url.txt` next to `pi-api.py`, one line:
  `http://<sandbox-tailnet-ip>:8765`.
- **Altare IDs:** environment variables `ALTARE_TEAM` and
  `ALTARE_SERVER` only — never in a file that could be shared.
- **Pi sessions:** one session per topic, reuse by default. Keep the
  registry (`pi-sessions.json`) current. Never start a fresh session
  when a topic already has one.

## 3. Browser steps (the only steps that need a browser)

Do these in the browser, in this order. Everything else is scripts.

1. **Altare console:** log in, create the sandbox (see question 1),
   open the web console terminal for it. The console sometimes shows
   the server as "Offline" when it is alive — trust the terminal, not
   the badge. Direct SSH from my VM is blocked by its egress proxy,
   so do not try SSH; use the web console and the Files API.
2. **Tailscale approvals (three of them, all by the user):**
   a. My VM joins the tailnet as device `muse` and prints an approval
      link — only the user can approve it. The same approval is also
      at login.tailscale.com/admin/machines.
   b. The sandbox joins as the device name from question 6 — approve
      it the same way.
   c. The first request to a new tailnet address needs one more
      approval — approve it once when it appears, then retry.
3. **Nothing else needs the browser.** Cloning this repo is public
   (no login). Monid signup is a website if you need a key.

## 4. Steps, in order

1. Clone this repo and run `./setup-muse.sh` on my VM. It installs
   the bridge files, the search tool and skill, generates the gateway
   token, builds the sandbox bundle, and (if `ALTARE_TEAM` and
   `ALTARE_SERVER` are set) uploads the bundle to `/root/work/setup/`
   on the sandbox. If the upload is skipped, it prints the exact
   upload commands — run them.
2. In the Altare web console terminal (as root), run:
   `bash /root/work/setup/setup-sandbox.sh`
   It installs Node 22 + Pi 1.5.2 + Tailscale, places the bundle,
   starts everything in tmux, and prints the sandbox tailnet IP. When
   it prints a Tailscale login URL, open it and approve the device.
3. Take the tailnet IP it printed and re-run:
   `./setup-muse.sh --tailnet <ip>`
   That writes `tailnet-url.txt` and runs the health check.
4. Verify (all must pass):
   - `pi-api.py health` → `{"ok": true}`
   - `pi-api.py models` → all six models (or however many you added)
   - `pi-api.py prompt "Say OK" --model xingchi/gpt-6.1-sol` → `OK`
   - `muse-pi.py ask --model moss/nex-n2.6 --prompt "Say OK"` → `OK`
     (this is the fallback path — if it works, the bridge works)
   - `python3 search/web.py research "pi agent"` → web results
   If a check fails, stop and tell me the exact failure and the fix.
   Do not declare the setup done until every check passes.

## 5. Tailscale — the issues we already hit, so you do not hit them

Read this before touching Tailscale. Every one of these cost real time:

- **No TUN device.** Altare sandboxes have no `/dev/net/` at all, and
  no Docker, no kernel modules, no systemd. The daemon must run in
  userspace mode: `tailscaled --tun=userspace-networking
  --state=/root/tailscale/tailscaled.state
  --socket=/root/tailscale/tailscaled.sock
  --config=/root/tailscale/tailscaled.conf`, in tmux session
  `tailscaled`. Do not try the default TUN mode — it cannot work here.
- **Fake root.** The sandbox tells programs they are uid 0, but the
  kernel truth is uid 999. Tailscale's LocalAPI then refuses mutating
  calls. The fix is the config file `/root/tailscale/tailscaled.conf`
  with `{"Version": "alpha0", "Locked": false, "OperatorUser":
  "container"}`, plus `tailscale up --operator=container
  --hostname=<name>`. Without `OperatorUser`, login fails.
- **Custom socket.** This daemon does not listen on the default
  socket. Plain `tailscale status` fails with "connection refused".
  Every `tailscale` command on the sandbox must pass
  `--socket=/root/tailscale/tailscaled.sock`. This is the single most
  likely thing to get wrong.
- **No Tailscale Serve needed.** The gateway listens on 127.0.0.1:8765
  only, and in userspace mode the daemon forwards incoming tailnet
  connections to the same port on localhost — so the gateway is
  reachable at the tailnet IP with no serve config.
- **Start order after a sandbox restart:** tailscaled → Tailscale
  login/status → gateway → watcher → cloudflared tunnel (optional).
  Restart all four tmux sessions (`tailscaled`, `pi-gateway`,
  `pi-bridge`, `pi-tunnel`); there is no systemd to do it for you.
- **Muse VM side:** the VM has a built-in Tailscale client
  (`/opt/hatch/bin/tailscale`, device name `muse`). Do not install an
  upstream client. Joining prints an approval link only the user can
  approve.
- **The :3130 proxy.** From the Muse VM, a direct connection to a
  tailnet IP returns empty. `pi-api.py` routes tailnet URLs through
  the VM's tunnel proxy on port 3130 (derived from `HTTPS_PROXY`,
  overridable with `PI_GATEWAY_PROXY`). Never "fix" this by removing
  the proxy logic, and never test the gateway with plain `curl` to the
  tailnet IP — test with `pi-api.py health`.
- **Approvals.** Three user approvals (section 3). The first request
  to a new tailnet address needs its own approval even after the
  device is approved.

## 6. Rules while you work

- Report real progress; do not go silent during long steps. If a step
  takes more than a few minutes, say where it is.
- Verify before trusting: a check counts only when its command
  returns the expected output, not when it looks right.
- Never paste a key into a Pi prompt or a browser task. Keys go to the
  sandbox through the bundle/`setkey`/stdin paths only.
- Never commit a secret to the repo. The repo's `.gitignore` blocks
  the secret files; keep it that way.
- Prefer xingchi/gpt-6.1-sol for long Pi work. moss dies empty on long
  sessions. If Pi returns empty twice on a task, have it write results
  to a file and read the file — and if a session goes empty twice,
  start a fresh session for that topic.
- One Pi session per topic; reuse, compact when long, fresh start only
  if a session dies or gets confused.
- When you are done, tell me the tailnet IP, the gateway health
  result, and the model list — and nothing else I did not ask for.
