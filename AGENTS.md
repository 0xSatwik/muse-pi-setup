# AGENTS.md

> Copied from the author's own operating manual. The rules and lessons are
> the point; the `~/workspace/...` paths are examples from the author's
> setup — adapt them to wherever you put this repo.

Your operating manual for this workspace, written by you. Your main instructions cover how you work in general. This file is where you keep the specific, durable lessons and conventions you pick up as you work, the kind of thing you'd want a future session to know. It's not about the user (that goes in `USER.md` and your memory) or your personality (that's `SOUL.md`); it's about how you get work done here.

## Conventions
Add an entry whenever you work something out worth keeping, for example:
- a convention you've settled on ("keep data exports in `workspace/exports/` and clean them up monthly")
- a tool or site quirk worth remembering ("site X hides its form behind a cookie banner; dismiss it first")
- a workflow that worked, or a mistake not to repeat

It starts empty and is meant to grow slowly. Don't pad it; a short, accurate file beats a long, stale one.

## Altare Pi delegation (standing rule, 2026-11-17)
- Frequently delegate long-running / heavy / architecture work to Pi
  via `~/workspace/altare-pi-setup/pi-bridge/muse-pi.py` (ask / send+get)
  on Altare, or via `pi-api.py` over the Hoody `http-8765` URL on a
  Hoody computer. Reasons: token saving (Pi uses the user's custom APIs),
  extra intelligence (second model/opinion), better architecture (Pi
  double-checks designs). The Pi side (paths, models, sessions) is the
  same on both hosts; only how Muse reaches it changes.
- Models: xingchi/gpt-6-astra, xingchi/gpt-6.1-sol, tokenlab/DeepSeek-V4.1-Flash, moss/nex-n2.6, howtofix/deepSeek-v4.1-flash-1017-sg, 100milionseek/deepseek-v4.1-flash-free. Watcher runs in tmux `pi-bridge` on the box; restart it after a box restart.
- Sessions (standing rule, user choice 2026-11-17): ONE Pi session per topic, reuse by default — never a fresh session when a topic already has one. Registry: `~/workspace/altare-pi-setup/pi-bridge/pi-sessions.json`. Continue with `pi-api.py prompt --session <id>`; register new topics there. Compact when long; fresh start only if a session dies or gets confused. Prefer xingchi/gpt-6.1-sol for long sessions.

## Web research (standing rule, 2026-11-17; Worker added 2026-11-19)
- Always use the combined search/fetch system: `python3 ~/workspace/search/web.py research "q"` — TinyFish free via Monid + cf-search Worker (Bing, no key) + DuckDuckGo, then fetch top URLs. Skill: `~/workspace/custom-skills/web-research/SKILL.md`. Pi uses the same file at `/root/pi-bridge/search.py`. Never use paid Monid endpoints; never write API keys literally in files.
- cf-search Worker: `https://cf-search.akamithun-search.workers.dev/search` — Bing only, plain text, one line per result. Country-wise filtering works (setlang+cc); pagination does NOT work for web/news (Bing ignores `first=` in every form tested — page=2 returns the same results as page=1). Google News (503) and DuckDuckGo (202 bot-challenge) do NOT work from Cloudflare's network. Full docs: `docs/SEARCH-WORKER.md` and `cf-search-worker/llms.txt`.

## Cloudflare Tunnel — permanent URL (lessons, 2026-11-19)
- A named tunnel gives a permanent URL (`https://<name>.<domain>/admin`); a quick tunnel gives a random `trycloudflare.com` URL that changes on restart. Use the named tunnel; keep the quick tunnel only as a fallback until the permanent URL is verified loading.
- **DNS record MUST be proxied (orange cloud).** With `proxied: false` (DNS-only) the browser hits the tunnel address directly and gets `ERR_CONNECTION_RESET`. A tunnel hostname only works when Cloudflare's edge proxies it to the tunnel. DNS needs ~60s to propagate after the fix.
- **Never restart cloudflared inside its tmux session.** A tmux session closes when its main process exits, and cloudflared IS the main process. Always `tmux kill-session -t pi-tunnel` then `tmux new-session -d -s pi-tunnel 'cloudflared tunnel --config ... run'`.
- The CNAME to `<uuid>.cfargotunnel.com` only works inside the SAME Cloudflare account as the tunnel. The domain/zone must be in the tunnel's account.
- Full guide: `docs/TUNNEL.md`.

## Cloudflare-blocked sites (lesson, 2026-11-17 — user-taught)
- Symptom: Cloudflare 403 "Your request was blocked" on direct curl AND browser.open AND the cloud browser, even with no auth and even on the site root (e.g. numes.ai, trycloudflare.com). That means the VM's egress is blocked, NOT the key or credentials — the key is never even evaluated. Stop retrying direct requests; diagnose once (no-auth curl, site root, browser UA) and move to the ladder.
- Ladder, in order: (1) `web.py` TinyFish fetch/search — server-side, often gets pages direct fetch can't; (2) browser task — a fresh browser/route can clear the block (bot-challenge recovery moved the tab and the page loaded); (3) vault Worker `service_request` — the Worker runs on Cloudflare's own network and reaches blocked APIs (Numes /models returned 200 through it); (4) Pi sandbox egress, different network, last resort.
- Cloudflare's Markdown for Agents (`Accept: text/markdown`) and Web Bot Auth (`tag="web-bot-auth"` signed headers) are NOT bypasses — both need the destination site to opt in / allowlist the agent. Don't waste time on them for a blocking site.
- Never paste API keys into browser tasks or Pi prompts. Put the key in the vault, unlock it for Pi, and let Pi call it via `service_request` — Pi never sees the value.

## Pi Admin page + keys (2026-11-18)
- After setup, ALL key/model management goes through the Pi Admin page (gateway URL + `/admin`): provider keys (write-only — the API never returns a value), model add/edit with per-model context/output/reasoning/vision, Make default, Test, the Monid key, gateway restart. Console rituals are the fallback, not the default. Login is the opening password (SHA-256 in the box's `gateway.env` as `PI_ADMIN_PASS_SHA256`) or the gateway token; 5 failed logins lock it for 10 minutes.
- Never paste keys in chat. Keys enter via the Admin page, Muse's secure connector pages, or stdin (`pi-api.py setkey` / `--key-stdin`) only — never as arguments, never in a Pi prompt, never in a browser task.
- Search is the combined system ONLY (TinyFish free endpoints via Monid + DuckDuckGo + X via FxEmbed) — never paid Monid endpoints. The Monid leg is load-bearing: DuckDuckGo returns `[]` from datacenter egress, so no Monid key on a side means no search results on that side.
- Hallmark (`nutlope/hallmark`) is the default design skill on both sides — Muse: `~/.agents/skills/hallmark` (+ `~/workspace/custom-skills/hallmark`); Pi: `/root/.pi/agent/skills/hallmark`. The `npx skills add` route fails in this environment; install by cloning `nutlope/hallmark` and copying its `skills/hallmark/` folder (see COMPLETE-SETUP.md §9).
