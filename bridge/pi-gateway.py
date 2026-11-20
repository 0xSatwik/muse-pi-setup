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

# ---- Model fallback (auto-switch) ----
# Ordered chain of "provider/modelId". When a session's turn dies on a
# provider error, the watchdog below switches that session to the next
# model in the chain and prompts it to continue with full context.
# Editable from the admin page; stored beside this file, not in Pi's
# own settings.json.
FALLBACK_FILE = os.path.join(BASE, "fallback.json")
FALLBACK_DEFAULT = {"enabled": True,
                    "chain": ["provider-a/model-1", "provider-b/model-2"]}
LAST_SWITCH = {}


def load_fallback():
    try:
        with open(FALLBACK_FILE) as f:
            d = json.load(f)
        chain = [c for c in d.get("chain", []) if isinstance(c, str) and "/" in c]
        return {"enabled": bool(d.get("enabled", True)),
                "chain": chain or list(FALLBACK_DEFAULT["chain"])}
    except Exception:
        return {"enabled": FALLBACK_DEFAULT["enabled"], "chain": list(FALLBACK_DEFAULT["chain"])}


def save_fallback(cfg):
    tmp = FALLBACK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, FALLBACK_FILE)
    return cfg

# ---- RPC process management ----
procs = {}          # session_id -> {"proc", "reader", "pending", "events", "lock", "cwd", "running"}
procs_lock = threading.Lock()


def log_event(sid, rec):
    p = procs.get(sid)
    if p is None:
        return
    p["events"].append(rec)
    p["last_event_at"] = time.time()
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
                    p["last_error"] = None
                elif t in ("agent_end", "agent_settled"):
                    p["running"] = False
                    p["agent_ends"] = p.get("agent_ends", 0) + 1
                elif t == "message_end":
                    msg = rec.get("message") or {}
                    if msg.get("stopReason") == "error":
                        p["last_error"] = {"error": msg.get("errorMessage") or "provider error (no message)",
                                           "at": msg.get("timestamp")}
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
             "cwd": cwd, "running": False, "sid": sid, "last_error": None,
             "last_event_at": 0, "fb_handled_at": None,
             "agent_ends": 0, "spawned_at": time.time(),
             "ac_last_end_count": -1, "ac_unproductive": 0, "ac_fingerprint": None}
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


FB_ERROR_HINTS = ("503", "502", "500", "upstream", "busy", "overloaded",
                  "unavailable", "timed out", "timeout", "econnreset",
                  "fetch failed", "socket hang", "rate limit", "429")


def _is_provider_error(err):
    e = (err or "").lower()
    return any(h in e for h in FB_ERROR_HINTS)


def _current_model(entry):
    st = rpc_call(entry, {"type": "get_state"}, timeout=30)
    model = ((st or {}).get("data") or {}).get("model") or {}
    prov = model.get("provider")
    mid = model.get("id") or model.get("modelId")
    return (prov + "/" + mid) if prov and mid else None


def fallback_watchdog():
    """When a session's turn has died on a provider error and stayed idle,
    switch it to the next model in the fallback chain and continue it."""
    while True:
        time.sleep(15)
        try:
            cfg = load_fallback()
            if not cfg["enabled"] or len(cfg["chain"]) < 2:
                continue
            now = time.time()
            for sid, entry in list(procs.items()):
                try:
                    if entry["proc"].poll() is not None or entry.get("running"):
                        continue
                    le = entry.get("last_error")
                    if not le or entry.get("fb_handled_at") == le.get("at"):
                        continue
                    if not _is_provider_error(le.get("error")):
                        entry["fb_handled_at"] = le.get("at")
                        continue
                    # Let Pi's own retries settle first: the error and the
                    # session's last event must both be at least 45s old.
                    err_at = (le.get("at") or 0) / 1000.0
                    if (err_at and now - err_at < 45) or now - (entry.get("last_event_at") or 0) < 45:
                        continue
                    cur = _current_model(entry)
                    chain = cfg["chain"]
                    if cur in chain:
                        idx = chain.index(cur)
                        nxt = chain[idx + 1] if idx + 1 < len(chain) else None
                    else:
                        nxt = chain[0] if chain[0] != cur else None
                    entry["fb_handled_at"] = le.get("at")
                    if not nxt:
                        continue
                    prov, mid = nxt.split("/", 1)
                    rpc_call(entry, {"type": "set_model", "provider": prov, "modelId": mid}, timeout=30)
                    if _current_model(entry) != nxt:
                        continue
                    LAST_SWITCH.clear()
                    LAST_SWITCH.update({"session": sid, "from": cur, "to": nxt, "at": int(now)})
                    rpc_call(entry, {"type": "prompt", "message":
                                     "Continue from where you left off. (Auto-fallback: the previous model hit a provider error, so this session was switched to " + nxt + ". You have the full conversation context.)"}, timeout=30)
                except Exception:
                    continue
        except Exception:
            continue


