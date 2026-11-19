---
name: web-research
description: Best search and fetch system for Muse and Pi — TinyFish free via Monid + cf-search Worker (Bing) + DuckDuckGo combined for maximum URLs, TinyFish free fetch, and X/Bluesky/TikTok/Instagram/Threads/Mastodon via FxEmbed. Use for ANY web research, X search, or fetching pages. Always use the combined `research` command, never a single source.
---

# Web Research — the only search/fetch system to use

Muse and Pi must ALWAYS use this system for web research. Never use a
single search engine, never curl a search page by hand, never guess.

## The tool

Muse: `python3 ~/workspace/search/web.py`
Pi (on Altare sandbox): `python3 /root/pi-bridge/search.py` (same file)

## Combined research — default for every research question

```
python3 web.py research "your question" --pages 2 --fetch-top 5
```

What it does, in one call (code-mode style — 1 tool call, not 6-8):
1. **Web search, three engines, deduped** — TinyFish `/free/search`
   via Monid ($0) + cf-search Worker (Bing, no key) + DuckDuckGo Lite
   (no key). Maximum URLs.
2. **X search** — FxEmbed `/ai/2/ask?q=&pages=2`, merged Markdown pack.
3. **Fetch top 5 URLs** — TinyFish `/free/fetch` ($0, clean Markdown),
   fallback plain curl.

Use `research` for anything that needs real data. Use the single
commands below only when you need just one piece.

## Web search / fetch

```
python3 web.py search "query" [--purpose "what the results are for"]
python3 web.py search-cf "query" [--vertical web|images|videos|news] [--count 10] [--cc IN] [--setlang en-IN] [--time week]
python3 web.py fetch https://example.com [https://...]   # up to 10 URLs
python3 web.py search-ddg "query"   # DuckDuckGo only, fallback
```

- TinyFish free: search 12,000/day, 30/min, 500/hr; fetch 1,000 URLs/day,
  150 URLs/min. Via Monid API `POST /v1/run` provider `tinyfish`,
  endpoints `/free/search` (queryParams: query, purpose, location,
  language, domain_type web|news|research_paper, recency_minutes)
  and `/free/fetch` (body: urls[1-10], format markdown|html|json).
  Paid endpoints `/search` / `/fetch` exist — NEVER use them, free
  ones are $0. Monid balance is $1; free calls cost $0.
- cf-search Worker (Bing, no key): `GET /search?q=...` at
  `https://cf-search.akamithun-search.workers.dev` (override with
  `CF_SEARCH_URL`). Plain text, one line per result: `N. Title - URL`.
  Filters: `vertical` (web|images|videos|news), `count` (1-50),
  `setlang`/`lang`, `cc`/`region`/`country`, `mkt`, `safesearch`,
  `time`/`time_range` (day|week|month|year), images add size/color/
  imgtype/face/license, videos add duration/resolution, news adds sort.
  Limits (verified 2026-11-19): web/news max 10 per query; pagination
  does NOT work (Bing ignores `first=` in every form tested — page=2
  returns the same results as page=1); country-wise filtering DOES work
  (setlang+cc change the results). Google News and DuckDuckGo do NOT
  work from Cloudflare's network (503 / 202 bot-challenge). Bing only.
  Full docs: `cf-search-worker/llms.txt` in this repo (or
  `~/workspace/cf-search-worker/llms.txt` on the author's machine).
- DuckDuckGo Lite: `https://lite.duckduckgo.com/lite/?q=...`, parse
  `class='result-link'` links, decode the `uddg=` param. No key.
  Flaky under rapid repeats (rate-limits) — that's why it's the
  fallback, not the primary. Space out calls.
  NOTE: DuckDuckGo works from a normal VM but does NOT work from
  Cloudflare's network (202 bot-challenge) — so the Worker can't use it.
- Monid key: from `~/.config/monid/credentials.yaml` (label `main`,
  chmod 600) or `$MONID_API_KEY`. NEVER write the literal key in a
  file, in chat, or in memory. On the Pi sandbox it lives as an env
  export in `/root/.profile`, same as the other API keys.

## X / social search — FxEmbed, no key

Base: `https://fixtweet.twapiworker.workers.dev`
(clone: `https://fixtweet-2.twapiworker.workers.dev` — fail over on flake)
**User-Agent header is MANDATORY** on every `/api` and `/ai` call
(e.g. `Muse/1.0`); missing UA = HTTP 401. Full manual:
`https://fixtweet.twapiworker.workers.dev/llms.txt`

```
python3 web.py xsearch "Pi coding agent" [--pages 3]   # /ai/2/ask, merged pack
python3 web.py xpost https://x.com/jack/status/20  # any post URL, or just the id
python3 web.py xprofile <handle>                        # X profile
python3 web.py xtrends                                   # X trends
```

Direct endpoints (when you need JSON / deep walks):
- Single post: `GET /api/2/status/{id}` (JSON) or `/ai/2/status/{id}` (Markdown)
- Thread: `/api/2/thread/{id}` | `/ai/2/thread/{id}`
- Conversation: `/api/2/conversation/{id}?ranking_mode=likes|recency`
- Profile: `/api/2/profile/{handle}` (+ `/statuses`, `/media`, `/search?q=`)
- Quotes/reposts: `/api/2/status/{id}/{quotes|reposts}?count=&cursor=`
- Search JSON: `GET /api/2/search?q=&feed=latest|top|media&count=50&fast=1`
  — follow `cursor.bottom` until 404. **500 mid-walk = retry the SAME
  request after ~30s; 404 = genuinely exhausted.** `fast=1` = stubs
  only, no stats/media. X operators pass through
  (`from:`, `filter:`, `lang:`, `since:`, `until:`, `min_faves:`).
- Universal post/profile: `GET /ai/2/post?url=<any supported URL>`
  — X, Bluesky, TikTok, Instagram, Threads, Mastodon, any of them.
- Bluesky: `/blueskyapi/2/...` + `/ai/2/bsky/...` (rkey = post id from
  a statuses call). TikTok: `/tiktok/api/{id}`, `/2/tiktok/...`.
  Instagram: `/instagram/api/{shortcode}`. Threads: `/atmosphere/2/threads/...`.
  Mastodon: `/atmosphere/2/mastodon/{domain}/...`.
- RSS: `/twitter/{handle}/feed.xml` (poll with `?since=<unix-sec>`;
  204 = nothing new). Trends/typeahead: `/api/2/trends`, `/api/2/typeahead?q=`.
- Limits: no Reddit/Facebook/YouTube. No TikTok comments/search.
  `?lang=` is accepted but translation is a NO-OP here. Single-post
  answers can flake per request — retry once or try the other base.

## Rules

1. **Always `research` first** for a research question. One combined
   call beats many single-source calls, in tokens and in coverage.
2. **Maximum URLs**: merge TinyFish + cf-search Worker + DuckDuckGo + X
   links, dedupe, then fetch the top 5-10. Never stop at the first 3 results.
3. **Never use paid Monid/TinyFish endpoints** (`/search`, `/fetch`
   without `/free/`). Free tiers cover everything here.
4. **Never paste API keys** in chat, files, or model output. Keys live
   in their own credential stores only.
5. **Cite sources**: every claim from research gets its URL.
6. **Bing pagination does not work** — do not call `page=2` expecting
   new results. Vary the query, country, language, or time filter instead.
