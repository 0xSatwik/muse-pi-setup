# Setup updates for `/pi` (Pi Chat)

Two audiences: someone building a box from scratch, and someone who already has a working box
and just wants the chat page. Pick the section that applies.

---

## A. New setup — from scratch

### 1. Install Pi and make sure it is on PATH

```bash
# Pi lives here once installed
ls /root/.pi/agent/bin/pi
```

The gateway shells out to `pi --mode rpc` for every session. If `pi` is not on `PATH` the gateway
starts fine but every prompt fails with `FileNotFoundError: pi`. Put it on PATH for the gateway
process explicitly (see step 4) rather than relying on a login shell.

### 2. Put the gateway and the page in place

```bash
mkdir -p /root/pi-bridge
# gateway (patched, includes /pi and /stats)
cp pi-gateway.py /root/pi-bridge/pi-gateway.py
# the chat UI — served from disk, so it can be updated without touching Python
cp pi.html       /root/pi-bridge/pi.html
chmod 600 /root/pi-bridge/pi-gateway.py
```

### 3. Create `gateway.env`

`/root/pi-bridge/gateway.env`, `chmod 600`, two lines:

```bash
PI_GATEWAY_TOKEN=<long random token>
PI_ADMIN_PASS_SHA256=<sha256 hex of your opening password>
```

Generate them without echoing the values:

```bash
python3 - <<'PY'
import hashlib, secrets, pathlib
tok = secrets.token_urlsafe(32)
pw  = input("opening password: ")
h   = hashlib.sha256(pw.encode()).hexdigest()
p = pathlib.Path("/root/pi-bridge/gateway.env")
p.write_text(f"PI_GATEWAY_TOKEN={tok}\nPI_ADMIN_PASS_SHA256={h}\n")
p.chmod(0o600)
print("wrote gateway.env (values not printed)")
PY
```

`PI_ADMIN_PASS_SHA256` is what makes the `/admin` and `/pi` opening-password login work. The
same password unlocks both pages; the raw gateway token also works on either.

### 4. Start the gateway in tmux, with PATH set and output logged

```bash
tmux new -s pi-gateway -d \
  'PATH=/root/.pi/agent/bin:$PATH exec python3 /root/pi-bridge/pi-gateway.py \
   >> /root/pi-bridge/gateway.log 2>&1'
```

Both parts matter:

- `PATH=/root/.pi/agent/bin:$PATH` — without it, `FileNotFoundError: pi` on the first prompt.
- `>> /root/pi-bridge/gateway.log 2>&1` — without it a crash is silent and the tmux pane scrolls
  away. The log is the first place to look when prompts stop working.

### 5. Expose it (optional)

A tunnel that forwards to the gateway serves both pages, since they are the same server:

```yaml
# /root/.cloudflared/config.yml
ingress:
  - hostname: <your-hostname>
    service: http://127.0.0.1:8765
  - service: http_status:404
```

### 6. Check it

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/pi     # 200
curl -s http://127.0.0.1:8765/health                                   # {"ok": true, ...}
curl -s -H "Authorization: Bearer $PI_GATEWAY_TOKEN" \
     http://127.0.0.1:8765/stats                                       # cpu/ram/disk
```

Then open `/pi` and log in with your opening password.

---

## B. Existing setup — add `/pi` to a running box

No reinstall, no sandbox restart, no tunnel change. Four steps, ~1 minute.

### 1. Back up the two files you are about to touch

```bash
cd /root/pi-bridge
cp pi-gateway.py pi-gateway.py.bak-pre-pi
cp pi.html       pi.html.bak-pre-freeze    # if pi.html already exists
```

### 2. Copy the new `pi.html`

```bash
cp pi.html /root/pi-bridge/pi.html
```

This alone is enough if your gateway already has the `/pi` route. If `/pi` returns 404, do step 3.

### 3. Apply the gateway patch (only if `/pi` 404s)

Either apply the unified diff:

```bash
cd /root/pi-bridge
patch -p0 < gateway-patch-unified.diff
python3 -m py_compile pi-gateway.py     # must exit 0
```

…or add the four pieces by hand, per `gateway-patch.md`:

1. the two docstring lines (`GET /pi`, `GET /stats`),
2. the stats block before `# ---- models.json CRUD ----`,
3. the `/pi` route at the top of `do_GET` and the `/stats` route after `/health`,
4. the two seed calls in `__main__`.

If you are also picking up the crash fix, confirm `_body()` wraps `json.loads` in
`try/except` and returns `{}` — otherwise a non-JSON POST body kills the server.

### 4. Restart the gateway ONLY

```bash
tmux kill-session -t pi-gateway
tmux new -s pi-gateway -d \
  'PATH=/root/.pi/agent/bin:$PATH exec python3 /root/pi-bridge/pi-gateway.py \
   >> /root/pi-bridge/gateway.log 2>&1'
```

**Do not restart the sandbox, the watcher, or the tunnel.** Only the gateway process needs to
re-read the patched file. The watcher (`tmux pi-bridge`) and the tunnel (`tmux pi-tunnel`) keep
running untouched.

> **PATH is not optional.** Omitting `PATH=/root/.pi/agent/bin:$PATH` produces a gateway that
> answers `/health` and `/pi` perfectly but fails every prompt with `FileNotFoundError: pi`,
> because the RPC subprocess cannot find the binary.

### 5. Verify

```bash
curl -s -o /dev/null -w '/pi %{http_code}\n' http://127.0.0.1:8765/pi
curl -s http://127.0.0.1:8765/health; echo
curl -s -H "Authorization: Bearer $PI_GATEWAY_TOKEN" http://127.0.0.1:8765/stats
```

Expected: `/pi` → `200`; health → `{"ok": true, ...}`; stats → `disk.pct` around the workspace
footprint against 10 GiB (not the host overlay percentage).

Then open `/pi`, unlock with your existing opening password, and pick a session.

### Updating the page later

`/pi` is read from disk on every request with `Cache-Control: no-cache`, so replacing
`/root/pi-bridge/pi.html` is a live update — no gateway restart, no patch.

```bash
cp new-pi.html /root/pi-bridge/pi.html     # reload the browser tab
```

### Rolling back

```bash
cd /root/pi-bridge
cp pi-gateway.py.bak-pre-pi pi-gateway.py
cp pi.html.bak-pre-freeze  pi.html
tmux kill-session -t pi-gateway
tmux new -s pi-gateway -d \
  'PATH=/root/.pi/agent/bin:$PATH exec python3 /root/pi-bridge/pi-gateway.py \
   >> /root/pi-bridge/gateway.log 2>&1'
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/pi` → 404 | gateway running an old copy without the route | step 3, then step 4 |
| Page loads, bars show `—` | `/stats` failing or not yet seeded | check `curl /stats` with the token; the page retries every 2 s |
| Prompt fails, `FileNotFoundError: pi` | gateway started without PATH | restart with `PATH=/root/.pi/agent/bin:$PATH` |
| Gateway dies on a POST | old `_body()` without try/except | apply the crash fix, restart |
| Page freezes on a long chat | old `pi.html` re-rendering the whole transcript per token | copy the current `pi.html` (live bubble + 100-message window) |
| Disk bar reads ~51% | old `/stats` using the host overlay | apply the disk fix in `gateway-patch.md` |
| Login rejects the password | `PI_ADMIN_PASS_SHA256` missing or stale in `gateway.env` | regenerate the hash, restart the gateway |
| `gateway.log` shows `BrokenPipeError` | client hung up mid-response | harmless; ignore unless repeated |
