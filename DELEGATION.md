# Delegation rule — Pi on Altare (standing, 2026-11-17)

Frequently delegate to Pi on the Altare sandbox "pi".

Why:
- **Token saving** — Pi runs on the user's own custom APIs
  (xingchi, tokenlab, moss), not on Muse tokens.
- **Extra intelligence** — a second model / second opinion, not just
  Muse thinking alone. Pick the best of the 5 models for the job.
- **Better architecture** — Pi double-checks designs and architecture
  before Muse builds, and reviews what Muse built.

When to delegate (default, not exception):
- Long-running tasks (anything that would run for minutes/hours)
- Heavy tasks (big code, big research, big refactors)
- Architecture / design decisions — get Pi's take first, then build
- Any task where a second model's view would catch mistakes

How:
- Short: `python3 ~/workspace/altare-pi-setup/pi-bridge/muse-pi.py ask --model <model> --prompt "..."`
- Long: `send --model <model> --prompt "..."` → returns an id → `get <id>` later
- Files: `put <local> <remote>` to send code in, `getfile <remote>` to bring results back
- Gateway (preferred for sessions): `python3 ~/workspace/altare-pi-setup/pi-bridge/pi-api.py prompt "..." [--session ID] [--model M]`

Sessions — one per topic (standing rule, user choice 2026-11-17):
- DEFAULT: reuse the topic's existing Pi session, never start fresh when one exists.
- Registry: `~/workspace/altare-pi-setup/pi-bridge/pi-sessions.json` — look up the topic
  there first, continue with `pi-api.py prompt --session <id>`.
- A topic with no session gets a new one; register its id, model and date in the file.
- Compact a session when it gets long (gateway `POST /sessions/{id}/compact`).
  Start fresh only if a session dies, errors repeatedly, or gets confused.
- Prefer xingchi/gpt-6.1-sol for long sessions (moss dies empty on long runs).

Models:
- xingchi/gpt-6-astra, xingchi/gpt-6.1-sol
- tokenlab/DeepSeek-V4.1-Flash
- moss/nex-n2.6
- howtofix/deepSeek-v4.1-flash-1017-sg
- 100milionseek/deepseek-v4.1-flash-free

Notes:
- Watcher runs in tmux `pi-bridge` on the sandbox; restart it after
  a sandbox restart (no systemd on Altare).
- This rule is recorded in ~/MEMORY.md and ~/AGENTS.md as well.
