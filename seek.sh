#!/usr/bin/env bash
# seek.sh — consult 100milionseek (deepseek-v4.1-flash-free) at MAX settings,
# following DEEPSEEK-MAX-GUIDE.md in this folder (verified 2026-11-18).
# Usage: seek.sh <prompt-file> <out-file>
# Writes the answer to <out-file> and the reasoning trace to <out-file>.reasoning
# Key lives in ./.key (mode 600). Max output (65536), reasoning_effort=max.
# Streaming is required: a non-streaming max-reasoning call can exceed the gateway's
# origin timeout (Cloudflare 524). Transient 502/503s are retried with backoff —
# the gateway throws them under load and a single attempt is not reliable.
# Keep prompts <= ~500K chars: the gateway's token estimator is strict
# (hard cap 197,488 input tokens) and rejects oversize requests with a 400.
#
# v2 (2026-11-19) — hard lessons from the PR #84 final review, which died repeatedly:
#  * Long silent streams get cut: a 126 KB prompt at reasoning_effort=max can sit
#    silent (queued + prefilling + thinking) for minutes, and the connection then
#    ends with ZERO content ("stream ended with empty content"). The provider was
#    alive throughout — small calls answered in seconds. Defence: cap the output
#    for verdict-style work (SEEK_MAX_TOKENS) so generation finishes fast, and
#    retry with real backoff (15/30/60/120s, 6 attempts).
#  * Reasoning is evidence: v1 discarded a dead attempt's reasoning trace. v2
#    saves it to <out>.reasoning.partial-<n> on failure.
#  * Truncation is failure: v1 accepted any non-empty content, even a stream cut
#    mid-answer. v2 requires a finish_reason ("stop"/"length"); a content stream
#    with no finish_reason is saved to <out>.partial-<n> and retried.
#  * Every attempt logs duration, curl exit code, first-byte time, chunk counts
#    and reasoning/content sizes, so a death is diagnosable from the log alone.
# Overrides: SEEK_MAX_TOKENS, SEEK_MAX_TIME (curl --max-time), SEEK_ATTEMPTS.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPT_FILE="${1:?usage: seek.sh <prompt-file> <out-file>}"
OUT_FILE="${2:?usage: seek.sh <prompt-file> <out-file>}"
python3 - "$DIR" "$PROMPT_FILE" "$OUT_FILE" <<'PYEOF'
import json, os, subprocess, sys, time

base_dir, prompt_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
key = open(f"{base_dir}/.key").read().strip()
prompt = open(prompt_path).read()
MAX_TOKENS = int(os.environ.get("SEEK_MAX_TOKENS", "65536"))
MAX_TIME = os.environ.get("SEEK_MAX_TIME", "1500")
ATTEMPTS = int(os.environ.get("SEEK_ATTEMPTS", "6"))
# Guide section 4: the effort knob is weak on this gateway — the intelligence
# comes from the prompt. A coding system prompt (which overrides the wrapper
# persona), full context in one call, premises stated exclusively, and a
# self-verification demand are the levers that measurably work.
SYSTEM = (
    "You are an expert senior software engineer reviewing real code and designs. "
    "Work step by step: analyse the problem, consider edge cases and failure modes, "
    "then give your final answer. Use ONLY the facts given in this conversation — "
    "ignore real-world dates, facts, and assumptions not stated here. "
    "Before concluding, re-check every claim you make against the material provided; "
    "if something is not established by it, say so explicitly instead of guessing. "
    "Follow the output format the user asks for exactly."
)
body = json.dumps({
    "model": "deepseek-v4.1-flash-free",
    "stream": True,
    "max_tokens": MAX_TOKENS,
    "reasoning_effort": "max",
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ],
})

# The request body rides in a temp file, not argv: curl's -d argument breaks
# past ~128 KB (Linux MAX_ARG_STRLEN) and a full PR diff alone is 122 KB.
def attempt(try_no):
    import tempfile
    fd, body_path = tempfile.mkstemp(prefix="seek-body-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        proc = subprocess.Popen(
            ["curl", "-sN", "--max-time", str(MAX_TIME), "https://100milionseek.top/v1/chat/completions",
             "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
             "-d", f"@{body_path}"],
            stdout=subprocess.PIPE, text=True,
        )
        return _read_stream(proc, try_no)
    finally:
        os.unlink(body_path)

def _read_stream(proc, try_no):
    content_parts, reasoning_parts, usage = [], [], {}
    t0 = time.time()
    first_byte = None
    finish = None
    chunks = 0
    assert proc.stdout is not None
    for line in proc.stdout:
        if first_byte is None:
            first_byte = time.time() - t0
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except Exception:
            continue
        if "error" in chunk:
            proc.wait()
            raise RuntimeError(f"API error: {json.dumps(chunk['error'])[:300]}")
        if chunk.get("usage"):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        chunks += 1
        if choices[0].get("finish_reason"):
            finish = choices[0]["finish_reason"]
        delta = choices[0].get("delta") or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
        if delta.get("reasoning_content"):
            reasoning_parts.append(delta["reasoning_content"])
    proc.wait()
    dur = time.time() - t0
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)
    stats = (f"dur={dur:.0f}s curl_rc={proc.returncode} first_byte="
             f"{first_byte:.0f}s chunks={chunks} reasoning_chars={len(reasoning)} "
             f"content_chars={len(content)} finish={finish}")
    if not content:
        if reasoning:
            with open(f"{out_path}.reasoning.partial-{try_no}", "w") as fh:
                fh.write(reasoning)
        raise RuntimeError(f"stream ended with empty content ({stats})")
    if finish is None:
        with open(f"{out_path}.partial-{try_no}", "w") as fh:
            fh.write(content)
        if reasoning:
            with open(f"{out_path}.reasoning.partial-{try_no}", "w") as fh:
                fh.write(reasoning)
        raise RuntimeError(f"stream truncated, no finish_reason ({stats})")
    sys.stderr.write(f"seek: attempt {try_no} stream ok ({stats})\n")
    return content, reasoning, usage

last_error = None
for try_no in range(1, ATTEMPTS + 1):
    try:
        content, reasoning, usage = attempt(try_no)
        break
    except Exception as error:  # transient gateway failures: back off and retry
        last_error = error
        if try_no == ATTEMPTS:
            sys.stderr.write(f"seek: failed after {ATTEMPTS} attempts: {error}\n")
            sys.exit(1)
        wait = min(15 * (2 ** (try_no - 1)), 120)
        sys.stderr.write(f"seek: attempt {try_no} failed ({error}); retrying in {wait}s\n")
        time.sleep(wait)

open(out_path, "w").write(content)
if reasoning:
    open(out_path + ".reasoning", "w").write(reasoning)
sys.stderr.write(
    f"seek: ok — prompt_tokens={usage.get('prompt_tokens')} completion_tokens={usage.get('completion_tokens')}\n"
)
PYEOF
