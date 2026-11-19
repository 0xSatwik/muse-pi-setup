# cf-search — Bing search Worker (search-only)

A dedicated Cloudflare Worker that returns Bing web/image/video/news
results as clean plain text, built for AI agents (Pi, Muse) that need
fast, free, filterable search without an API key. It is the second leg
of the combined search in `web.py`, alongside TinyFish via Monid.

- Live URL: `https://cf-search.akamithun-search.workers.dev`
- No auth, no key, no sign-in. Free tier Worker.
- One endpoint: `GET/POST /search`. Health: `GET /health` returns
  `ok cf-search web images videos news`.
- Source: `cf-search-worker/` in this repo is NOT included — the Worker
  lives in the author's workspace (`~/workspace/cf-search-worker/`),
  with full docs in its `llms.txt` / `llm.txt`. Deploy it with your own
  Cloudflare account (see below) and set `CF_SEARCH_URL` to your URL.

## Response format (single format, always)

Plain text only. No JSON, no format parameter. One line per result:

```
Search: bitcoin (web, 3 results)
1. Bitcoin price today - https://coinmarketcap.com/currencies/bitcoin/
2. BTC USD — Bitcoin Price and Chart — TradingView - https://www.tradingview.com/symbols/BTCUSD/
3. Bitcoin - Open source P2P money - https://bitcoin.org/
```

Title + URL only is the lowest-token format (measured ~23 tokens/result
vs ~106 for full JSON). Snippets are dropped on purpose — the title +
URL is enough to pick which page to fetch.

## Filters

- `q` (required), `vertical` (web|images|videos|news), `count` (1-50),
  `page`, `offset`/`first`, `setlang`/`lang`, `cc`/`region`/`country`,
  `mkt`, `safesearch` (off|moderate|strict), `time`/`time_range`
  (day|week|month|year). Images add size/color/imgtype/face/license.
  Videos add duration/resolution. News adds sort.

## What works and what does not (verified 2026-11-19)

- **Country-wise filtering WORKS.** Same query with `setlang=en-IN&cc=IN`
  vs `setlang=en-US&cc=US` gives genuinely different results (verified
  with `cricket`: India leads with Cricinfo/Cricbuzz, USA leads with
  Cricket Wireless).
- **Pagination does NOT work for web/news.** Bing ignores the `first`
  offset in every form tested: RSS `first`, HTML `first`, `FORM=PERE`,
  the `FPIG` session token, cookies, cookies+FPIG+FORM together, and
  `count=50`. Page 2 returns the identical results as page 1. Bing only
  paginates for a real browser session. To get more results, vary the
  query, country, language, or time filter instead.
- **Web/news max 10 per query.** `count=50` still gives 10.
- **Google News does NOT work.** A `/gnews` endpoint was built and
  removed: Google News RSS returns 503 to Cloudflare egress IPs (it
  works from a normal VM directly). Bing News via `/search vertical=news`
  is the working news source.
- **DuckDuckGo does NOT work.** Tested twice: via the vault Worker
  (lite, html, main all `upstream_failed` after ~20s) and via a live
  `/ddg` endpoint in this Worker (html.duckduckgo.com returned HTTP 202,
  a bot-challenge page, 0 results). GitHub repos that scrape DuckDuckGo
  from Workers exist, but from this Worker's Cloudflare IPs DuckDuckGo
  serves a bot-challenge, not results.
- **Google and SearxNG also fail** from the Worker. Bing is the only
  working search source here.

## Deploy your own

```bash
# In Cloudflare dashboard or API: create a Worker, paste src/index.js,
# deploy. Then set the URL for web.py:
export CF_SEARCH_URL="https://<your-worker>.<your-subdomain>.workers.dev"
```

The Worker needs no secrets, no KV, no D1 — it is a plain fetch-and-parse
bridge. It sets a 20s fetch timeout to Bing and a `Cache-Control:
no-store` header. CORS is open.

## Why this exists

Public SearxNG instances rate-limit and bot-block datacenter egress
(0/100 and 0/100 in two load tests). TinyFish via Monid works but is a
third-party API with daily caps. The vault Worker proved Cloudflare's
network can reach Bing directly (30/30 at 15/min, 28/30 with results,
~440ms). This dedicated Worker turns that into a clean search API for Pi,
with every Bing filter.
