# Gateway patch — what changed in `pi-gateway.py`

**Before:** 848 lines · **After:** 1067 lines (+219)
**Backup of the original on the box:** `/root/pi-bridge/pi-gateway.py.bak-pre-pi`
**Machine-readable diff:** `pi-gateway.py.patch` (also `gateway-patch-unified.diff`, identical)
Apply with `cd /root/pi-bridge && patch -p0 < gateway-patch-unified.diff`.

All changes are additive or defensive. Every pre-existing route, the auth gate, the RPC plumbing
and the `/admin` page are unchanged in behaviour.

> **Start the gateway with `pi` on PATH.** Every prompt shells out to `pi --mode rpc`. Without
> `PATH=/root/.pi/agent/bin:$PATH` the gateway serves `/health` and `/pi` fine but fails every
> prompt with `FileNotFoundError: pi`.
>
> ```bash
> tmux new -s pi-gateway -d \
>   'PATH=/root/.pi/agent/bin:$PATH exec python3 /root/pi-bridge/pi-gateway.py \
>    >> /root/pi-bridge/gateway.log 2>&1'
> ```

---

## 1. Docstring — 2 lines added (lines 34–35)

```python
   GET  /pi                            single-page chat UI (Pi Chat)
   GET  /stats                         live sandbox CPU / RAM / disk usage
```

## 2. Crash fix — `_body()` (lines 741–748)

**This is a pre-existing bug, not introduced by `/pi`.** The original body read:

```python
def _body(self):
    n = int(self.headers.get("Content-Length") or 0)
    return json.loads(self.rfile.read(n) or b"{}") if n else {}
```

`json.loads()` sat outside any `try`, so a POST whose body was not JSON (empty body, form post,
curl without `-H 'Content-Type: application/json'`, a probe) raised `JSONDecodeError` inside the
request handler. That propagated out of `do_POST` and killed the server — taking down every live
session's RPC process with it. Reproduced at ~03:36 on this box.

Now:

```python
def _body(self):
    n = int(self.headers.get("Content-Length") or 0)
    if not n:
        return {}
    try:
        return json.loads(self.rfile.read(n) or b"{}")
    except Exception:
        return {}
```

A malformed body yields `{}`; the route then fails its own validation and returns a normal 4xx
while the server keeps serving. **Apply this even if you never use `/pi`** — it is a
denial-of-service fix for the whole gateway.

## 3. New stats module — inserted before `# ---- models.json CRUD ----` (lines 234–416)

| Symbol | Line | Purpose |
|---|---|---|
| `CPU_MOUNT`, `DISK_QUOTA_GB`, `_cpu_prev`, `_ws_cache`, `WS_TTL` | 235–239 | module state |
| `_seed_cpu()` | 242 | baseline CPU reading at startup so the first `/stats` is not `null` |
| `_seed_workspace()` | 250 | warms the `/root` size cache in a background thread |
| `_cgroup(path)` | 258 | read a cgroup v2 file, `None` on failure |
| `_cpu_quota_cores()` | 266 | parse `cpu.max` → cores (`"175000 100000"` → 1.75) |
| `_cpu_usage_usec()` | 278 | cumulative sandbox CPU from `cpu.stat` |
| `_read_cpu()` | 290 | fallback: host-wide `/proc/stat` jiffies |
| `_workspace_bytes(force=False)` | 302 | cached `du -sxB1 /root` (30 s walk, 5 min TTL, background thread) |
| `stats_snapshot()` | 325 | builds the JSON returned by `GET /stats` |

### Why cgroup values, not host values

The box is a container on a 16-core / 128 GiB host with an 845 GB overlay filesystem. Host-wide
numbers are misleading inside a 1.75-core / 6.3 GiB sandbox:

| Metric | Source | Example on this box |
|---|---|---|
| CPU | `cpu.stat usage_usec` delta ÷ wall time ÷ `cpu.max` quota | 13.3 % of 175 % |
| RAM | `memory.current` ÷ `memory.max` | 1.4 / 6.3 GiB = 21.9 % |
| Disk | `du -sxB1 /root` ÷ `DISK_QUOTA_GB` (10) | 4.03 / 10 GiB = **40.3 %** |
| Disk (reference) | `statvfs("/")` | 433.7 / 845.3 GB host overlay = 51.3 % |

### Disk fix — the reason `pct` changed