# ---- Auto-continue ----
# Pi works the master task file /root/work/agentx/TASKS.md top to bottom,
# but a Pi turn ENDS when the session reports — after that, silence until
# a human (or the supervisor cron, every ~30 min) nudges it. This
# watchdog closes the gap: when a configured work session has ended a
# turn and stayed idle a while, and TASKS.md still holds work for it,
# the gateway sends the standard continue prompt itself. Guardrails:
# never fire on a provider-error death (the fallback watchdog owns
# those); never fire when no work remains (queue done, or only the
# owner-only section is left); stop after a few consecutive continues
# that changed nothing in TASKS.md — the session is blocked, not lazy,
# and the supervisor cron takes it from there. Config lives beside this
# file like fallback.json; the session ids live only in that file.
AC_FILE = os.path.join(BASE, "autocontinue.json")
AC_DEFAULT = {"enabled": True, "idle_seconds": 90, "max_unproductive": 3,
              "tasks_file": "/root/work/agentx/TASKS.md", "sessions": {}}
LAST_AUTOCONTINUE = {}
AC_PROMPT = ("Continue from where you left off. Keep working through "
             "/root/work/agentx/TASKS.md per its rules: finish your claimed task, "
             "mark it [x] in the file when its definition of done is met, then claim "
             "the next unclaimed task and keep going. Report what you finished and "
             "what remains, then stop. (Auto-continue: you stopped with work left in "
             "the file, so the gateway restarted you — no human sent this.)")


def load_autocontinue():
    try:
        with open(AC_FILE) as f:
            d = json.load(f)
        sessions = d.get("sessions") or {}
        if not isinstance(sessions, dict):
            sessions = {}
        return {"enabled": bool(d.get("enabled", True)),
                "idle_seconds": max(30, int(d.get("idle_seconds", 90))),
                "max_unproductive": max(1, int(d.get("max_unproductive", 3))),
                "tasks_file": d.get("tasks_file") or AC_DEFAULT["tasks_file"],
                "sessions": sessions}
    except Exception:
        return {"enabled": AC_DEFAULT["enabled"],
                "idle_seconds": AC_DEFAULT["idle_seconds"],
                "max_unproductive": AC_DEFAULT["max_unproductive"],
                "tasks_file": AC_DEFAULT["tasks_file"], "sessions": {}}


def save_autocontinue(cfg):
    tmp = AC_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, AC_FILE)
    return cfg


def _ac_work_state(tasks_file, tag):
    """Read TASKS.md; return (fingerprint, work_left) for one session tag.
    Work left = the session's own claimed [~] task, or any unclaimed [ ]
    task above the owner-only section. The fingerprint captures the queue
    counts so an unchanged file across continues reads as 'blocked'."""
    try:
        with open(tasks_file) as f:
            lines = f.read().splitlines()
    except Exception:
        return None, False
    done = claimed_mine = unclaimed = blocked = 0
    in_owner = False
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if s.startswith("#") and ("owner-only" in low or "do not start" in low):
            in_owner = True
        if s.startswith("- [x]") or s.startswith("- [X]"):
            done += 1
        elif s.startswith("- [!]"):
            blocked += 1
        elif s.startswith("- [~]"):
            if ("(" + tag + ")") in s or ("[" + tag + "]") in s:
                claimed_mine += 1
        elif s.startswith("- [ ]") and not in_owner:
            unclaimed += 1
    return (done, claimed_mine, unclaimed, blocked), (claimed_mine > 0 or unclaimed > 0)


