#!/usr/bin/env python3
"""Gateway patch #2: make session_files() fast + return the model per session.

The scan JSON-parsed EVERY line of all 71 session files (8.6 MB, incl.
giant tool-result lines) on every /sessions poll: ~8.3s per scan. Now it
only parses the session header and model_change lines (substring pre-test),
counts the rest without parsing. Also raises the list cache TTL 5s -> 30s
and adds each session's last model (provider/modelId) so the /pi sidebar
can show it without opening the transcript.
"""
import sys

GW = "/root/pi-bridge/pi-gateway.py"

def sub(old, new, count=1):
    with open(GW) as f:
        s = f.read()
    if s.count(old) != count:
        print(f"FAIL: pattern found {s.count(old)}x, expected {count}x:\n{old[:120]!r}")
        sys.exit(1)
    with open(GW, "w") as f:
        f.write(s.replace(old, new, count))
    print(f"ok: {old[:60]!r}...")

sub(
    'SESS_CACHE_TTL = 5.0  # /pi polls /sessions every 2-10s; don\'t re-parse every file each time',
    'SESS_CACHE_TTL = 30.0  # /pi polls /sessions every 2-10s; don\'t re-scan every file each time')

sub(
    '                name, cwd, n = sid, "", 0\n'
    '                try:\n'
    '                    with open(path) as f:\n'
    '                        for line in f:\n'
    '                            n += 1\n'
    '                            try:\n'
    '                                rec = json.loads(line)\n'
    '                            except Exception:\n'
    '                                continue\n'
    '                            if isinstance(rec, dict):\n'
    '                                if rec.get("type") == "session" and rec.get("name"):\n'
    '                                    name = rec["name"]\n'
    '                                if rec.get("cwd"):\n'
    '                                    cwd = rec["cwd"]\n'
    '                except Exception:\n'
    '                    pass\n'
    '                out.append({"id": sid, "name": name, "cwd": cwd, "messages": n,',
    '                name, cwd, model, n = sid, "", "", 0\n'
    '                try:\n'
    '                    with open(path) as f:\n'
    '                        for line in f:\n'
    '                            n += 1\n'
    '                            # Only the session header + model_change lines\n'
    '                            # carry list data; parsing every message/tool\n'
    '                            # line made a full scan take ~8s over 71 files.\n'
    '                            if (\'"type":"session"\' not in line\n'
    '                                    and \'"type": "session"\' not in line\n'
    '                                    and \'"model_change"\' not in line):\n'
    '                                continue\n'
    '                            try:\n'
    '                                rec = json.loads(line)\n'
    '                            except Exception:\n'
    '                                continue\n'
    '                            if not isinstance(rec, dict):\n'
    '                                continue\n'
    '                            if rec.get("type") == "session":\n'
    '                                if rec.get("name"):\n'
    '                                    name = rec["name"]\n'
    '                                if rec.get("cwd"):\n'
    '                                    cwd = rec["cwd"]\n'
    '                            elif rec.get("type") == "model_change" and rec.get("modelId"):\n'
    '                                model = (rec.get("provider") + "/" if rec.get("provider") else "") + rec["modelId"]\n'
    '                except Exception:\n'
    '                    pass\n'
    '                out.append({"id": sid, "name": name, "cwd": cwd, "model": model, "messages": n,')

print("PATCH2 APPLIED")
