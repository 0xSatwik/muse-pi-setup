#!/usr/bin/env python3
"""Pi bridge watcher — runs on the Altare sandbox 'pi' as root.
Polls /root/pi-bridge/inbox/*.json, runs Pi headless on each job,
writes the result to /root/pi-bridge/outbox/<id>.json.
Muse (on the other side) talks to it only through the Altare Files API,
so no SSH into the sandbox is needed.

Start once, in tmux (sandbox has no systemd):
  tmux new -s pi-bridge -d 'python3 /root/pi-bridge/watcher.py'
  # after a sandbox restart, run that again — restarts stop everything.
Job JSON: {"id": "...", "model": "moss/nex-n2.6", "prompt": "...",
           "timeout": 1800, "cwd": "/root/work/<id>"}
Out JSON: {"id": "...", "status": "done|error|timeout",
           "output": "...", "stderr": "...", "exit_code": 0,
           "started_at": "...", "finished_at": "..."}
"""
import json, os, subprocess, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/root/pi-bridge")
INBOX = BASE / "inbox"
OUTBOX = BASE / "outbox"
DONE = BASE / "done"
WORK = Path("/root/work")
LOG = BASE / "watcher.log"
POLL = 5


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_profile_env():
    # Pi reads API keys from env; they live as exports in /root/.profile
    for path in (Path("/root/.profile"), Path("/root/.bashrc")):
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith("export ") and "=" in line:
                    k, v = line[len("export "):].split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass


def run_job(job):
    jid = job["id"]
    model = job.get("model", "moss/nex-n2.6")
    prompt = job.get("prompt", "")
    timeout = int(job.get("timeout", 1800))
    cwd = Path(job.get("cwd") or (WORK / jid))
    cwd.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    log(f"START {jid} model={model} cwd={cwd}")
    env = dict(os.environ)
    env["PATH"] = "/root/.pi/agent/bin:" + env.get("PATH", "")
    try:
        r = subprocess.run(
            ["pi", "--model", model, "-p", prompt],
            cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout,
        )
        status = "done" if r.returncode == 0 else "error"
        out = {"id": jid, "status": status, "output": r.stdout,
               "stderr": r.stderr[-4000:], "exit_code": r.returncode,
               "started_at": started,
               "finished_at": datetime.now(timezone.utc).isoformat()}
    except subprocess.TimeoutExpired as e:
        out = {"id": jid, "status": "timeout",
               "output": (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""),
               "stderr": "timed out after %ss" % timeout, "exit_code": None,
               "started_at": started,
               "finished_at": datetime.now(timezone.utc).isoformat()}
    except Exception:
        out = {"id": jid, "status": "error", "output": "",
               "stderr": traceback.format_exc()[-4000:], "exit_code": None,
               "started_at": started,
               "finished_at": datetime.now(timezone.utc).isoformat()}
    (OUTBOX / f"{jid}.json").write_text(json.dumps(out, indent=2))
    log(f"END {jid} status={out['status']} exit={out['exit_code']}")
    return out


def main():
    for d in (INBOX, OUTBOX, DONE, WORK):
        d.mkdir(parents=True, exist_ok=True)
    load_profile_env()
    log("watcher up, polling %s" % INBOX)
    while True:
        try:
            for f in sorted(INBOX.glob("*.json"), key=lambda p: p.stat().st_mtime):
                try:
                    job = json.loads(f.read_text())
                except Exception as e:
                    log(f"BAD {f.name}: {e}")
                    f.rename(DONE / f.name)
                    continue
                f.rename(DONE / f.name)
                run_job(job)
        except Exception:
            log("loop error:\n" + traceback.format_exc())
        time.sleep(POLL)


if __name__ == "__main__":
    main()
