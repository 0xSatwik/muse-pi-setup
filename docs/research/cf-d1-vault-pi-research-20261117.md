# Cloudflare D1 vault + Worker MCP gateway: final debate report

17 November 2026. Recovered Pi research reconciled with Muse’s independent report. Design recommendation; no deployment performed.

## Verdict and ONE recommended plan

**Adopt a stateless Streamable HTTP MCP server on Workers Free, AES-256-GCM key rows in D1, a separate data-encryption key (DEK) in a Worker secret, and D1-backed authorization grants lasting exactly two hours.** Pi holds only the Worker URL and a random request-only bearer token. Muse alone holds the administrative master secret; the Worker stores only its verifier. Every upstream operation runs inside the Worker. An unlock binds **agent token + service + exact labeled key + allowed operations/resources**, never the whole vault.

The bearer in Pi’s `mcp.json` authenticates requests but cannot unlock, renew, administer, or retrieve keys. Its effective access is the intersection of its policy and an unexpired server-side grant. Once the grant expires, the same bearer is powerless for that service/key until Pi asks Muse and Muse explicitly unlocks again. No sliding renewal, client-clock trust, or automatic refresh.

Choose **D1 expiry checks on every operation, primary reads, and no positive authorization cache**. No KV, Durable Objects, OAuth service, paid plan, or VM is required. Serve an optional manual-entry page from the Worker; Pages Free is optional. Keep audits small and bounded. Classic and fine-grained GitHub PATs are equally supported, with no token-type preference.

## Debate: what survives scrutiny

| Issue | Challenge and evidence | Converged decision |
|---|---|---|
| Pi compatibility | Muse says legacy SSE is supported and illustrates `transport`, `lifecycle`, and `auth`. The installed Pi 1.5.2 `docs/mcp.md` explicitly rejects `sse`; it documents `url`, optional `type`, `headers`, and `oauth`. Local version documentation is stronger evidence for this installation. | Use URL-based Streamable HTTP `/mcp`, with the documented bearer header. |
| Audit cost | Muse says not to write one D1 row per call. The inherited D1 quota is 100,000 rows written/day: 200 compact call rows/day is inexpensive. Batching saves round trips but does not erase billed row writes; indexes also consume writes. Worker logs are not automatically safer. | Log unlock/revoke/admin events and write operations; sample successful reads, cap retention and daily volume. Never log request bodies or keys. |
| Expiry storage | Both favor D1. Pi’s earlier “instant revocation everywhere” claim was too broad: caches, replica reads, and already-dispatched calls undermine it. | Read authorization from the primary without a validity cache; revoke blocks subsequent admissions, not already-sent upstream calls. |
| Secret placement | “Master secret only with Muse” does not require sending it into Worker storage. A verifier suffices. The DEK is a different secret and must be available to the Worker for reliable decryption across isolates. | Muse retains raw master; Worker secret holds its SHA-256 verifier and an independent DEK. Unlock controls authorization, not whether the runtime possesses the DEK. |
| Free-tier certainty | Prior Pi notes contained contradictory DO duration arithmetic and unsupported latency/CPU estimates. Muse’s 1,000 requests/10-minute burst figure lacks supporting source text in the supplied report. | Do not rely on that burst figure or CPU guesses. DO is viable but unnecessary; measure Worker CPU before acceptance. |

Evidence basis: the old session contains fetched Cloudflare/GitHub documentation and local Pi documentation, plus failed search attempts and repeated unsaved drafts. Muse supplies the D1 enforcement date, **2026-09-01**, which is accepted as a required operating constraint here; its exact date was not independently re-probed in this recovery. Citations below identify authoritative reference pages, not new live verification. Speculative alternative-product prices from the old drafts are excluded.

## Threat model and honest boundary

Protect upstream keys from the agent model, Pi’s filesystem/environment, transcripts, and theft of a D1 export alone. Trust the deployed Worker code, its deployment pipeline, Cloudflare runtime/control plane, and Muse’s administration environment. Pi may be malicious or prompt-injected and may read its own request token. Treat that bearer as extractable.

Two shapes both hide upstream credentials if implemented correctly: (a) Pi calls the Worker with restricted authority; (b) Muse calls the Worker and returns results to Pi. Shape (b) permits review of each operation but adds orchestration and latency. The chosen shape is **direct Pi-to-Worker MCP execution with Muse-controlled scoped sessions**, not per-action Muse mediation. Earlier drafts calling this “strict Shape B” were misleading.

During an active grant, compromised Pi can misuse every permitted operation and read every permitted result. A two-hour window limits credential use, not the lifetime of harm: a malicious commit, disclosed document, or created upstream credential can survive expiry. Exclude credential creation, permission changes, workflow edits, deploy control, and similar persistence mechanisms unless deliberately required. Token secrecy does not make broad write access safe.

