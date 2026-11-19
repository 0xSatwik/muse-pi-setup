# Cloudflare Tunnel — permanent URL for Pi

Pi's gateway runs on the sandbox at `http://127.0.0.1:8765`. To reach it
from anywhere (your Muse, your phone, the Admin page), it needs a public
URL. A Cloudflare Tunnel gives it one. There are two kinds: a **named
tunnel** (permanent) and a **quick tunnel** (temporary). Use the named
tunnel. The quick tunnel is only a fallback.

## The two tunnels

| | Named tunnel (permanent) | Quick tunnel (temporary) |
|---|---|---|
| URL | `https://<name>.<your-domain>` — stays the same forever | `https://<random>.trycloudflare.com` — changes every restart |
| Setup | Once, then it just runs | Every restart |
| Use for | Admin page, Muse→Pi, daily use | Emergency fallback only |

## 1. Named tunnel — set it up once

Prerequisites: a Cloudflare account, a domain (or free subdomain) whose
DNS is on Cloudflare in that SAME account, and `cloudflared` on the box.

### a. Create the tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create <name>        # e.g. hardeepwalia
```

This writes credentials to `~/.cloudflared/<tunnel-id>.json`. Note the
tunnel id.

### b. Add a DNS record — proxied, not DNS-only

Create a CNAME in the Cloudflare DNS for your zone:

```
<name>.<your-domain>  CNAME  <tunnel-id>.cfargotunnel.com  proxied: true
```

**Proxied MUST be true (orange cloud).** This is the most common mistake.
With `proxied: false` (DNS-only, grey cloud) the browser hits the tunnel
address directly and gets `ERR_CONNECTION_RESET` — the tunnel never
receives the traffic. A tunnel hostname only works when Cloudflare's edge
proxies it to the tunnel. (Learned 2026-11-19: the permanent URL failed
with connection reset until the record was flipped to proxied; DNS then
needed ~60 seconds to propagate.)

The CNAME target must be in the SAME Cloudflare account as the zone.
A CNAME to `<uuid>.cfargotunnel.com` only works inside the account that
owns the tunnel — a foreign DNS record gives 530/1033, cross-account
gives 1014.

### c. Write the config

`~/.cloudflared/config.yml`:

```yaml
tunnel: <tunnel-id>
credentials-file: /root/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: <name>.<your-domain>
    service: http://127.0.0.1:8765
  - service: http_status:404
```

Keep a backup: `cp config.yml config.yml.bak-permanent`.

### d. Run it — recreate the tmux session, never restart inside it

```bash
tmux kill-session -t pi-tunnel 2>/dev/null; sleep 2
tmux new-session -d -s pi-tunnel 'cloudflared tunnel --config /root/.cloudflared/config.yml run'
```

**Never restart cloudflared inside the existing tmux session.** A tmux
session CLOSES when its main process exits, and cloudflared IS the main
process of `pi-tunnel`. Sending Ctrl-C kills the session itself, so the
restart command has nowhere to run. (Learned 2026-11-19: three failed
switch attempts before this was understood.) Always kill the session and
create a fresh one with the command.

Wait 45 seconds, then verify:

```bash
tmux ls                                        # pi-tunnel must exist
tmux capture-pane -t pi-tunnel -p | tail -20    # look for "Registered tunnel connection"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/health   # must be 200
```

And check from the Cloudflare side (API): the tunnel should show 4
connections. Then open `https://<name>.<your-domain>/admin` in a
browser — the Pi Admin page should load.

### e. If it doesn't register

- Check the config hostname matches the DNS record exactly.
- Check the DNS record is proxied (see b).
- Check the tunnel id and credentials-file path in the config.
- Run `cloudflared` in the foreground for 15s with the same config and
  read the exact error lines — do not guess from a condensed log.
- The tunnel log ending at "precheck complete" with no registration and
  no error usually means the process died silently or the check was too
  early — confirm with `ps aux | grep cloudflared` whether it is running.

## 2. Quick tunnel — temporary, fallback only

```bash
tmux new-session -d -s pi-tunnel-quick 'cloudflared tunnel --config /root/pi-bridge/quick-empty.yml --url http://127.0.0.1:8765'
```

This prints a random `https://<random>.trycloudflare.com` URL. It works
immediately with no DNS setup, but the URL changes on every restart, so
it is not a permanent address. Keep it running as a fallback while the
named tunnel is being set up. Do NOT retire it until the named tunnel's
permanent URL is verified loading in a browser.

**If only a quick tunnel is set (no named tunnel yet):**
1. Use the quick URL for now — it works, it just changes on restart.
2. Set up the named tunnel using section 1 above (create tunnel, add the
   proxied DNS record, write the config, recreate the session).
3. Verify the permanent URL loads in a browser.
4. Only then stop the quick tunnel: `tmux kill-session -t pi-tunnel-quick`.
5. Update any saved URLs (Muse's gateway address, bookmarks) to the
   permanent one.

## 3. Free domain for the tunnel

A tunnel needs a domain to publish a permanent URL. Options (researched
2026-11-19):
- **eu.org** — free for life, in the Public Suffix List, Cloudflare
  accepts it as a zone. Manual approval, days to weeks. The only
  genuinely free-for-life path.
- **DigitalPlat dpdns.org** — free subdomain, works with tunnels, but
  needs renewal every 365 days (not lifetime).
- **afraid.org FreeDNS** — does NOT work (not in the PSL, cannot be a
  Cloudflare zone, cannot point at a tunnel).
- **Freenom (.tk/.ml/.ga/.cf/.gq)** — dead, no free signup anymore.
- A cheap paid domain works the same day and is the practical choice
  if eu.org approval is too slow.
- A Workers.dev reverse proxy does NOT work — a Worker cannot reach a
  named tunnel via `<id>.cfargotunnel.com` (upstream_failed). A custom
  domain is the only clean permanent URL.

## 4. Domain must be in the tunnel's account

The domain (zone) must live in the SAME Cloudflare account as the
tunnel. If the tunnel is in account A and the domain is in account B,
the CNAME will not route. Move the zone to the tunnel's account, or
create the tunnel in the account that holds the domain.
