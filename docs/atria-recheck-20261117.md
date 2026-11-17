# Atria Dawn — free-access re-check (fresh, 17 Nov 2026)

Scope: re-verify live, from scratch, whether any **free hosted route** to **Atria Dawn** (`internlm/Atria-Dawn-Preview`, a.k.a. `atria-dawn-preview`) exists today. Prior verdict (16 Nov): official ~100M free-token promo at `api.atria-asi.ai` had ended and the host returned 503 on all paths.

**VERDICT: NO free Atria Dawn route is usable today without signup, and no route at all could be used without signup/payment.**

- The official international API is still dead (503 everywhere).
- Infron removed Atria Dawn from its free list (only 1 free model left, and it's not Atria).
- AntSeed has **no Atria-Dawn on its network at all** today, and its one "free" model is **stakers-only** (requires acquiring + staking ANTS tokens = payment). Live-tested.
- Duanyan/InkStone (书生·端砚) Token Plan is the only place still advertising 0-cost Atria-Dawn-Preview — but it requires account registration (+ phone binding), so it could not be tested and is not confirmed live today.
- OpenRouter: no Atria. HuggingFace: weights only (MIT), no hosted inference provider.

---

## 1) api.atria-asi.ai — still dead (probed live today, 17 Nov 2026)

Probed `GET /`, `/v1/models`, `/health`, `/docs`, `/v1/chat/completions`:

```
HTTP 503 Service Temporarily Unavailable (server: alb) on ALL paths
```

Same failure mode as 16 Nov. The marketing root `https://atria-asi.ai` is up (HTTP 200, "Atria Dawn"), so only the API/console host is down. No announcement text is served on the 503 page.

## 2) New free hosted routes — checked live today

### Infron (`infron.ai` / `api.infron.ai`) — free program exists, but Atria is GONE
- Site is up (Framer page published 2026-11-14). `GET https://api.infron.ai/v1/models` → HTTP 200, **497 models, zero matching "atria"/"dawn"**.
- Only free model today: `qwen/qwen3.8-27b:free` (documented $0/token, "never deducts from your credit balance", https://infron.ai/docs/overview/free-models).
- Their own X promos advertised free Atria: @InfronAI Oct 30 ("5 models. $0/$0 … Atria: Dawn Preview", x.com/InfronAI/status/2116175797019168907) and Nov 3 ("FREE on Infron: Atria Dawn Preview", status/2117421345059590273 → `infron.ai/models/internlm/atria-dawn-preview:free`). That model page today returns a generic page with no Atria content → listing removed between 3 Nov and today.
- API requires a key: `POST /v1/chat/completions` with no key → 401 "No token provided"; with dummy key → 401 "The token status is not available". Signup required → not tested further.
- Historical catch (X @calbuldelis69, Oct 31, status/2116454300671230304): Infron free tier required a **$5 minimum balance** for anti-abuse (free usage doesn't consume it).

### AntSeed (`antseed.com`) — live-tested; NO Atria today, and "free" is stakers-only
- AntSeed is a P2P inference market; you run a local gateway/buyer proxy (no signup). Their X posts (Nov 6 status/2118688654834983246, Nov 10 status/2120286631089319947) listed "Atria-Dawn" among "all free" models.
- Live test today (installed `@antseed/cli` v0.1.250 via npm, ran `antseed buyer start` locally, no account created):
  - Connected to the P2P network; local catalog: **305 models, none matching atria/dawn**.
  - `antseed network browse --services --top 400 --json`: 93 peers, **1,324 distinct services, zero atria/dawn**.
  - Tested their one currently-free model `deepseek-v4.1-flash-free` with a real chat call (0 balance, placeholder key):
    **HTTP 429** `free_tier_exhausted` — "This model is free only for buyers staked on this seller. Stake ANTS in its pool to use it: 500 ANTS locked for a year gives 20 free requests per day." (`stakersOnly: true`, my limit: 0).
  - ⇒ "Free" on AntSeed means **stake ANTS (buy tokens) or nothing** → payment required; and Atria-Dawn isn't offered by any seller right now anyway.

### Duanyan / 书生·端砚 (Intern "InkStone") Token Plan (`discovery.intern-ai.org.cn`) — most promising, but signup-gated (NOT tested)
- Console is **up** today (HTTP 200 at `https://discovery.intern-ai.org.cn/token-plan/home`). It is the official China hosted-access route listed in the model card (github of the card: huggingface.co/internlm/Atria-Dawn-Preview → "Deployment & Online Access" table).
- X reports: @xiangxiang103 (Oct 4, status/2106758713021534319) and @Pengchenop (Oct 5, status/2107084828546159026): new users get a **monthly free base pack of 10 墨点 ("ink points")**; official billing says 1 墨点 offsets up to 50M tokens (≈ up to 500M tokens/month); **Atria-Dawn-Preview is one of 3 own models at limited-time 0 墨点** (free, no deduction); OpenAI- and Anthropic-compatible API. Repeated Nov 9 by @jhl880617 (status/2119648747365736778).
- Caveats (X @niumage888, Nov 15, status/2121971332489621615): the official page currently only says "free monthly tokens during test period"; the big token numbers circulate from directory sites; test period may end without notice. @DongTao57263 (Oct 5): the platform reportedly blocks non-China IPs.
- No public unauthenticated API (SPA shell only; `/api/...` guesses return the HTML app). Model list / pricing / API base URL are visible only after login.
- **Not tested: registration (+ phone number binding) is required. Per instructions, I did not sign up.**

### OpenRouter — no
`GET https://openrouter.ai/api/v1/models` (live, no key): 469 models, zero "atria".

### HuggingFace — weights only, no free hosted inference
- Models: `internlm/Atria-Dawn-Preview` (MIT, created 2026-09-11, ~2.3k downloads), `-FP8`, `-Ascend-w8a8`, community MLX/quants.
- `inferenceProviderMapping` = `{}` → **no HF inference provider hosts it**; using it means self-hosting (free software, paid compute).

## 3) Live test summary
Only AntSeed could be exercised end-to-end without signup — done (local P2P buyer, no account). Result: no Atria-Dawn available; its free tier is stakers-only (payment). Infron (401 without key) and Duanyan (login wall) were probed but not called, exactly because that would require signup/payment.

## Best available path today (honest ranking)
1. **Duanyan/InkStone Token Plan** — the only route still advertising 0-cost Atria-Dawn-Preview. Steps: (1) open `https://discovery.intern-ai.org.cn/token-plan/home`; (2) register an account and bind a phone number (mainland-China number reportedly needed; overseas IPs may be blocked); (3) claim the monthly free 墨点 in the console; (4) create an API key in the console; (5) point any OpenAI- or Anthropic-compatible client at the console's API base URL with that key and call model `Atria-Dawn-Preview` (0-墨点 = no balance consumed while the test-period promo lasts). Caveats: promo is "test period" only, quotas reset monthly, and availability was last corroborated by posts from Nov 9 — verify in-console after login.
2. **Self-host the MIT weights** from `huggingface.co/internlm/Atria-Dawn-Preview` (or the FP8 build) — no API cost, but you need serious GPU capacity (community reports FP8 files alone ≈ 755 GB).
3. **Wait for `api.atria-asi.ai` to return** — still 503 on all paths as of today; the earlier ~100M free-token promo is over per the 16 Nov verdict.

## Evidence index (all accessed 17 Nov 2026)
- 503 probes: `api.atria-asi.ai/{,/v1/models,/health,/docs,/v1/chat/completions}`; `atria-asi.ai` root 200.
- Infron: `api.infron.ai/v1/models` (497 models, no atria; 1 free: qwen/qwen3.8-27b:free); `infron.ai/docs/overview/free-models`; 401s on chat/completions; X 2116175797019168907 (Oct 30), 2117421345059590273 (Nov 3), 2116454300671230304 (Oct 31, $5 min balance).
- AntSeed: `antseed.com/docs/{quickstart,api,staked-free-tier}`; live local buyer test (models list, network browse JSON, 429 free_tier_exhausted with `stakersOnly:true`); X 2118688654834983246 (Nov 6), 2120286631089319947 (Nov 10).
- Duanyan: `discovery.intern-ai.org.cn/token-plan/home` 200; X 2106758713021534319 (Oct 4), 2107084828546159026 (Oct 5), 2119648747365736778 (Nov 9), 2115083453226201453 (Oct 27), 2121971332489621615 (Nov 15 caveat).
- OpenRouter: `openrouter.ai/api/v1/models` (no atria). HuggingFace: `huggingface.co/api/models?search=atria-dawn`, model card + empty `inferenceProviderMapping`.
