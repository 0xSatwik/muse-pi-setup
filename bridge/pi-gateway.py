#!/usr/bin/env python3
"""pi-gateway.py — direct HTTP API for Pi on the Altare sandbox.

Muse talks to Pi over plain HTTPS (via a cloudflared tunnel) instead of
the flaky Altare Files API. One Pi RPC subprocess per session
(`pi --mode rpc`), JSONL commands in, events out. Stdlib only.

Auth: Bearer token from /root/pi-bridge/gateway.env (PI_GATEWAY_TOKEN=...).
Listen: 127.0.0.1:8765 by default (PI_GATEWAY_HOST / PI_GATEWAY_PORT
override it). On Hoody the gateway binds 0.0.0.0 so the Hoody proxy can
reach it; a tunnel or the tailnet exposes it publicly otherwise.

Endpoints (all except /health need Authorization: Bearer <token>):
  GET  /health
  GET  /sessions                      list sessions (disk + running state)
  POST /prompt {message, session_id?, model?, cwd?, name?}
       new session (no session_id) or continue existing one. Returns
       {session_id, accepted, disposition}. Use streamingBehavior steer
       automatically when the session is already running.
  POST /sessions/{id}/prompt {message}   next prompt into a session
  GET  /sessions/{id}                 transcript + stats
  GET  /sessions/{id}/status          running?, last assistant text
  GET  /sessions/{id}/events?since=N  live progress events (poll)
  POST /sessions/{id}/stop            abort current run
  POST /sessions/{id}/rename {name}
  DELETE /sessions/{id}               delete session file (stops process)
  POST /sessions/{id}/model {model}   switch model mid-session
  GET  /models                        models.json + available models
  POST /models {provider, id, api?, baseUrl?, apiKey? | env_name+api_key}
       add a model to models.json (api_key is stored in provider-keys.env,
       models.json keeps only the $ENV_NAME placeholder)
  POST /secrets {env_name, api_key}   store a provider API key (chmod 600)
  GET  /admin                         single-page admin UI (keys & models)
  GET  /pi                            single-page chat UI (Pi Chat)
  GET  /stats                         live sandbox CPU / RAM / disk usage
  GET  /secrets                       env names + set/unset (never values)
  DELETE /secrets/{env_name}          remove a provider key
  GET  /settings                      current default provider/model
  POST /settings {defaultProvider, defaultModel}
  GET  /monid                         whether the Monid search key is set
  POST /monid {key}                   store the Monid key (chmod 600)
  POST /provider-models {base_url, api_key? | env_name?}
                                      fetch the provider's live /models list
  POST /restart                       restart the gateway (reloads keys)
  PATCH /models/{provider}/{id} {..}  edit a model entry
  DELETE /models/{provider}/{id}      remove a model entry
  POST /rpc {session_id, command}     raw RPC passthrough, any command
  GET  /files?path=<relpath>          pull a file from /root/work
  POST /sessions/{id}/compact         compact session context

Run: PI_GATEWAY_TOKEN set via /root/pi-bridge/gateway.env
  python3 /root/pi-bridge/pi-gateway.py   (tmux: pi-gateway)
"""
import hashlib, hmac, json, os, re, subprocess, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request, urllib.error
from urllib.parse import urlparse, parse_qs

BASE = "/root/pi-bridge"
WORK = "/root/work"
SESSIONS_DIR = os.path.expanduser("~/.pi/agent/sessions")
MODELS_JSON = os.path.expanduser("~/.pi/agent/models.json")
KEYS_FILE = os.path.join(BASE, "provider-keys.env")  # chmod 600, KEY=VALUE lines
PORT = int(os.environ.get("PI_GATEWAY_PORT", "8765"))
HOST = os.environ.get("PI_GATEWAY_HOST", "127.0.0.1")


