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
  POST /restart                       restart the gateway (reloads keys)
  PATCH /models/{provider}/{id} {..}  edit a model entry
  DELETE /models/{provider}/{id}      remove a model entry
  POST /rpc {session_id, command}     raw RPC passthrough, any command
  GET  /files?path=<relpath>          pull a file from /root/work
  POST /sessions/{id}/compact         compact session context

Run: PI_GATEWAY_TOKEN set via /root/pi-bridge/gateway.env
  python3 /root/pi-bridge/pi-gateway.py   (tmux: pi-gateway)
"""
import json, os, re, subprocess, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
if not TOKEN:
    print("no PI_GATEWAY_TOKEN in gateway.env or env", file=sys.stderr)
    sys.exit(1)

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
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if not self._auth():
            return self._json(401, {"error": "unauthorized"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/health":
            return self._json(200, {"ok": True, "sessions_running": sum(1 for p in procs.values() if p["proc"].poll() is None)})
        if u.path == "/sessions":
            return self._json(200, session_files())
        if u.path == "/models":
            return self._json(200, load_models())
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
        if u.path == "/secrets":
            # Store a provider API key (never logged, never returned).
            env_name, value = body.get("env_name"), body.get("api_key")
            if not env_name or not value:
                return self._json(400, {"error": "env_name and api_key required"})
            if not save_secret(env_name, value):
                return self._json(400, {"error": "bad env_name"})
            return self._json(200, {"ok": True, "env_name": env_name})
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
        m = re.match(r"^/models/([^/]+)/([^/]+)$", u.path)
        if m:
            data = load_models()
            models = data.get("providers", {}).get(m.group(1), {}).get("models", [])
            data["providers"][m.group(1)]["models"] = [x for x in models if x.get("id") != m.group(2)]
            save_models(data)
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "unknown route"})


if __name__ == "__main__":
    print(f"pi-gateway listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