A stolen Pi bearer has the same bounded authority during grants bound to that bearer. A D1 reader sees ciphertext and metadata. A D1 writer can tamper with authorization rows: field encryption does **not** protect session integrity from database write compromise. Cloudflare deploy control can replace code and extract secrets; the gateway must never expose its own deployment/D1 administration privileges through Pi’s tools. Source-code disclosure alone does not disclose runtime secrets.

“No keys to the model” is an architectural property under these trust assumptions, not an absolute guarantee against arbitrary Worker compromise or credentials already present in upstream content. Enforce Worker-only API access through Pi host/tool network restrictions if “never calls APIs directly” must be a security boundary: MCP configuration alone cannot prevent bash/network bypasses.

## D1 encryption

D1’s automatic encryption at rest uses AES-256, with GCM preferred, and Cloudflare-managed keys; it does not stop an authorized SQL reader. Add application field encryption using Worker WebCrypto `AES-GCM`: independent random 256-bit DEK, fresh random 96-bit nonce on **every** encryption, 128-bit authentication tag, and authenticated additional data binding immutable key ID, service, label, and encryption version. Persist ciphertext/tag, nonce, and version; never plaintext.

Keep the DEK in a Worker secret, separate from the Muse master verifier and D1. Plaintext exists transiently in Worker memory and the upstream HTTPS authorization header. JavaScript does not provide reliable zeroization, so avoid persistent plaintext caches and unnecessary copies. A DEK solely cached in an isolate cannot support a reliable global two-hour session: isolates restart and requests can land elsewhere. Persisted authorization grants solve that independently.

Rotate DEKs by retaining old/new versioned bindings, re-encrypting each row with fresh nonces, verifying completion/backups, and retiring the old binding after the recovery window. Rotating a DEK does not undo an already-exposed upstream PAT; rotate the PAT too. Backups and D1 Time Travel require a rollback procedure that revokes sessions and bearer tokens after restoration so old grants cannot become valid again.