def load_keys_file():
    """Provider API keys live here (never in models.json, never logged)."""
    try:
        with open(KEYS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


load_keys_file()
TOKEN = None
for line in open(os.path.join(BASE, "gateway.env")) if os.path.exists(os.path.join(BASE, "gateway.env")) else []:
    if line.startswith("PI_GATEWAY_TOKEN="):
        TOKEN = line.strip().split("=", 1)[1]
TOKEN = TOKEN or os.environ.get("PI_GATEWAY_TOKEN")
ADMIN_PASS_SHA256 = os.environ.get("PI_ADMIN_PASS_SHA256")
for line in open(os.path.join(BASE, "gateway.env")) if os.path.exists(os.path.join(BASE, "gateway.env")) else []:
    if line.startswith("PI_ADMIN_PASS_SHA256="):
        ADMIN_PASS_SHA256 = line.strip().split("=", 1)[1]
if not TOKEN:
    print("no PI_GATEWAY_TOKEN in gateway.env or env", file=sys.stderr)
    sys.exit(1)

LOGIN_FAILS = {}

# ---- RPC process management ----
procs = {}          # session_id -> {"proc", "reader", "pending", "events", "lock", "cwd", "running"}
procs_lock = threading.Lock()


def log_event(sid, rec):
    p = procs.get(sid)
    if p is None:
        return
    p["events"].append(rec)
    if len(p["events"]) > 2000:
        p["events"] = p["events"][-2000:]
    try:
        with open(os.path.join(BASE, "sessions", sid + ".events.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def reader_thread(sid):
    p = procs[sid]
    proc = p["proc"]
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("type") == "response" and rec.get("id") in p["pending"]:
                ev = p["pending"].pop(rec["id"])
                ev["result"] = rec
                ev["done"].set()
            else:
                log_event(sid, rec)
                t = rec.get("type", "")
                if t in ("agent_start",):
                    p["running"] = True
                elif t in ("agent_end", "agent_settled"):
                    p["running"] = False
    except Exception:
        pass
    p["running"] = False


def spawn_rpc(sid, cwd, model=None):
    """Start pi --mode rpc for a session (resume if sid given). Returns entry."""
    os.makedirs(os.path.join(BASE, "sessions"), exist_ok=True)
    cmd = ["pi", "--mode", "rpc"]
    if sid:
        cmd += ["--session", sid]
    if model:
        cmd += ["--model", model]
    env = dict(os.environ)
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
    entry = {"proc": proc, "pending": {}, "events": [], "lock": threading.Lock(),
             "cwd": cwd, "running": False, "sid": sid}
    procs[sid or "new"] = entry
    threading.Thread(target=reader_thread, args=(sid or "new",), daemon=True).start()
    return entry


def rpc_call(entry, cmd, timeout=60):
    rid = "req-" + uuid.uuid4().hex[:8]
    cmd = dict(cmd)
    cmd["id"] = rid
    ev = {"done": threading.Event(), "result": None}
    with entry["lock"]:
        entry["pending"][rid] = ev
        entry["proc"].stdin.write(json.dumps(cmd) + "\n")
        entry["proc"].stdin.flush()
    if not ev["done"].wait(timeout):
        entry["pending"].pop(rid, None)
        return {"success": False, "error": "timeout waiting for pi response"}
    return ev["result"]


def ensure_proc(sid, cwd=WORK, model=None):
    """Get (or start) the RPC process for a session id."""
    with procs_lock:
        if sid in procs and procs[sid]["proc"].poll() is None:
            return procs[sid]
        if sid in procs:
            del procs[sid]
    return spawn_rpc(sid, cwd, model)


def session_files():
    out = []
    seen = set()
    # live gateway sessions first (RPC processes) — Pi may not have
    # flushed the session file to disk yet
    for sid, p in procs.items():
        if p["proc"].poll() is not None:
            continue
        seen.add(sid)
        out.append({"id": sid, "name": sid, "cwd": p["cwd"], "messages": len(p["events"]),
                    "mtime": time.time(), "running": p["running"], "live": True})
    # disk: scan ~/.pi/agent recursively for session jsonl files
    roots = [SESSIONS_DIR, os.path.expanduser("~/.pi/agent")]
    for root in roots:
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(dirpath, fn)
                sid = fn[:-6]
                if sid in seen:
                    continue
                seen.add(sid)
                name, cwd, n = sid, "", 0
                try:
                    with open(path) as f:
                        for line in f:
                            n += 1
                            try:
                                rec = json.loads(line)
                            except Exception:
                                continue
                            if isinstance(rec, dict):
                                if rec.get("type") == "session" and rec.get("name"):
                                    name = rec["name"]
                                if rec.get("cwd"):
                                    cwd = rec["cwd"]
                except Exception:
                    pass
                out.append({"id": sid, "name": name, "cwd": cwd, "messages": n,
                            "mtime": os.path.getmtime(path),
                            "running": sid in procs and procs[sid]["proc"].poll() is None and procs[sid]["running"]})
    out.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    return out


# ---- host / sandbox stats (for the /pi page header) ----
CPU_MOUNT = "/sys/fs/cgroup"
DISK_QUOTA_GB = 10.0  # the sandbox plan's disk allowance (no cgroup quota exists for it)
_cpu_prev = {"usec": None, "ts": None}
_ws_cache = {"bytes": None, "ts": 0.0, "busy": False}
WS_TTL = 300.0  # refresh the /root footprint every 5 min


def _seed_cpu():
    """Take a baseline CPU reading at startup so the very first /stats call
    can already return a percentage instead of null."""
    u = _cpu_usage_usec()
    if u is not None:
        _cpu_prev["usec"], _cpu_prev["ts"] = u, time.time()


def _seed_workspace():
    """Warm the /root footprint cache in the background at startup."""
    try:
        _workspace_bytes(force=True)
    except Exception:
        pass


def _cgroup(path, default=None):
    try:
        with open(os.path.join(CPU_MOUNT, path)) as f:
            return f.read().strip()
    except Exception:
        return default


def _cpu_quota_cores():
    """cpu.max is '<quota> <period>' (e.g. '175000 100000' = 1.75 cores)."""
    raw = _cgroup("cpu.max")
    if not raw or raw == "max":
        return None
    try:
        q, per = raw.split()
        return int(q) / int(per)
    except Exception:
        return None


def _cpu_usage_usec():
    """Cumulative CPU time consumed by this sandbox, from cgroup cpu.stat."""
    try:
        with open(os.path.join(CPU_MOUNT, "cpu.stat")) as f:
            for line in f:
                if line.startswith("usage_usec"):
                    return int(line.split()[1])
    except Exception:
        pass
    return None


def _read_cpu():
    """Fallback: (busy, total) jiffies host-wide from /proc/stat."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        return sum(vals) - idle, sum(vals)
    except Exception:
        return None, None


def _workspace_bytes(force=False):
    """Cached size of /root (the sandbox's own footprint). Refreshed by a
    background thread because du over a few GB takes ~30s."""
    now = time.time()
    due = _ws_cache["bytes"] is None or (now - _ws_cache["ts"] > WS_TTL)
    if (force or due) and not _ws_cache["busy"]:
        _ws_cache["busy"] = True

        def _work():
            try:
                out = subprocess.run(["du", "-sxB1", "/root"], capture_output=True,
                                     text=True, timeout=600).stdout.split()
                _ws_cache["bytes"] = int(out[0])
                _ws_cache["ts"] = time.time()
            except Exception:
                pass
            finally:
                _ws_cache["busy"] = False

        threading.Thread(target=_work, daemon=True).start()
    return _ws_cache["bytes"]


def stats_snapshot():
    """CPU %, RAM %, disk % + the sandbox spec shown next to the bars.
    CPU/RAM come from cgroup v2 (the real sandbox quota, not host-wide numbers)."""
    now = time.time()
    quota = _cpu_quota_cores()

    # --- CPU: cgroup accounting over wall time, as % of the allowed cores ---
    cpu_pct = None
    usec = _cpu_usage_usec()
    if usec is not None and _cpu_prev["usec"] is not None:
        d_usec = usec - _cpu_prev["usec"]
        d_wall = now - _cpu_prev["ts"]
        if d_wall > 0:
            allowed_usec = d_wall * 1e6 * (quota or (os.cpu_count() or 1))
            cpu_pct = max(0.0, min(100.0, 100.0 * d_usec / allowed_usec))
    if usec is not None:
        _cpu_prev["usec"], _cpu_prev["ts"] = usec, now
    else:
        # fallback when cgroup accounting is unavailable: host-wide /proc/stat delta
        busy, total = _read_cpu()
        if busy is not None and _cpu_prev.get("hbusy") is not None:
            d_total = total - _cpu_prev["hbusy"]
            d_busy = busy - _cpu_prev["hbusy"]
            if d_total > 0:
                cpu_pct = max(0.0, min(100.0, 100.0 * d_busy / d_total))
        if busy is not None:
            _cpu_prev["hbusy"], _cpu_prev["htotal"] = busy, total

    # --- RAM: cgroup current/max, fall back to /proc/meminfo ---
    ram_used = ram_total = None
    cur, mx = _cgroup("memory.current"), _cgroup("memory.max")
    if cur and mx and mx != "max":
        try:
            ram_used, ram_total = int(cur), int(mx)
        except Exception:
            pass
    if not ram_total:
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k] = int(v.split()[0]) * 1024
            ram_total = info.get("MemTotal")
            ram_used = ram_total - info.get("MemAvailable", 0) if ram_total else None
        except Exception:
            pass

    def pct(used, total):
        if not used or not total:
            return None
        return max(0.0, min(100.0, 100.0 * used / total))

    # --- Disk: the sandbox's own footprint vs the plan allowance ---
    # There is no cgroup disk quota on this box (io.max is empty), and statvfs("/")
    # reports the 845 GB host overlay, which would be meaningless next to a
    # "10 GiB" label. So the bar is /root's real footprint over the plan quota,
    # and the host overlay numbers are reported separately for reference.
    disk = {"pct": None}
    ws = _workspace_bytes()
    quota_b = DISK_QUOTA_GB * (1024 ** 3)
    if ws:
        disk = {"pct": pct(ws, quota_b),
                "used_gb": round(ws / (1024 ** 3), 2),
                "total_gb": DISK_QUOTA_GB,
                "basis": "workspace(/root) vs plan quota"}
    try:
        st = os.statvfs("/")
        host_total = st.f_blocks * st.f_frsize
        host_used = host_total - st.f_bavail * st.f_frsize
        disk["host"] = {"pct": pct(host_used, host_total),
                        "used_gb": round(host_used / 1e9, 1),
                        "total_gb": round(host_total / 1e9, 1)}
    except Exception:
        pass

    def gb(n):
        return round(n / (1024 ** 3), 1) if n else None

    rp = pct(ram_used, ram_total)
    return {
        "cpu": {"pct": None if cpu_pct is None else round(cpu_pct, 1),
                "quota": None if not quota else round(quota * 100)},  # 175 = 1.75 cores
        "ram": {"pct": None if rp is None else round(rp, 1),
                "used_gb": gb(ram_used), "total_gb": gb(ram_total)},
        "disk": disk,
        "spec": {"ram": (str(gb(ram_total)) + " GiB") if ram_total else "6 GiB",
                 "cpu": (str(round(quota * 100)) + "%") if quota else "175%",
                 "disk": "10 GiB"},
        "updated": int(now),
    }


# ---- models.json CRUD ----
def load_models():
    try:
        return json.load(open(MODELS_JSON))
    except Exception:
        return {"providers": {}}


def save_models(data):
    with open(MODELS_JSON, "w") as f:
        json.dump(data, f, indent=2)


def save_secret(env_name, value):
    """Store a provider API key in provider-keys.env (chmod 600). The value
    is never logged or returned. Returns False on a bad env var name."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name or ""):
        return False
    lines = {}
    try:
        with open(KEYS_FILE) as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    lines[k] = v
    except FileNotFoundError:
        pass
    lines[env_name] = value
    with open(KEYS_FILE, "w") as f:
        for k, v in lines.items():
            f.write(f"{k}={v}\n")
    os.chmod(KEYS_FILE, 0o600)
    os.environ[env_name] = value
    return True



SETTINGS_JSON = os.path.expanduser("~/.pi/agent/settings.json")
MONID_FILE = os.path.expanduser("~/.config/monid/credentials.yaml")


def list_secrets():
    """Env names in provider-keys.env + whether each has a value.
    Values are never returned."""
    out = []
    try:
        with open(KEYS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out.append({"env_name": k.strip(), "set": bool(v.strip())})
    except FileNotFoundError:
        pass
    return out


def delete_secret(env_name):
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name or ""):
        return False
    try:
        with open(KEYS_FILE) as f:
            lines = [l for l in f if not (l.strip() and not l.strip().startswith("#")
                     and "=" in l and l.split("=", 1)[0].strip() == env_name)]
    except FileNotFoundError:
        return False
    with open(KEYS_FILE, "w") as f:
        f.writelines(lines)
    os.chmod(KEYS_FILE, 0o600)
    os.environ.pop(env_name, None)
    return True


def load_settings():
    try:
        return json.load(open(SETTINGS_JSON))
    except Exception:
        return {}


def save_settings(patch):
    data = load_settings()
    data.update(patch)
    with open(SETTINGS_JSON, "w") as f:
        json.dump(data, f, indent=2)
    return data


def monid_status():
    try:
        with open(MONID_FILE) as f:
            txt = f.read()
        m = re.search(r'key:\s*"([^"]+)"', txt)
        return {"set": bool(m and m.group(1) and m.group(1) != "PASTE_MONID_KEY_HERE")}
    except FileNotFoundError:
        return {"set": False}


def save_monid(key):
    key = (key or "").strip()
    if not key or '"' in key or "\n" in key:
        return False
    os.makedirs(os.path.dirname(MONID_FILE), exist_ok=True)
    with open(MONID_FILE, "w") as f:
        f.write('key: "%s"\nlabel: main\n' % key)
    os.chmod(MONID_FILE, 0o600)
    return True


ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pi Admin — keys &amp; models</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#16181d;--mut:#6b7280;--bd:#e3e6ea;--ac:#2563eb;--ok:#15803d;--bad:#dc2626}
@media (prefers-color-scheme:dark){:root{--bg:#0e1013;--card:#171a1f;--tx:#e7eaee;--mut:#9aa3ad;--bd:#262b33;--ac:#5b93ff}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--tx)}
.wrap{max-width:880px;margin:0 auto;padding:20px 14px 60px}
h1{font-size:21px;margin:4px 0 2px}h2{font-size:16px;margin:0 0 10px}
.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px;margin-bottom:14px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:7px 0;border-bottom:1px solid var(--bd)}
.row:last-child{border-bottom:none}
.row .grow{flex:1;min-width:130px}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:13px}
.mut{color:var(--mut);font-size:12.5px}
.badge{font-size:11.5px;padding:2px 8px;border-radius:99px;border:1px solid var(--bd)}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.no{color:var(--bad);border-color:var(--bad)}
button{background:var(--ac);color:#fff;border:none;border-radius:8px;padding:7px 13px;font-size:13.5px;cursor:pointer}
button.ghost{background:transparent;color:var(--tx);border:1px solid var(--bd)}
button.danger{background:transparent;color:var(--bad);border:1px solid var(--bad)}
button:disabled{opacity:.5}
input,select{background:var(--card);color:var(--tx);border:1px solid var(--bd);border-radius:8px;padding:8px 10px;font-size:14px}
input[type=password],input[type=text]{min-width:0}
input.num{width:110px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:9px;margin-bottom:10px}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--tx);color:var(--bg);padding:9px 16px;border-radius:9px;font-size:13.5px;display:none;max-width:90%;z-index:9}
.prov{font-weight:600;margin-top:8px}
.pick{max-height:320px;overflow:auto;border:1px solid var(--bd);border-radius:9px;padding:6px 10px;margin:10px 0}
.pick .row{padding:5px 0}
label.chk{display:flex;gap:7px;align-items:center;cursor:pointer}
.editbox{width:100%;display:none;gap:8px;flex-wrap:wrap;padding:6px 0}
</style></head><body><div class="wrap">
<h1>Pi Admin</h1>
<div class="sub">Keys &amp; models for your Pi sandbox. Keys are write-only — stored on the box, never shown back. Every action is locked behind your opening password.</div>

<div class="card" id="loginCard"><h2>Open Pi Admin</h2>
<div class="row"><input type="password" id="tok" class="grow" placeholder="Opening password">
<button onclick="saveTok()">Unlock</button></div>
<div class="mut">Your opening password unlocks this page. (The raw gateway token also works here.)</div></div>

<div id="app" style="display:none">
<div class="card"><h2>Status</h2>
<div class="row"><div class="grow">Gateway <span id="health" class="badge">…</span> <span class="mut" id="deflt"></span></div>
<button class="ghost" onclick="loadAll()">Refresh</button>
<button onclick="restartGw()">Restart gateway</button></div>
<div class="mut">Restart reloads keys and models. Needed after changing keys.</div></div>

<div class="card"><h2>Models</h2><div id="models"></div></div>

<div class="card"><h2>Add models — the proper way</h2>
<div class="grid">
<input id="am_provider" placeholder="provider name (e.g. openrouter)">
<input id="am_base" placeholder="base URL (https://…/v1)">
<input id="am_env" placeholder="key env name (e.g. OPENROUTER_API_KEY)">
<input id="am_key" type="password" placeholder="API key (blank = use stored key)">
<select id="am_api"><option value="openai-completions">API: OpenAI-compatible</option><option value="anthropic-messages">API: Anthropic</option></select>
</div>
<button onclick="loadProviderModels()">Load models from provider</button>
<span class="mut">Fetches the provider's live model list using your key — pick from real models instead of typing IDs.</span>
<div id="pickWrap" style="display:none">
<div class="row"><input id="pickSearch" class="grow" placeholder="Filter models…" oninput="filterPick()"></div>
<div class="pick" id="pickList"></div>
<div class="mut">For each ticked model: context = max input tokens, output = max output tokens. Pre-filled from the provider when it reports them — edit freely. R = reasoning/thinking model, V = vision (image input).</div>
<div class="row"><button onclick="addSelected()">Add ticked models</button></div>
</div>
<div class="row" style="margin-top:10px"><input id="mm_id" class="grow" placeholder="…or type a model id manually">
<input id="mm_ctx" class="num" type="number" placeholder="context" value="128000">
<input id="mm_out" class="num" type="number" placeholder="output" value="16384">
<label class="chk"><input type="checkbox" id="mm_r"> R</label>
<label class="chk"><input type="checkbox" id="mm_v"> V</label>
<button class="ghost" onclick="addManual()">Add this one</button></div>
</div>

<div class="card"><h2>Provider keys</h2><div id="keys"></div>
<div class="row"><input id="nk_env" class="grow" placeholder="New env name (e.g. OPENROUTER_API_KEY)">
<input id="nk_val" type="password" class="grow" placeholder="key value">
<button onclick="setKey(document.getElementById('nk_env').value,document.getElementById('nk_val').value)">Set key</button></div></div>

<div class="card"><h2>Monid search key</h2>
<div class="row"><div class="grow">Combined search inside the server (TinyFish free + DuckDuckGo) <span id="monidBadge" class="badge">…</span></div></div>
<div class="row"><input id="monid_key" type="password" class="grow" placeholder="mk_… key from your Monid dashboard">
<button onclick="setMonid()">Save Monid key</button></div></div>
</div></div>
<div id="toast"></div>
<script>
const $=id=>document.getElementById(id);
let TOK=sessionStorage.getItem('pigtok')||'';
let PICK=[];
function toast(m){const t=$('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',4600)}
async function api(path,opts={}){opts.headers=Object.assign({'Authorization':'Bearer '+TOK,'Content-Type':'application/json'},opts.headers||{});
 const r=await fetch(path,opts);let d={};try{d=await r.json()}catch(e){}
 if(r.status===401)throw new Error('bad token');if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d}
async function saveTok(){const v=$('tok').value.trim();if(!v)return;
 try{const r=await fetch('/admin-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:v})});
  if(r.ok){const d=await r.json();TOK=d.token;sessionStorage.setItem('pigtok',TOK);loadAll();return}}catch(e){}
 TOK=v;sessionStorage.setItem('pigtok',TOK);loadAll()}
async function loadAll(){try{
 const [models,secrets,settings,monid,health]=await Promise.all([api('/models'),api('/secrets'),api('/settings'),api('/monid'),api('/health')]);
 $('loginCard').style.display='none';$('app').style.display='block';
 $('health').textContent=health.ok?'running':'?';$('health').className='badge ok';
 $('deflt').textContent='Default: '+(settings.defaultProvider||'?')+'/'+(settings.defaultModel||'?');
 renderModels(models,settings);renderKeys(secrets.secrets||[],models);
 $('monidBadge').textContent=monid.set?'set':'not set';$('monidBadge').className='badge '+(monid.set?'ok':'no');
}catch(e){$('loginCard').style.display='block';$('app').style.display='none';if(TOK)toast(e.message)}}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function fmtN(n){if(!n)return '?';return n>=1000?Math.round(n/1000)+'k':String(n)}
function renderModels(data,settings){const el=$('models');el.innerHTML='';
 const provs=data.providers||{};
 Object.keys(provs).sort().forEach(p=>{const pv=provs[p];
  const h=document.createElement('div');h.className='prov';h.textContent=p;el.appendChild(h);
  const base=document.createElement('div');base.className='mut mono';base.textContent=(pv.baseUrl||'')+'  ·  key: '+(pv.apiKey||'(none)');el.appendChild(base);
  (pv.models||[]).forEach(m=>{const row=document.createElement('div');row.className='row';
   const isDef=settings.defaultProvider===p&&settings.defaultModel===m.id;
   row.innerHTML='<div class="grow"><span class="mono">'+esc(m.id)+'</span> '+(isDef?'<span class="badge ok">default</span>':'')+
    ' <span class="mut">ctx '+fmtN(m.contextWindow)+' · out '+fmtN(m.maxTokens)+(m.reasoning?' · reasoning':'')+((m.input||[]).includes('image')?' · vision':'')+'</span></div>';
   const eb=document.createElement('div');eb.className='editbox';
   eb.innerHTML='<input class="num ec" type="number" value="'+(m.contextWindow||'')+'" placeholder="context">'+
    '<input class="num eo" type="number" value="'+(m.maxTokens||'')+'" placeholder="output">'+
    '<input class="en" placeholder="display name" value="'+esc(m.name||'')+'">'+
    '<label class="chk"><input type="checkbox" class="er" '+(m.reasoning?'checked':'')+'> reasoning</label>'+
    '<label class="chk"><input type="checkbox" class="ev" '+(((m.input||[]).includes('image'))?'checked':'')+'> vision</label>';
   const sv=document.createElement('button');sv.textContent='Save';sv.onclick=()=>saveEdit(p,m.id,eb);
   eb.appendChild(sv);row.appendChild(eb);
   const b0=document.createElement('button');b0.className='ghost';b0.textContent='Edit';b0.onclick=()=>{eb.style.display=eb.style.display==='flex'?'none':'flex'};
   const b1=document.createElement('button');b1.className='ghost';b1.textContent='Make default';b1.onclick=()=>setDefault(p,m.id);
   const b2=document.createElement('button');b2.className='ghost';b2.textContent='Test';b2.onclick=ev=>testModel(p,m.id,ev.target);
   const b3=document.createElement('button');b3.className='danger';b3.textContent='Remove';b3.onclick=()=>delModel(p,m.id);
   row.append(b0,b1,b2,b3);el.appendChild(row)})})}
async function saveEdit(p,id,eb){const patch={contextWindow:parseInt(eb.querySelector('.ec').value)||undefined,
 maxTokens:parseInt(eb.querySelector('.eo').value)||undefined,reasoning:eb.querySelector('.er').checked,
 input:eb.querySelector('.ev').checked?['text','image']:['text']};
 const nm=eb.querySelector('.en').value.trim();if(nm)patch.name=nm;
 try{await api('/models/'+encodeURIComponent(p)+'/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify(patch)});toast('Saved '+id);loadAll()}catch(e){toast(e.message)}}
function renderKeys(secrets,models){const el=$('keys');el.innerHTML='';
 const names=new Set(secrets.map(s=>s.env_name));
 Object.values(models.providers||{}).forEach(pv=>{const k=(pv.apiKey||'').replace(/^\$/,'');if(k)names.add(k)});
 [...names].sort().forEach(n=>{const s=secrets.find(x=>x.env_name===n);const row=document.createElement('div');row.className='row';
  row.innerHTML='<div class="grow"><span class="mono">'+esc(n)+'</span> <span class="badge '+((s&&s.set)?'ok':'no')+'">'+((s&&s.set)?'set':'not set')+'</span></div>';
  const inp=document.createElement('input');inp.type='password';inp.placeholder='new value';inp.className='grow';
  const b=document.createElement('button');b.textContent='Set';b.onclick=()=>setKey(n,inp.value);
  const d=document.createElement('button');d.className='danger';d.textContent='Remove';d.onclick=()=>delKey(n);
  row.append(inp,b,d);el.appendChild(row)})}
async function loadProviderModels(){const base=$('am_base').value.trim(),env=$('am_env').value.trim(),key=$('am_key').value;
 if(!base||!env){toast('base URL and env name are required');return}
 try{const d=await api('/provider-models',{method:'POST',body:JSON.stringify({base_url:base,env_name:env,api_key:key})});
  PICK=d.models||[];$('pickWrap').style.display='block';renderPick(PICK);
  toast('Loaded '+PICK.length+' models from the provider')}catch(e){toast(e.message)}}
function renderPick(list){const el=$('pickList');el.innerHTML='';
 list.forEach(m=>{const row=document.createElement('div');row.className='row';row.dataset.mid=m.id;
  row.innerHTML='<label class="chk grow"><input type="checkbox" class="pc"> <span class="mono">'+esc(m.id)+'</span></label>'+
   '<input class="num px" type="number" value="'+(m.context||128000)+'" title="context">'+
   '<input class="num po" type="number" value="'+(m.output||16384)+'" title="output">'+
   '<label class="chk"><input type="checkbox" class="pr"> R</label><label class="chk"><input type="checkbox" class="pv"> V</label>';
  el.appendChild(row)});
 if(!list.length)el.innerHTML='<div class="mut">No models returned.</div>'}
function filterPick(){const q=$('pickSearch').value.toLowerCase();
 document.querySelectorAll('#pickList .row').forEach(r=>{r.style.display=r.dataset.mid.toLowerCase().includes(q)?'flex':'none'})}
function provFields(){return {provider:$('am_provider').value.trim(),baseUrl:$('am_base').value.trim(),
 api:$('am_api').value,env_name:$('am_env').value.trim(),api_key:$('am_key').value}}
async function addSelected(){const f=provFields();if(!f.provider){toast('provider name required');return}
 const rows=[...document.querySelectorAll('#pickList .row')].filter(r=>r.querySelector('.pc').checked);
 if(!rows.length){toast('tick at least one model');return}
 let n=0;for(const r of rows){const body=Object.assign({},f,{id:r.dataset.mid,
   contextWindow:parseInt(r.querySelector('.px').value)||128000,maxTokens:parseInt(r.querySelector('.po').value)||16384});
  if(r.querySelector('.pr').checked)body.reasoning=true;
  body.input=r.querySelector('.pv').checked?['text','image']:['text'];
  try{await api('/models',{method:'POST',body:JSON.stringify(body)});n++}catch(e){toast(e.message)}}
 toast('Added '+n+' model(s)'+(f.api_key?' — restart the gateway to load the new key':''));loadAll()}
async function addManual(){const f=provFields();const id=$('mm_id').value.trim();
 if(!f.provider||!id||!f.env_name){toast('provider, model id and env name are required');return}
 const body=Object.assign({},f,{id,contextWindow:parseInt($('mm_ctx').value)||128000,maxTokens:parseInt($('mm_out').value)||16384});
 if($('mm_r').checked)body.reasoning=true;body.input=$('mm_v').checked?['text','image']:['text'];
 try{await api('/models',{method:'POST',body:JSON.stringify(body)});toast('Added '+id);loadAll()}catch(e){toast(e.message)}}
async function setDefault(p,m){try{await api('/settings',{method:'POST',body:JSON.stringify({defaultProvider:p,defaultModel:m})});toast('Default is now '+p+'/'+m);loadAll()}catch(e){toast(e.message)}}
async function delModel(p,m){if(!confirm('Remove model '+p+'/'+m+'?'))return;try{await api('/models/'+encodeURIComponent(p)+'/'+encodeURIComponent(m),{method:'DELETE'});toast('Removed '+m);loadAll()}catch(e){toast(e.message)}}
async function setKey(env,val){env=(env||'').trim();if(!env||!val){toast('env name and value required');return}
 try{await api('/secrets',{method:'POST',body:JSON.stringify({env_name:env,api_key:val})});toast('Key saved for '+env+' — restart to apply');loadAll()}catch(e){toast(e.message)}}
async function delKey(env){if(!confirm('Remove key '+env+'? Models using it will fail until a new key is set.'))return;
 try{await api('/secrets/'+encodeURIComponent(env),{method:'DELETE'});toast('Key removed — restart to apply');loadAll()}catch(e){toast(e.message)}}
async function setMonid(){const v=$('monid_key').value.trim();if(!v){toast('paste the Monid key first');return}
 try{await api('/monid',{method:'POST',body:JSON.stringify({key:v})});toast('Monid key saved on the box');loadAll()}catch(e){toast(e.message)}}
async function restartGw(){try{await api('/restart',{method:'POST',body:'{}'});toast('Restarting…');}catch(e){}
 for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,1500));try{const h=await fetch('/health').then(r=>r.json());if(h.ok){toast('Gateway back up');loadAll();return}}catch(e){}}toast('Gateway did not answer — check again in a bit')}
async function testModel(p,m,btn){btn.disabled=true;btn.textContent='Testing…';
 try{const r=await api('/prompt',{method:'POST',body:JSON.stringify({message:'Say OK',model:p+'/'+m,name:'admin-test'})});
  const sid=r.session_id;let txt='';
  for(let i=0;i<30;i++){await new Promise(r2=>setTimeout(r2,2000));const s=await api('/sessions/'+sid+'/status');txt=s.last_assistant_text||'';if(txt)break}
  if(txt&&typeof txt!=='string'){try{txt=txt.text||JSON.stringify(txt)}catch(e){txt=String(txt)}}
  toast(txt?('Reply: '+String(txt).slice(0,120)):('No reply from '+m+' (key missing or provider down)'));
 }catch(e){toast(e.message)}btn.disabled=false;btn.textContent='Test'}
if(TOK){$('tok').value=TOK;loadAll()}
</script></body></html>
"""

# ---- HTTP ----
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _auth(self):
        if self.path == "/health":
            return True
        return self.headers.get("Authorization") == "Bearer " + TOKEN

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        _path = urlparse(self.path).path
        if _path in ("/pi", "/pi.html"):
            # Pi Chat. Served from pi.html next to this file so the page can be
            # updated without patching Python; the shell is public and holds no
            # secrets — every API call it makes is Bearer-authenticated.
            body = None
            try:
                with open(os.path.join(BASE, "pi.html"), "rb") as f:
                    body = f.read()
            except Exception:
                body = None
            if body is None:
                body = b"<!doctype html><meta charset=utf-8><title>Pi Chat</title>" \
                       b"<p style='font:15px system-ui;padding:24px'>pi.html is missing on the box." \
                       b" Copy it to /root/pi-bridge/pi.html and reload."
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return
        if _path == "/admin":
            # The admin page shell is public; every API call it makes is
            # Bearer-authenticated, and it contains no secrets.
            body = ADMIN_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._auth():
            return self._json(401, {"error": "unauthorized"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/health":
            return self._json(200, {"ok": True, "sessions_running": sum(1 for p in procs.values() if p["proc"].poll() is None)})
        if u.path == "/stats":
            return self._json(200, stats_snapshot())
        if u.path == "/sessions":
            return self._json(200, session_files())
        if u.path == "/models":
            return self._json(200, load_models())
        if u.path == "/secrets":
            return self._json(200, {"secrets": list_secrets()})
        if u.path == "/settings":
            s = load_settings()
            return self._json(200, {"defaultProvider": s.get("defaultProvider"),
                                    "defaultModel": s.get("defaultModel")})
        if u.path == "/monid":
            return self._json(200, monid_status())
        m = re.match(r"^/sessions/([^/]+)$", u.path)
        if m:
            sid = m.group(1)
            entry = ensure_proc(sid)
            msgs = rpc_call(entry, {"type": "get_messages"}, timeout=30)
            stats = rpc_call(entry, {"type": "get_session_stats"}, timeout=30)
            return self._json(200, {"id": sid, "messages": msgs, "stats": stats})
        m = re.match(r"^/sessions/([^/]+)/status$", u.path)
        if m:
            sid = m.group(1)
            entry = procs.get(sid)
            last = rpc_call(entry, {"type": "get_last_assistant_text"}, timeout=30) if entry and entry["proc"].poll() is None else None
            return self._json(200, {"id": sid, "running": bool(entry and entry["running"]),
                                    "last_assistant_text": (last or {}).get("data") if isinstance(last, dict) else last})
        m = re.match(r"^/sessions/([^/]+)/events$", u.path)
        if m:
            sid = m.group(1)
            since = int(q.get("since", ["0"])[0])
            entry = procs.get(sid)
            evs = entry["events"][since:] if entry else []
            try:
                with open(os.path.join(BASE, "sessions", sid + ".events.jsonl")) as f:
                    lines = f.readlines()
                if not entry:
                    evs = [json.loads(l) for l in lines[since:]]
            except Exception:
                pass
            return self._json(200, {"events": evs, "next": since + len(evs)})
        if u.path == "/files":
            rel = (q.get("path") or [""])[0]
            full = os.path.normpath(os.path.join(WORK, rel))
            if not full.startswith(WORK):
                return self._json(403, {"error": "path outside work dir"})
            try:
                with open(full) as f:
                    return self._json(200, {"path": rel, "content": f.read()})
            except FileNotFoundError:
                return self._json(404, {"error": "not found"})
        return self._json(404, {"error": "unknown route"})

    def do_POST(self):
        if urlparse(self.path).path == "/admin-login":
            now = time.time()
            st = LOGIN_FAILS.get("state", {"count": 0, "until": 0})
            if st["until"] > now:
                return self._json(429, {"error": "too many attempts — try again in a few minutes"})
            # Opening-password login for the admin page: returns the gateway
            # token when the SHA-256 of the password matches the hash in
            # gateway.env (PI_ADMIN_PASS_SHA256). Tailnet-only surface.
            body = self._body()
            pw = (body.get("password") or "").encode()
            digest = hashlib.sha256(pw).hexdigest()
            if ADMIN_PASS_SHA256 and hmac.compare_digest(digest, ADMIN_PASS_SHA256.strip().lower()):
                LOGIN_FAILS["state"] = {"count": 0, "until": 0}
                return self._json(200, {"token": TOKEN})
            st["count"] = st.get("count", 0) + 1
            if st["count"] >= 5:
                st = {"count": 0, "until": now + 600}
            LOGIN_FAILS["state"] = st
            return self._json(401, {"error": "wrong password"})
        if not self._auth():
            return self._json(401, {"error": "unauthorized"})
        u = urlparse(self.path)
        body = self._body()
        if u.path == "/prompt":
            sid = body.get("session_id")
            cwd = body.get("cwd", WORK)
            entry = ensure_proc(sid, cwd=cwd, model=body.get("model")) if sid else spawn_rpc(None, cwd, body.get("model"))
            if body.get("name") and not sid:
                rpc_call(entry, {"type": "set_session_name", "name": body["name"]}, timeout=15)
            cmd = {"type": "prompt", "message": body["message"]}
            if entry["running"]:
                cmd["streamingBehavior"] = "steer"
            res = rpc_call(entry, cmd, timeout=30)
            # discover the real session id
            state = rpc_call(entry, {"type": "get_state"}, timeout=15)
            real_sid = None
            try:
                real_sid = (state.get("data") or {}).get("sessionId") or (state.get("data") or {}).get("session", {}).get("id")
            except Exception:
                pass
            if real_sid and (sid or "new") != real_sid:
                with procs_lock:
                    procs[real_sid] = procs.pop(sid or "new")
                    procs[real_sid]["sid"] = real_sid
            return self._json(200, {"session_id": real_sid or sid, "response": res})
        m = re.match(r"^/sessions/([^/]+)/prompt$", u.path)
        if m:
            sid = m.group(1)
            entry = ensure_proc(sid)
            cmd = {"type": "prompt", "message": body["message"]}
            if entry["running"]:
                cmd["streamingBehavior"] = "steer"
            return self._json(200, rpc_call(entry, cmd, timeout=30))
        m = re.match(r"^/sessions/([^/]+)/stop$", u.path)
        if m:
            entry = procs.get(m.group(1))
            if entry and entry["proc"].poll() is None:
                return self._json(200, rpc_call(entry, {"type": "abort"}, timeout=15))
            return self._json(200, {"success": True, "note": "not running"})
        m = re.match(r"^/sessions/([^/]+)/rename$", u.path)
        if m:
            entry = ensure_proc(m.group(1))
            return self._json(200, rpc_call(entry, {"type": "set_session_name", "name": body["name"]}, timeout=15))
        m = re.match(r"^/sessions/([^/]+)/model$", u.path)
        if m:
            entry = ensure_proc(m.group(1))
            return self._json(200, rpc_call(entry, {"type": "set_model", "model": body["model"]}, timeout=30))
        m = re.match(r"^/sessions/([^/]+)/compact$", u.path)
        if m:
            entry = ensure_proc(m.group(1))
            return self._json(200, rpc_call(entry, {"type": "compact"}, timeout=60))
        if u.path == "/models":
            # Add a model; provider-level fields go on the provider, the rest
            # on the model entry. Optional api_key + env_name stores the key
            # in provider-keys.env and references it as $ENV_NAME only.
            data = load_models()
            data.setdefault("providers", {})
            prov = data["providers"].setdefault(body["provider"], {"models": []})
            for field in ("api", "baseUrl"):
                if field in body:
                    prov[field] = body[field]
            env_name = body.get("env_name")
            if env_name and body.get("api_key"):
                if save_secret(env_name, body["api_key"]):
                    prov["apiKey"] = "$" + env_name
                else:
                    return self._json(400, {"error": "bad env_name"})
            elif env_name:
                prov["apiKey"] = "$" + env_name
            elif body.get("apiKey"):
                prov["apiKey"] = body["apiKey"]
            model = {k: v for k, v in body.items()
                     if k not in ("provider", "api", "baseUrl", "apiKey", "env_name", "api_key")}
            if model.get("id"):
                prov.setdefault("models", [])
                if not any(m.get("id") == model["id"] for m in prov["models"]):
                    prov["models"].append(model)
            save_models(data)
            return self._json(200, {"ok": True, "providers": list(data["providers"])})
        if u.path == "/provider-models":
            # Fetch the provider's own /models list (from the box, using the
            # key given or the stored key for env_name) so the admin page can
            # offer real model IDs instead of blind typing.
            base = (body.get("base_url") or "").rstrip("/")
            if not base.startswith("https://"):
                return self._json(400, {"error": "base_url must start with https://"})
            key = body.get("api_key") or os.environ.get(body.get("env_name") or "", "")
            req = urllib.request.Request(base + "/models", headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                **({"Authorization": "Bearer " + key} if key else {})})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    raw = json.loads(r.read().decode()[:2_000_000])
            except Exception as e:
                return self._json(502, {"error": "provider /models failed: " + str(e)[:160]})
            items = raw.get("data") if isinstance(raw, dict) else raw
            out = []
            for it in items or []:
                if not isinstance(it, dict) or not it.get("id"):
                    continue
                ctx = it.get("context_length") or it.get("contextWindow") or it.get("max_context_tokens") or it.get("context")
                outp = it.get("max_output_tokens") or it.get("maxTokens") or it.get("max_completion_tokens")
                top = it.get("top_provider") or {}
                if not ctx:
                    ctx = top.get("context_length")
                if not outp:
                    outp = top.get("max_completion_tokens")
                out.append({"id": it["id"], "context": ctx, "output": outp,
                            "name": it.get("name") if isinstance(it.get("name"), str) else None})
            return self._json(200, {"models": out, "count": len(out)})
        if u.path == "/secrets":
            # Store a provider API key (never logged, never returned).
            env_name, value = body.get("env_name"), body.get("api_key")
            if not env_name or not value:
                return self._json(400, {"error": "env_name and api_key required"})
            if not save_secret(env_name, value):
                return self._json(400, {"error": "bad env_name"})
            return self._json(200, {"ok": True, "env_name": env_name})
        if u.path == "/settings":
            patch = {k: body[k] for k in ("defaultProvider", "defaultModel") if body.get(k)}
            if not patch:
                return self._json(400, {"error": "defaultProvider/defaultModel required"})
            s = save_settings(patch)
            return self._json(200, {"ok": True, "defaultProvider": s.get("defaultProvider"),
                                    "defaultModel": s.get("defaultModel")})
        if u.path == "/monid":
            if not save_monid(body.get("key")):
                return self._json(400, {"error": "bad key"})
            return self._json(200, {"ok": True})
        if u.path == "/restart":
            # Restart the gateway itself (new process re-reads provider keys
            # and models.json). Terminates live RPC sessions first.
            def _restart():
                time.sleep(2)
                for e in list(procs.values()):
                    try:
                        e["proc"].terminate()
                    except Exception:
                        pass
                subprocess.Popen(
                    ["sh", "-c", "tmux kill-session -t pi-gateway 2>/dev/null; sleep 1; tmux new -s pi-gateway -d 'python3 /root/pi-bridge/pi-gateway.py'"],
                    start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Thread(target=_restart, daemon=True).start()
            return self._json(200, {"ok": True, "restarting": True})
        if u.path == "/rpc":
            sid = body.get("session_id")
            entry = ensure_proc(sid) if sid else spawn_rpc(None, WORK)
            return self._json(200, rpc_call(entry, body["command"], timeout=60))
        return self._json(404, {"error": "unknown route"})

    def do_PATCH(self):
        if not self._auth():
            return self._json(401, {"error": "unauthorized"})
        m = re.match(r"^/models/([^/]+)/([^/]+)$", urlparse(self.path).path)
        if not m:
            return self._json(404, {"error": "unknown route"})
        body = self._body()
        data = load_models()
        models = data.get("providers", {}).get(m.group(1), {}).get("models", [])
        for mdl in models:
            if mdl.get("id") == m.group(2):
                mdl.update(body)
                save_models(data)
                return self._json(200, {"ok": True, "model": mdl})
        return self._json(404, {"error": "model not found"})

    def do_DELETE(self):
        if not self._auth():
            return self._json(401, {"error": "unauthorized"})
        u = urlparse(self.path)
        m = re.match(r"^/sessions/([^/]+)$", u.path)
        if m:
            sid = m.group(1)
            with procs_lock:
                e = procs.pop(sid, None)
            if e and e["proc"].poll() is None:
                e["proc"].terminate()
            try:
                os.remove(os.path.join(SESSIONS_DIR, sid + ".jsonl"))
            except FileNotFoundError:
                pass
            return self._json(200, {"ok": True})
        m = re.match(r"^/secrets/([^/]+)$", u.path)
        if m:
            if not delete_secret(m.group(1)):
                return self._json(400, {"error": "bad env_name"})
            return self._json(200, {"ok": True})
        m = re.match(r"^/models/([^/]+)/([^/]+)$", u.path)
        if m:
            data = load_models()
            models = data.get("providers", {}).get(m.group(1), {}).get("models", [])
            data["providers"][m.group(1)]["models"] = [x for x in models if x.get("id") != m.group(2)]
            save_models(data)
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "unknown route"})


if __name__ == "__main__":
    # Seed the CPU baseline and warm the /root footprint cache so the first
    # /stats call already returns real numbers instead of nulls.
    _seed_cpu()
    _seed_workspace()
    print(f"pi-gateway listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
