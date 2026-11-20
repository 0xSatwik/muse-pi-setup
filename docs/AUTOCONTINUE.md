# Auto-continue — Pi restarts its own work when a turn ends

Pi works the master task file `/root/work/agentx/TASKS.md` top to bottom,
but a Pi turn *ends* when the session writes its report. Before this, the
session then sat idle until a human — or a supervisor cron, up to ~30
minutes later — nudged it. The gateway now closes that gap itself.

## How it works

A watchdog thread in `bridge/pi-gateway.py` (same process as the model
fallback watchdog) checks every 15 s. For each session listed in
`bridge/autocontinue.json` it fires the standard continue prompt when
ALL of these hold:

- the session is not running a turn, and a turn has ended since the last
  auto-continue (a freshly spawned proc counts once — so the watchdog
  also *respawns* the work sessions after a gateway restart and restarts
  their work on its own);
- the session has been idle for `idle_seconds` (default 90);
- the turn did **not** die on a provider error — those belong to the
  model fallback watchdog, which switches the model and continues the
  session itself;
- TASKS.md still holds work for that session: its own claimed `[~]`
  task (matched by its `(tag)`), or any unclaimed `[ ]` task above the
  owner-only section (the section whose heading says "owner-only" /
  "do not start").

## Guardrails

- **Blocked ≠ lazy.** The watchdog fingerprints TASKS.md (done / claimed
  / unclaimed / blocked counts). If `max_unproductive` (default 3)
  consecutive continues change nothing in the file, it stops firing for
  that session. A supervisor or human takes it from there — a session
  waiting on a person should not spin.
- **Owner-only work is never started.** Unclaimed tasks inside the
  owner-only section do not count as work left.
- **One fire per turn end.** Each auto-continue is keyed to a turn end;
  the watchdog never double-prompts a session for the same stop.

## Config

`bridge/autocontinue.json` sits beside the gateway (same pattern as
`fallback.json`); see `bridge/autocontinue.json.example`. The session
ids live only in that file, never in code. `enabled: false` turns the
watchdog off without a restart (the file is re-read every cycle).

Status: `GET /autocontinue` returns the config plus `lastContinue`
(session, tag, time, unproductive count). `POST /autocontinue` accepts
`enabled`, `idle_seconds`, `max_unproductive`.

## Verified

2026-11-20: gateway restarted with the watchdog live and nobody touched
the sessions — within ~2 minutes both work sessions had been respawned
and were running again on their own.