def autocontinue_watchdog():
    """When a work session's turn has ended and work remains in TASKS.md,
    prompt it to continue — no human or cron nudge needed."""
    while True:
        time.sleep(15)
        try:
            cfg = load_autocontinue()
            if not cfg["enabled"] or not cfg["sessions"]:
                continue
            now = time.time()
            for sid, meta in list(cfg["sessions"].items()):
                try:
                    entry = procs.get(sid)
                    if entry is None or entry["proc"].poll() is not None:
                        # No live proc (e.g. the gateway restarted): resume
                        # the session from disk so the idle gate below can
                        # restart its work — the watchdog is the spawner of
                        # last resort, nothing else respawns these procs.
                        entry = ensure_proc(sid)
                    if entry.get("running"):
                        continue
                    tag = (meta or {}).get("tag") or ""
                    if not tag:
                        continue
                    # Provider-error deaths belong to the fallback watchdog.
                    le = entry.get("last_error")
                    if le and _is_provider_error(le.get("error")):
                        continue
                    # A turn must have ended since the last auto-continue
                    # (a fresh proc counts once: agent_ends 0 > -1, so work
                    # sessions also self-resume after a gateway restart).
                    ends = entry.get("agent_ends", 0)
                    if ends <= entry.get("ac_last_end_count", -1):
                        continue
                    idle_from = max(entry.get("last_event_at") or 0,
                                    entry.get("spawned_at") or 0)
                    if now - idle_from < cfg["idle_seconds"]:
                        continue
                    fp, work_left = _ac_work_state(cfg["tasks_file"], tag)
                    if fp is None:
                        continue
                    entry["ac_last_end_count"] = ends
                    if not work_left:
                        entry["ac_unproductive"] = 0
                        entry["ac_fingerprint"] = fp
                        continue
                    if entry.get("ac_fingerprint") == fp:
                        entry["ac_unproductive"] = entry.get("ac_unproductive", 0) + 1
                    else:
                        entry["ac_unproductive"] = 0
                    entry["ac_fingerprint"] = fp
                    if entry["ac_unproductive"] >= cfg["max_unproductive"]:
                        # Turns keep ending and the file never changes:
                        # blocked, not lazy. Leave it for the supervisor.
                        continue
                    rpc_call(entry, {"type": "prompt", "message": AC_PROMPT}, timeout=30)
                    LAST_AUTOCONTINUE.clear()
                    LAST_AUTOCONTINUE.update({"session": sid, "tag": tag, "at": int(now),
                                              "unproductive": entry["ac_unproductive"]})
                except Exception:
                    continue
        except Exception:
            continue


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

