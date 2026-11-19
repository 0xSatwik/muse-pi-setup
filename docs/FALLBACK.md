# Model fallback — automatic fail-over when a provider dies

Built 2026-11-20. Lives in the gateway (`bridge/pi-gateway.py`); there is
nothing to install beyond the gateway itself.

## The problem

A Pi session's turn can die mid-work when its model provider has an outage
— 503 "upstream busy" storms are the common case. The session's history is
safe on disk, but the turn just stops, and a human (or a supervisor loop)
has to notice, switch the model by hand, and re-prompt. During a bad
provider night this happened again and again.

## The design

The gateway keeps an ordered **fallback chain** of `provider/modelId`
entries, stored in `fallback.json` next to the gateway (deliberately NOT
in Pi's own `settings.json`, so it survives Pi config changes and can be
edited live):

```json
{ "enabled": true, "chain": ["provider-a/model-1", "provider-b/model-2"] }
```

A watchdog thread in the gateway polls every 15 seconds. A session is
switched when ALL of these hold:

- its last turn ended with a provider-class error (the error text matches
  hints like 503/502/500, upstream, busy, overloaded, unavailable,
  timeout, rate limit, 429);
- the session is idle — the error and its last event are both at least
  45 s old, so Pi's own retry window gets the first chance to recover;
- that death has not already been handled (one switch per death, never a
  switch loop).

The switch itself uses Pi's RPC: `set_model` to the NEXT chain entry,
verified with `get_state` (the gateway's older `/sessions/{id}/model`
route does not shape this command correctly — always go through `/rpc`).
The session is then prompted to continue, with a note that it was
auto-switched. The full conversation context is preserved — only the
serving model changes. A session already on the last chain entry is left
alone. The last switch is remembered and shown in the admin page.

## Ordering the chain — the admin page

The admin page has a **Model fallback order** card:

- enable/disable checkbox;
- the ordered list with ↑ / ↓ to reorder and ✕ to remove;
- a dropdown of every registered model to add to the order;
- a "last auto-switch" line.

Every change saves immediately through `POST /fallback` — no gateway
restart needed. `GET /fallback` returns the current chain plus the last
switch record. Only models whose provider has a key set can actually
serve; ordering a keyless model is allowed but pointless.

## Notes and limits

- This covers provider *deaths*. A silently hung stream (no error, no
  events) is a different failure — that still needs an outside supervisor
  watching event flow.
- Difficulty routing (which model a step *should* start on) is a separate
  concern handled by whoever drives the sessions; the fallback chain is
  only the safety net underneath it.
- Copy `bridge/fallback.json.example` to `fallback.json` beside the
  gateway and put your own provider/model ids in order.
