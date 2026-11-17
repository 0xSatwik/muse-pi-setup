#!/usr/bin/env python3
"""muse-pi — Muse's tool to call Pi on the Altare sandbox, no SSH needed.

Transport: Altare Files API (team token, servers:files scope).
Muse writes a job JSON to the sandbox's inbox, the watcher on the
sandbox (tmux session `pi-bridge`, /root/pi-bridge/watcher.py) runs
`pi --model <model> -p "<prompt>"` and writes the result to outbox.
Muse polls outbox and prints Pi's answer.

Usage:
  python3 muse-pi.py ask  --model moss/nex-n2.6 --prompt "Say OK" [--timeout 900]
  python3 muse-pi.py send --model xingchi/gpt-6.1-sol --prompt "Build ..."   # long task, returns id at once
  python3 muse-pi.py get <id>        # fetch a long task's result later
  python3 muse-pi.py list            # inbox / outbox / done
  python3 muse-pi.py status          # watcher log tail + queue counts
  python3 muse-pi.py put <local> <remote-rel-path>   # send a file to /root/work/
  python3 muse-pi.py getfile <remote-rel-path> [local]  # bring a file back
Models (Pi on Altare, ~/.pi/agent/models.json):
  xingchi/gpt-6-astra, xingchi/gpt-6.1-sol,
  tokenlab/DeepSeek-V4.1-Flash, moss/nex-n2.6,
  howtofix/deepSeek-v4.1-flash-1017-sg, 100milionseek/deepseek-v4.1-flash-free
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://console.altare.gg/api"
# Your Altare team and server IDs (Altare console → server details).
# Set them as environment variables; never hardcode them in a shared copy.
TEAM = os.environ.get("ALTARE_TEAM", "")
SERVER = os.environ.get("ALTARE_SERVER", "")
if not TEAM or not SERVER:
    raise SystemExit("Set ALTARE_TEAM and ALTARE_SERVER (your Altare team and sandbox server IDs).")
# Files API paths are under /rootfs (= sandbox filesystem root)
BRIDGE = "/rootfs/root/pi-bridge"
WORK = "/rootfs/root/work"
MODELS = ["xingchi/gpt-6-astra", "xingchi/gpt-6.1-sol",
          "tokenlab/DeepSeek-V4.1-Flash", "moss/nex-n2.6",
          "howtofix/deepSeek-v4.1-flash-1017-sg",
          "100milionseek/deepseek-v4.1-flash-free"]


def _auth(req):
    # Prefer a plain Altare API token when given; otherwise mint a surrogate
    # from the connected Altare Platform credential (Muse connector).
    token = os.environ.get("ALTARE_API_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        return
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    try:
        from dynamic_credentials import add_surrogate_to_request
    except ImportError:
        raise SystemExit("No ALTARE_API_TOKEN set and the Altare Platform connector is not available. Set ALTARE_API_TOKEN or connect Altare Platform.")
    add_surrogate_to_request(req, "custom.altare-platform", allowed_hosts=["console.altare.gg"])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    req.add_header("Accept", "application/json")
    _auth(req)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError, TimeoutError) as e:
        if isinstance(e, urllib.error.HTTPError):
            raw = e.read().decode(errors="replace")
            if e.code == 404:
                return None
            if e.code not in (502, 503, 429):
                raise RuntimeError(f"Altare API HTTP {e.code}: {raw[:500]}")
        # Altare origin is flaky (Cloudflare 502, remote disconnects); retry after 65s
        for attempt in (1, 2):
            time.sleep(65)
            try:
                req2 = urllib.request.Request(BASE + path, data=data, method=method)
                for k, v in req.header_items():
                    req2.add_header(k, v)
                with urllib.request.build_opener(NoRedirect()).open(req2, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e2:
                raw = e2.read().decode(errors="replace")
                if e2.code == 404:
                    return None
                if attempt == 2:
                    raise RuntimeError(f"Altare API HTTP {e2.code}: {raw[:500]}")
                continue
            except Exception:
                if attempt == 2:
                    raise
                continue
        raise RuntimeError(f"Altare API failed: {e}")


def write_file(path, content):
    return call("POST", f"/tenants/{TEAM}/servers/{SERVER}/files/write",
                {"path": path, "content": content})


def read_file(path):
    r = call("GET", f"/tenants/{TEAM}/servers/{SERVER}/files/contents?path={urllib.parse.quote(path)}")
    return r["content"] if r else None


def list_dir(path):
    r = call("GET", f"/tenants/{TEAM}/servers/{SERVER}/files?path={urllib.parse.quote(path)}")
    return [i["name"] for i in r["items"]] if r else []


def new_id():
    return "pi-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + str(int(time.time() * 1000) % 10000)


def send(model, prompt, timeout=1800):
    if model not in MODELS:
        print(f"warning: {model} not in known list {MODELS}", file=sys.stderr)
    jid = new_id()
    job = {"id": jid, "model": model, "prompt": prompt,
           "timeout": timeout, "cwd": f"/root/work/{jid}"}
    write_file(f"{BRIDGE}/inbox/{jid}.json", json.dumps(job, indent=2))
    return jid


def get(jid):
    raw = read_file(f"{BRIDGE}/outbox/{jid}.json")
    return json.loads(raw) if raw else None


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask"); a.add_argument("--model", required=True); a.add_argument("--prompt", required=True); a.add_argument("--timeout", type=int, default=900)
    s = sub.add_parser("send"); s.add_argument("--model", required=True); s.add_argument("--prompt", required=True); s.add_argument("--timeout", type=int, default=3600)
    g = sub.add_parser("get"); g.add_argument("id")
    sub.add_parser("list"); sub.add_parser("status")
    pu = sub.add_parser("put"); pu.add_argument("local"); pu.add_argument("remote")
    gf = sub.add_parser("getfile"); gf.add_argument("remote"); gf.add_argument("local", nargs="?")
    args = p.parse_args()

    if args.cmd == "send":
        jid = send(args.model, args.prompt, args.timeout)
        print(json.dumps({"id": jid, "model": args.model, "status": "queued",
                          "get_with": f"python3 muse-pi.py get {jid}"}))
    elif args.cmd == "ask":
        jid = send(args.model, args.prompt, args.timeout)
        print(f"queued {jid} model={args.model} — waiting up to {args.timeout}s…", file=sys.stderr)
        deadline = time.time() + args.timeout + 60
        while time.time() < deadline:
            time.sleep(10)
            res = get(jid)
            if res:
                print(res.get("output", ""))
                if res.get("stderr"):
                    print(f"\n[stderr] {res['stderr']}", file=sys.stderr)
                print(f"\n[pi-bridge] id={jid} status={res['status']} exit={res.get('exit_code')}", file=sys.stderr)
                sys.exit(0 if res["status"] == "done" else 1)
        print(f"timeout waiting for {jid}; fetch later with: python3 muse-pi.py get {jid}", file=sys.stderr)
        sys.exit(2)
    elif args.cmd == "get":
        res = get(args.id)
        if res:
            print(res.get("output", ""))
            print(f"\n[pi-bridge] id={args.id} status={res['status']} exit={res.get('exit_code')}", file=sys.stderr)
            sys.exit(0 if res["status"] == "done" else 1)
        print(f"no result yet for {args.id} — still running or unknown id. Check: python3 muse-pi.py list", file=sys.stderr)
        sys.exit(2)
    elif args.cmd == "list":
        print(json.dumps({
            "inbox": list_dir(f"{BRIDGE}/inbox"),
            "outbox": list_dir(f"{BRIDGE}/outbox"),
            "done": list_dir(f"{BRIDGE}/done"),
        }, indent=2))
    elif args.cmd == "status":
        log = read_file(f"{BRIDGE}/watcher.log") or "(no watcher.log — watcher not started?)"
        print(json.dumps({
            "inbox": list_dir(f"{BRIDGE}/inbox"),
            "outbox": list_dir(f"{BRIDGE}/outbox"),
            "watcher_log_tail": log[-2000:],
        }, indent=2))
    elif args.cmd == "put":
        content = Path(args.local).read_text()
        write_file(f"{WORK}/{args.remote}", content)
        print(f"uploaded {args.local} -> /root/work/{args.remote} ({len(content)} bytes)")
    elif args.cmd == "getfile":
        content = read_file(f"{WORK}/{args.remote}")
        if content is None:
            print(f"not found: /root/work/{args.remote}", file=sys.stderr); sys.exit(1)
        dest = Path(args.local) if args.local else Path("downloads") / Path(args.remote).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        print(f"downloaded /root/work/{args.remote} -> {dest} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