The first version of `stats_snapshot()` used `statvfs("/")` for the disk bar, which inside this
container reports the **845 GB host overlay**. The bar read 51 % while the sandbox was nowhere
near its allowance, contradicting the "10 GiB disk" label next to it. There is no cgroup disk
quota to read instead (`io.max` is empty).

The disk figure is now the sandbox's own workspace footprint against the plan allowance:

```json
"disk": {
  "pct": 40.3,
  "used_gb": 4.03,
  "total_gb": 10.0,
  "basis": "workspace(/root) vs plan quota",
  "host": { "pct": 51.3, "used_gb": 433.7, "total_gb": 845.3 }
}
```

The host overlay numbers remain available under `disk.host` for reference but **never** feed
`disk.pct`.

## 4. `GET /pi` and `GET /pi.html` — route added (lines 750–772)

Inserted at the top of `do_GET`, **before** `if _path == "/admin"` and before the auth gate — the
same model as `/admin`: the page shell is public because it holds no secrets, and every API call
it makes is Bearer-authenticated.

```python
def do_GET(self):
    _path = urlparse(self.path).path
    if _path in ("/pi", "/pi.html"):
        body = None
        try:
            with open(os.path.join(BASE, "pi.html"), "rb") as f:
                body = f.read()
        except Exception:
            body = None
        if body is None:
            body = (b"<!doctype html><meta charset=utf-8><title>Pi Chat</title>"
                    b"<p style='font:15px system-ui;padding:24px'>pi.html is missing on the box. "
                    b"Copy it to /root/pi-bridge/pi.html and reload.")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)
        return
    if _path == "/admin":
        ...
```

The page is read **from disk on every request**, not embedded as a Python string like
`ADMIN_HTML`. That means the UI can be updated by copying one file — no gateway edit, no restart.
`Cache-Control: no-cache` stops browsers pinning an old copy.

## 5. `GET /stats` — route added (lines 789–790)

Added immediately after `/health`, so it sits behind the normal Bearer auth gate:

```python
if u.path == "/stats":
    return self._json(200, stats_snapshot())
```

Full response on this box:

```json
{
  "cpu":  { "pct": 13.3, "quota": 175 },
  "ram":  { "pct": 21.9, "used_gb": 1.4, "total_gb": 6.3 },
  "disk": { "pct": 40.3, "used_gb": 4.03, "total_gb": 10.0,
            "basis": "workspace(/root) vs plan quota",
            "host": { "pct": 51.3, "used_gb": 433.7, "total_gb": 845.3 } },
  "spec": { "ram": "6.3 GiB", "cpu": "175%", "disk": "10 GiB" },
  "updated": 1795127388
}
```

`pct` can be `null` on the very first call after a cold start if `cpu.stat` is unreadable; the
startup seed normally prevents that. `disk.pct` stays `null` until the first `du` finishes
(~30 s), then is cached for 5 minutes.

## 6. Startup seed calls — `__main__` block (lines 1061–1067)

```python
if __name__ == "__main__":
    # Seed the CPU baseline and warm the /root footprint cache so the first
    # /stats call already returns real numbers instead of nulls.
    _seed_cpu()
    _seed_workspace()
    print(f"pi-gateway listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
```

## 7. New file on the box (not a Python change)

`/root/pi-bridge/pi.html` — the chat UI, 1107 lines / 50,550 bytes, served by the route in §4.

---

## Applying this to another box

```bash
cd /root/pi-bridge
cp pi-gateway.py pi-gateway.py.bak-pre-pi
patch -p0 < gateway-patch-unified.diff    # or add the pieces by hand per the sections above
python3 -m py_compile pi-gateway.py       # must exit 0
cp pi.html /root/pi-bridge/pi.html

# restart ONLY the gateway, with PATH set and output logged
tmux kill-session -t pi-gateway
tmux new -s pi-gateway -d \
  'PATH=/root/.pi/agent/bin:$PATH exec python3 /root/pi-bridge/pi-gateway.py \
   >> /root/pi-bridge/gateway.log 2>&1'
```

Verify:

```bash
curl -s -o /dev/null -w '/pi %{http_code}\n' http://127.0.0.1:8765/pi
curl -s http://127.0.0.1:8765/health; echo
curl -s -H "Authorization: Bearer $PI_GATEWAY_TOKEN" http://127.0.0.1:8765/stats
```
