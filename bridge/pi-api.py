#!/usr/bin/env python3
"""pi-api.py — Muse-side client for the Pi gateway (Altare sandbox or Hoody computer).
Config lives next to this script: hoody-url.txt (preferred if present),
tailnet-url.txt, or public-url.txt, plus gateway-token.txt (chmod 600,
never in chat). The :3130 tunnel proxy applies only to tailnet (100.x)
URLs; a Hoody https URL goes direct.
Usage: pi-api.py health | sessions | models | prompt "msg" [--session ID] [--model M]
       pi-api.py status <id> | events <id> | stop <id> | files <path>
"""
import json, os, sys, urllib.request
# Config lives next to this script: hoody-url.txt, tailnet-url.txt, or
# public-url.txt (first one found, in that order), plus gateway-token.txt
# (chmod 600, never in chat). See README for how to fill them.
D = os.path.dirname(os.path.abspath(__file__))
URL = None
for _name in ("hoody-url.txt", "tailnet-url.txt", "public-url.txt"):
    _p = os.path.join(D, _name)
    if os.path.exists(_p):
        URL = open(_p).read().strip()
        break
if not URL:
    raise SystemExit("no gateway URL file found next to pi-api.py "
                     "(hoody-url.txt, tailnet-url.txt, or public-url.txt)")
TOK = open(os.path.join(D, "gateway-token.txt")).read().strip()

def _opener():
    # A tailnet (100.x) URL needs the VM's tunnel proxy on port 3130; the proxy
    # is derived from HTTPS_PROXY unless PI_GATEWAY_PROXY is set. Without it,
    # direct connections to the tailnet address come back empty.
    if URL.startswith("http://100."):
        proxy = os.environ.get("PI_GATEWAY_PROXY")
        if not proxy and "HTTPS_PROXY" in os.environ:
            proxy = os.environ["HTTPS_PROXY"].rsplit(":", 1)[0] + ":3130"
        if proxy:
            return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()

def call(method, path, body=None):
    req = urllib.request.Request(URL + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"})
    try:
        with _opener().open(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode(errors="replace")[:500]}

if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "health"
    if cmd == "health":
        print(json.dumps(call("GET", "/health"), indent=2))
    elif cmd == "sessions":
        print(json.dumps(call("GET", "/sessions"), indent=2))
    elif cmd == "models":
        print(json.dumps(call("GET", "/models"), indent=2))
    elif cmd == "prompt":
        body = {"message": a[1]}
        for i, x in enumerate(a):
            if x == "--session": body["session_id"] = a[i+1]
            if x == "--model": body["model"] = a[i+1]
        print(json.dumps(call("POST", "/prompt", body), indent=2))
    elif cmd == "add-model":
        # pi-api.py add-model <provider> <model-id> --base-url URL [--api openai-completions] --env-name NAME [--key-stdin]
        # With --key-stdin the API key is read from stdin (never argv/history);
        # it is stored in provider-keys.env on the sandbox, models.json keeps $NAME.
        body = {"provider": a[1], "id": a[2]}
        for i, x in enumerate(a):
            if x == "--base-url": body["baseUrl"] = a[i+1]
            if x == "--api": body["api"] = a[i+1]
            if x == "--env-name": body["env_name"] = a[i+1]
        if "--key-stdin" in a:
            body["api_key"] = sys.stdin.read().strip()
        print(json.dumps(call("POST", "/models", body), indent=2))
    elif cmd == "setkey":
        # pi-api.py setkey <ENV_NAME>  (key read from stdin)
        body = {"env_name": a[1], "api_key": sys.stdin.read().strip()}
        print(json.dumps(call("POST", "/secrets", body), indent=2))
    elif cmd == "restart":
        print(json.dumps(call("POST", "/restart", {}), indent=2))
    elif cmd == "status":
        print(json.dumps(call("GET", f"/sessions/{a[1]}/status"), indent=2))
    elif cmd == "events":
        print(json.dumps(call("GET", f"/sessions/{a[1]}/events"), indent=2))
    elif cmd == "stop":
        print(json.dumps(call("POST", f"/sessions/{a[1]}/stop", {}), indent=2))
    elif cmd == "files":
        import urllib.parse
        print(json.dumps(call("GET", "/files?path=" + urllib.parse.quote(a[1])), indent=2))
    else:
        print("unknown command", cmd)