<div class="card"><h2>Model fallback order</h2>
<div class="mut">When a session's model hits a provider error (busy, 5xx, timeout), the session auto-switches to the next model in this order and continues with the full context. Put the models in the order you want them tried. Only models whose provider has a key can actually work.</div>
<div class="row"><label><input type="checkbox" id="fb_enabled" onchange="fbToggle()"> Auto-switch enabled</label></div>
<div id="fb_list"></div>
<div class="row"><select id="fb_add" class="grow"></select><button onclick="fbAdd()">Add to order</button></div>
<div class="mut" id="fb_last"></div>
</div>

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
 const [models,secrets,settings,monid,health,fallback]=await Promise.all([api('/models'),api('/secrets'),api('/settings'),api('/monid'),api('/health'),api('/fallback')]);
 $('loginCard').style.display='none';$('app').style.display='block';
 $('health').textContent=health.ok?'running':'?';$('health').className='badge ok';
 $('deflt').textContent='Default: '+(settings.defaultProvider||'?')+'/'+(settings.defaultModel||'?');
 renderModels(models,settings);renderKeys(secrets.secrets||[],models);renderFallback(fallback,models);
 $('monidBadge').textContent=monid.set?'set':'not set';$('monidBadge').className='badge '+(monid.set?'ok':'no');
}catch(e){$('loginCard').style.display='block';$('app').style.display='none';if(TOK)toast(e.message)}}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
let FB={enabled:true,chain:[]};
function renderFallback(fb,models){FB={enabled:!!fb.enabled,chain:(fb.chain||[]).slice()};
 $('fb_enabled').checked=FB.enabled;
 const el=$('fb_list');el.innerHTML='';
 FB.chain.forEach((c,i)=>{const row=document.createElement('div');row.className='row';
  row.innerHTML='<span class="grow">'+(i+1)+'. '+esc(c)+'</span>';
  const up=document.createElement('button');up.className='ghost';up.textContent='↑';up.disabled=!i;up.onclick=()=>fbMove(i,-1);
  const dn=document.createElement('button');dn.className='ghost';dn.textContent='↓';dn.disabled=i===FB.chain.length-1;dn.onclick=()=>fbMove(i,1);
  const rm=document.createElement('button');rm.className='ghost';rm.textContent='✕';rm.onclick=()=>fbRemove(i);
  row.append(up,dn,rm);el.append(row)});
 const sel=$('fb_add');sel.innerHTML='';
 const provs=(models&&models.providers)||{};
 Object.keys(provs).forEach(p=>{(provs[p].models||[]).forEach(m=>{const v=p+'/'+m.id;
  if(!FB.chain.includes(v)){const o=document.createElement('option');o.value=v;o.textContent=v;sel.append(o)}})});
 const ls=fb.lastSwitch;
 $('fb_last').textContent=ls?('Last auto-switch: '+(ls.from||'?')+' → '+ls.to+' · '+new Date(ls.at*1000).toLocaleTimeString()):'No auto-switch yet.'}
async function fbSave(){try{await api('/fallback',{method:'POST',body:JSON.stringify({enabled:FB.enabled,chain:FB.chain})});toast('Fallback order saved')}catch(e){toast(e.message)}}
async function fbMove(i,d){const j=i+d;if(j<0||j>=FB.chain.length)return;const t=FB.chain[i];FB.chain[i]=FB.chain[j];FB.chain[j]=t;await fbSave();loadAll()}
async function fbRemove(i){FB.chain.splice(i,1);await fbSave();loadAll()}
async function fbAdd(){const v=$('fb_add').value;if(!v)return;FB.chain.push(v);await fbSave();loadAll()}
async function fbToggle(){FB.enabled=$('fb_enabled').checked;await fbSave();loadAll()}
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
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if urlparse(self.path).path == "/admin":
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
        if u.path == "/fallback":
            cfg = load_fallback()
            cfg["lastSwitch"] = dict(LAST_SWITCH) if LAST_SWITCH else None
            return self._json(200, cfg)
        if u.path == "/autocontinue":
            cfg = load_autocontinue()
            cfg["lastContinue"] = dict(LAST_AUTOCONTINUE) if LAST_AUTOCONTINUE else None
            return self._json(200, cfg)
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
                                    "last_error": entry.get("last_error") if entry else None,
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
        if u.path == "/fallback":
            cfg = load_fallback()
            if isinstance(body.get("enabled"), bool):
                cfg["enabled"] = body["enabled"]
            if isinstance(body.get("chain"), list):
                cfg["chain"] = [c for c in body["chain"] if isinstance(c, str) and "/" in c]
            return self._json(200, save_fallback(cfg))
        if u.path == "/autocontinue":
            cfg = load_autocontinue()
            if isinstance(body.get("enabled"), bool):
                cfg["enabled"] = body["enabled"]
            if isinstance(body.get("idle_seconds"), int):
                cfg["idle_seconds"] = max(30, body["idle_seconds"])
            if isinstance(body.get("max_unproductive"), int):
                cfg["max_unproductive"] = max(1, body["max_unproductive"])
            return self._json(200, save_autocontinue(cfg))
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
    print(f"pi-gateway listening on {HOST}:{PORT}", flush=True)
    threading.Thread(target=fallback_watchdog, daemon=True).start()
    threading.Thread(target=autocontinue_watchdog, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