Sources: [D1 security](https://developers.cloudflare.com/d1/reference/data-security/), [Worker WebCrypto](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/), [Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/).

## Worker MCP for Pi

Use the current Cloudflare stateless remote-MCP pattern and an official MCP SDK transport compatible with Workers’ Fetch API. Pin versions and prove compatibility rather than assuming a Node HTTP transport runs unchanged. Support initialization, protocol negotiation, tool listing/calls, notifications, and correct Streamable HTTP responses; do not invent a partial JSON-RPC protocol. Reject untrusted browser Origins, authenticate before dispatch, and bound message/batch sizes.

`workers-mcp` is the older local stdio-proxy approach; its README directs new projects toward remote MCP. A DO-backed `McpAgent` is possible on Free with SQLite DOs, but persistent MCP connection state is unnecessary for this vault. An MCP transport session ID is never an authorization grant.

Pi user configuration at `~/.pi/agent/mcp.json`:

```json
{
  "mcpServers": {
    "vault": {
      "url": "https://vault.example.workers.dev/mcp",
      "headers": {"Authorization": "Bearer <REQUEST_ONLY_TOKEN>"},
      "exposure": "codemode",
      "description": "Scoped tools; ask Muse to unlock when a grant expires"
    }
  }
}
```

The placeholder is replaced out of band; no PAT, master secret, or DEK goes into Pi. Environment substitution is supported but does not protect a bearer from a Pi process able to read that environment. Tool visibility settings and Pi permission hooks are useful UX controls; authorization remains Worker-side. Locked calls return a structured MCP tool error containing only `unlock_required`, service, label, and an instruction to ask Muse. Resources, pagination, retries, and every tool execution require the same checks.

Sources: installed `/root/.pi/agent/install/releases/1.5.2/node_modules/@earendil-works/pi-coding-agent/docs/mcp.md`; [Cloudflare remote MCP](https://developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server/), [workers-mcp](https://github.com/cloudflare/workers-mcp), [MCP transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).

## GitHub through the Worker

Expose narrow tools such as `github_read_file`, `github_list_issues`, and explicitly enabled write tools. Worker code maps each tool to service `github`; Pi cannot redefine that mapping. Resolve an exact authorized key label, decrypt only that row, and send `Authorization: Bearer <PAT>` to the fixed GitHub API origin, with required API headers/User-Agent. Both classic and fine-grained PATs use this flow.

Authorize canonical owner/repository, operation, branch, and file path using the intersection of agent, grant, and key policy. Build URLs server-side; disallow arbitrary URLs, header overrides, raw REST/GraphQL passthrough, and uncontrolled redirects. Bound pages, file sizes, and response bytes. PAT scopes and organization policies still apply; classic PATs may have broad upstream reach, making Worker policy enforcement essential. Never silently fall back from a failed work token to a personal token.

Return selected result fields, never upstream request/debug headers. Disable payload tracing and avoid exception serialization that includes credentials. Scrub exact active secret values and recognizable token patterns as defense in depth; regexes alone cannot guarantee removal of arbitrary secrets in repository content. Restrict sensitive paths and do not expose Actions logs/artifacts or arbitrary downloads by default. Writes use idempotency handling so a retry cannot duplicate effects.

Authenticated PAT REST requests generally share a 5,000/hour user limit; multiple PATs for one user do not automatically multiply it. Search and secondary limits differ. Honor rate-limit headers and retry guidance; authenticated conditional requests yielding 304 can reduce primary-limit usage where documented.

Sources: [GitHub REST authentication](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api), [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), [REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).

## Free-tier limits and budget

| Product | Relevant Free allowance/constraint | Decision |
|---|---|---|
| Workers | 100,000 requests/day; 10 ms CPU/request; inherited docs list 50 external subrequests/request | Chosen; cap processing and benchmark CPU. Network wait differs from CPU. |
| D1 | 5 million rows read/day; 100,000 rows written/day; 10 databases; 500 MB/database, 5 GB/account; inherited docs list 50 queries/invocation | Chosen; indexed authorization/key lookup, bounded audits. |
| KV | 100,000 reads/day; 1,000 writes/day; 1 GB storage; same-key write limit 1/second | Omit. Eventual consistency makes immediate revocation unsuitable. |
| Durable Objects | SQLite-backed Free available; 13,000 GB-s/day compute duration, 5 GB storage/account, 100 classes in recovered docs | Omit; viable alternative, not inherently paid. Separate DO request/SQL quotas also apply. |
| Pages | Free static hosting; 500 builds/month; Functions use Workers allowances | Optional UI only. |

D1 limits are **rows**, not simply SQL statement counts; indexes and scans matter. Treat enforced daily limits since 2026-09-01 as hard availability boundaries. One indexed join can check bearer, grant, policy, and key; measure actual `rows_read`/`rows_written`. At 200 calls/day, a handful of row reads/call and tens to hundreds of bounded audit writes/day fit comfortably. Do not promise a fixed CPU cost without measuring SDK, crypto, JSON parsing, and redaction together.

Audit unlock/revoke/key changes and writes using timestamp, agent/key IDs, operation, status, and request ID only. Sample successful reads; omit arguments, bodies, headers, raw errors, and per-call last-used updates. Retain a small capped history, prune in bounded batches, and account for deletion/index writes. Never buffer mandatory audit records in isolate memory. Missing authorization/quota reads fail closed. Require an audit reservation before state-changing calls; acknowledge upstream/D1 atomicity limits if result logging later fails.

Keep the account on Free and do not attach paid-only dependencies. Quota exhaustion means refusal/outage, not permission to upgrade. Unauthenticated traffic can still exhaust Worker capacity; request caps and low-cost rejection reduce abuse but cannot guarantee availability.

Sources: [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/), [KV limits](https://developers.cloudflare.com/kv/platform/limits/), [KV consistency](https://developers.cloudflare.com/kv/concepts/how-kv-works/), [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/), [DO limits](https://developers.cloudflare.com/durable-objects/platform/limits/), [Pages limits](https://developers.cloudflare.com/pages/platform/limits/).

## Scoped two-hour unlocks and multiple keys

Muse calls `POST /unlock` with its master credential and `{agent_id, service, key_label, allowed_tools, resources, request_id}`. The Worker verifies the master against a secret-stored verifier, resolves the exact enabled key, bounds policy, and records server time `opened_at`, `expires_at = opened_at + 7200`. The TTL is fixed server-side. Repeated delivery of the same admin request is idempotent and does not extend expiry.

A `github/work` unlock permits only that key for that Pi identity. `github/personal` and `cloudflare/main` each need their own unlock and independent window. Calls specify a label; no “all keys,” ambiguous defaults, or fallback. Multiple simultaneously authorized keys are allowed.

Before each upstream dispatch, perform a fresh primary authorization read; do not enable replica-backed authorization reads. If using D1 Sessions API, start the authorization session with `first-primary`. Require matching agent/service/key and `revoked_at IS NULL AND expires_at > server_now`. Recheck before subsequent dispatches in a multi-step tool. Expiry/revoke cannot retract an already-transmitted GitHub operation; keep tools short, bounded, and synchronous. Restarting the Worker changes neither the deadline nor the grant.

`POST /revoke` targets a grant, agent, or exact key. Token revocation disables all its grants. Key rotation/disable revokes grants bound to that key; stale labels must not select a replacement automatically. After expiry, return `unlock_required`; Pi asks Muse again. Muse approves the exact service, key, and scope using trusted task context, rather than accepting Pi’s suggested scope blindly.

In-memory timers are unreliable across isolates. KV TTL has eventual consistency, including potentially more than 60 seconds depending on cache TTL. DO alarms can clean up durable state but do not remove the need to check time at dispatch, and DO RAM is not durable. **D1 timestamp checks win because D1 is already required.**

Source: [D1 read replication and Sessions API](https://developers.cloudflare.com/d1/best-practices/read-replication/).

## Alternatives

Worker secret bindings alone simplify a fixed handful of keys but do not meet the requirement to manage multiple encrypted key rows in D1. Cloudflare Secrets Store is a reasonable managed alternative for secret lifecycle/RBAC; it still needs the Worker policy/session layer and does not satisfy the requested D1 storage design. Its exact current free entitlement was not established in the recovered evidence, so it is not a dependency.

1Password, Doppler, and Infisical can improve lifecycle management, but a gateway is still required to keep credentials off Pi. Do not assume their hosted or self-hosted operating costs are zero. A VM gateway has familiar tooling but adds patching, persistence, and hosting operations; it is outside the chosen free Cloudflare stack. None eliminates misuse of authorized tools or a compromised gateway deployer.

## Concrete build plan

1. Create one Free Worker and D1 database. Provision independent DEK and master verifier through Muse-controlled tooling. No bootstrap/deploy credential enters Pi. Keep the vault in a deployment boundary Pi cannot modify through GitHub tools or CI.
2. Migrate these tables, using foreign keys, uniqueness constraints, and indexed lookups:

   - `keys(id PK, service, label, ciphertext, nonce, enc_version, policy_json, enabled)`; `UNIQUE(service,label)`.
   - `agents(id PK, token_hash UNIQUE, policy_json, revoked_at)`; bearer is at least 256 random bits, stored only as hash server-side.
   - `grants(id PK, agent_id FK, key_id FK, service, policy_json, opened_at, expires_at, revoked_at, admin_request_id UNIQUE)`; index `(agent_id,key_id,expires_at)` and enforce key/service agreement.
   - `audit(id PK, ts, agent_id, key_id, grant_id, operation, status, request_id)`; minimum necessary indexes.
   - Bounded write-operation idempotency records as needed; no raw tool payloads.
3. Implement `/mcp`, Muse-only `/unlock`, `/revoke`, and `/admin/keys` for add/rotate/disable plus metadata-only listing. No decrypt/export route. Admin tools, if offered over MCP, belong to a separate authenticated Muse endpoint and never Pi’s tool list.
4. Add a same-origin manual entry page with restrictive CSP, no third-party scripts/storage, `Cache-Control: no-store`, and no payload logging. A human pastes a key directly into this page; Muse submits secrets from its secure environment without transcript/shell-history interpolation. Authenticate admin requests, protect against CSRF, encrypt immediately, return metadata only. Do not grant admin merely because a page is hidden or an unverified Access header exists.
5. Implement the GitHub adapter and all server-side policy checks; configure Pi with only its endpoint/bearer. Enforce host egress restrictions if required. Deploy only through Muse-controlled credentials.
6. Acceptance checks: initialize/list/call MCP from installed Pi; deny admin with Pi token; deny cross-service/key/agent substitution; deny at exactly expiry; verify revoke via another connection and after redeploy; reject redirects/path bypasses; test GCM tampering and rotation; exercise duplicate writes, quota failures, audit caps, and restore/revocation. Use canary credentials to inspect results/logs for leakage. Measure worst-case CPU under 10 ms; reduce tool sizes if needed rather than adopt Paid.

## Three strongest objections to the recommended plan

1. **The gateway is a total-compromise point.** Worker deploy access, Muse administration compromise, or D1 write access can defeat important boundaries. AES-GCM protects database confidentiality, not malicious execution or authorization-row integrity. Accept only with independent deployment control, narrow upstream permissions, and recovery/revocation procedures.
2. **Two hours permits lasting damage.** A malicious agent can exploit legitimate operations without ever learning a PAT. Narrow server-enforced tools/resources and exclusion of persistence-producing operations are essential; audit and expiry alone do not prevent this.
3. **Free-tier correctness costs availability and engineering effort.** SDK CPU, primary D1 reads, quota exhaustion, upstream retries, and partial write/audit failures require careful handling. There is no free-tier SLA or guaranteed CPU headroom. The plan deliberately fails closed and pauses Pi until Muse restores access; if those limits fail acceptance, reduce scope rather than weaken the boundary or silently incur paid usage.
