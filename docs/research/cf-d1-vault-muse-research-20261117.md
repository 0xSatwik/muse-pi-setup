# Muse-side research — Cloudflare Worker + D1 MCP vault (17 Nov 2026)

Done here in Muse via the combined search system (web.py), to debate against
Pi's report (session 01a1e68d-cab0-76ba-814a-c428035ad366).

## Verified facts

### 1. Pi supports remote MCP servers — YES (pi.dev MCP docs)
- `~/.pi/agent/mcp.json`, `mcpServers` entries. Transports: `stdio`,
  `streamable-http` (alias `http`, URL-only shorthand), legacy `sse`.
- Remote example: `{"transport": "streamable-http", "url": "https://.../mcp",
  "headers": {"Authorization": "Bearer <token>"}, "lifecycle": "lazy"}`.
  Also supports `auth: {type: "oauth"}` (OAuth 2.1 PKCE).
- Diagnostics redact Authorization headers / tokens in error output.
- CONSEQUENCE: the Worker-as-MCP-server plan is compatible with Pi as-is.
- CAVEAT: Pi's request-only Bearer token lives in mcp.json on the sandbox —
  the model could read it via bash (`cat ~/.pi/agent/mcp.json`). Bounded
  damage only: the token is tool-use-only and the Worker refuses execution
  without Muse's unlock. The token must never be the master secret.

### 2. Cloudflare Workers as a remote MCP server — YES (official docs)
- developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server:
  deploy to `https://<name>.<account>.workers.dev/mcp`, Streamable HTTP,
  with or without auth (Workers OAuth Provider for auth). Also
  blog.cloudflare.com "The next generation of MCP" (Aug 2026): stateless MCP
  server in a Worker.
- CONSEQUENCE: no custom protocol work needed; use the official pattern.

### 3. Free-tier limits — VERIFIED (Cloudflare docs)
- Workers Free: 100,000 requests/day, burst 1,000 req/10 min; Error 1027
  when exceeded; 10 ms CPU per request.
- D1 Free: 5,000,000 rows read/day, 100,000 rows written/day, 5 GB storage,
  10 databases (500 MB each). Since 2026-09-01 D1 ENFORCES daily query
  limits — queries fail when exceeded, so audit logging must stay light
  (don't log a D1 row per tool call; batch or keep the audit in the Worker
  log / a capped table).
- CONSEQUENCE: this use (a handful of tool calls a day) fits easily in free.

### 4. Field-level encryption in Workers — YES (WebCrypto)
- Workers runtime implements the full Web Crypto API (`crypto.subtle`),
  including AES-GCM. Precedent: secret.airat.top (Workers + D1, encrypted
  secrets, burn-after-reading).
- CONSEQUENCE: AES-GCM field-level encryption of keys in D1 is feasible.

## Open design points for the debate
- 2-hour unlock TTL state: in-memory cache does NOT survive Worker isolates.
  Options: Durable Object (check free-tier DO limits), KV with TTL, or a
  D1 `unlocks` table with expiry timestamps checked per request. Recommend
  D1-backed expiry (no extra service, survives restarts, revocable) unless
  Pi finds a cheaper DO/KV path inside free tier.
- Scoped unlocks: one unlock = one service (+ which labeled key, e.g.
  github-personal vs github-work). Enforce in the Worker, not by trust.
- The master secret: lives in Muse's Secure Vault only; used transiently
  for /unlock and admin calls. Never in Pi, never in D1 plaintext, never
  in Worker code.
- Residual risk to name honestly: Pi can misuse allowed tools inside an
  active window (e.g. commit anything to the allowed repo); the allow-list
  + 2h window + audit log are the boundary, not the model's goodwill.
  Cloudflare itself holds the keys (trust Cloudflare, not Altare, not the
  model). If the master secret leaks, everything unlocks.
