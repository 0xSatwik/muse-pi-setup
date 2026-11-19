#!/usr/bin/env python3
"""Fix the /pi sanitizer bug cluster + drawer z-index + session dupes + 502s.

pi.html:
  P1  sanitizer allow-list: BUTTON/OPTION/OPTGROUP tags; data-act, data-q,
      value, selected, label attrs. (Was silently stripping them, which broke
      session clicks [data-act], suggestion chips [data-q], the model
      dropdown [option/optgroup/value/selected] and the Show-older button.)
  P2  renderModelSel: build <option>/<optgroup> with DOM APIs, not set() —
      the HTML parser drops <option> outside a <select>, so set() can never
      render them however the allow-list reads.
  P3  Show-older button: onclick -> data-act="older" + delegation in the
      logInner click handler (set() strips on* handlers by design).
  P4  Narrow mode: drawer z-index 30, scrim 25 — the blurred topbar
      (z-index 20) was painting over the drawer's top row, hiding the
      search box and the + New button.
  P5  Dedupe sessions by base UUID (Pi keeps timestamped snapshot files
      alongside the live file: 2026-11-19T09-14-30-020Z_<uuid> vs <uuid>).
      Keep the newest entry per base id.
  P6  Only toast a sessions error on the 3rd consecutive failure, once per
      streak — a single transient 502 while polling no longer spams.

pi-gateway.py:
  G1  Cache session_files() for 5s: the /pi page polls /sessions every
      2-10s and every poll re-read + JSON-parsed every session file.
  G2  Listen backlog 5 -> 128 + daemon threads: concurrent polls from the
      page overflowed the backlog, cloudflared reported them as 502s.

Backups: pi.html.bak-pre-sanfix, pi-gateway.py.bak-pre-502fix.
"""
import sys

def sub(path, old, new, count=1):
    with open(path) as f:
        s = f.read()
    if s.count(old) != count:
        print(f"FAIL {path}: pattern found {s.count(old)}x, expected {count}x:\n{old[:120]!r}")
        sys.exit(1)
    with open(path, "w") as f:
        f.write(s.replace(old, new, count))
    print(f"ok: {path}: {old[:60]!r}...")

HTML = "/root/pi-bridge/pi.html"
GW = "/root/pi-bridge/pi-gateway.py"

# ---- P1: sanitizer allow-lists ----
sub(HTML,
    'const OK_TAGS = new Set(("DIV SPAN P B STRONG EM DEL CODE PRE A UL OL LI BR HR " +\n'
    '  "H2 H3 H4 H5 BLOCKQUOTE TABLE THEAD TBODY TR TH TD DETAILS SUMMARY").split(" "));',
    'const OK_TAGS = new Set(("DIV SPAN P B STRONG EM DEL CODE PRE A UL OL LI BR HR " +\n'
    '  "H2 H3 H4 H5 BLOCKQUOTE TABLE THEAD TBODY TR TH TD DETAILS SUMMARY BUTTON OPTION OPTGROUP").split(" "));')
sub(HTML,
    'const OK_ATTR = new Set(["class", "href", "target", "rel", "title", "style",\n'
    '  "data-lang", "data-id", "colspan", "rowspan"]);',
    'const OK_ATTR = new Set(["class", "href", "target", "rel", "title", "style",\n'
    '  "data-lang", "data-id", "data-act", "data-q", "value", "selected", "label",\n'
    '  "colspan", "rowspan"]);')

# ---- P2: renderModelSel via DOM APIs ----
sub(HTML,
    'function renderModelSel() {\n'
    '  const sel = $("modelSel");\n'
    '  const want = CUR ? (modelCache[CUR] || PENDING_MODEL) : PENDING_MODEL;\n'
    '  let html = \'<option value="">model…</option>\';\n'
    '  let lastP = null;\n'
    '  MODELS.forEach(m => {\n'
    '    if (m.provider !== lastP) {\n'
    '      if (lastP !== null) html += "</optgroup>";\n'
    '      html += \'<optgroup label="\' + esc(m.provider) + \'">\';\n'
    '      lastP = m.provider;\n'
    '    }\n'
    '    html += \'<option value="\' + esc(m.key) + \'"\' + (m.key === want ? " selected" : "") + ">" +\n'
    '            esc(m.id) + "</option>";\n'
    '  });\n'
    '  if (lastP !== null) html += "</optgroup>";\n'
    '  set(sel, html);\n'
    '}',
    'function renderModelSel() {\n'
    '  // Build with DOM APIs, NOT set(): the HTML parser drops <option> /\n'
    '  // <optgroup> tokens outside a <select>, so set() can never render them.\n'
    '  const sel = $("modelSel");\n'
    '  const want = CUR ? (modelCache[CUR] || PENDING_MODEL) : PENDING_MODEL;\n'
    '  sel.replaceChildren();\n'
    '  const ph = document.createElement("option");\n'
    '  ph.value = ""; ph.textContent = "model…";\n'
    '  sel.appendChild(ph);\n'
    '  let lastP = null, grp = null;\n'
    '  MODELS.forEach(m => {\n'
    '    if (m.provider !== lastP) {\n'
    '      grp = document.createElement("optgroup");\n'
    '      grp.label = m.provider;\n'
    '      sel.appendChild(grp);\n'
    '      lastP = m.provider;\n'
    '    }\n'
    '    const o = document.createElement("option");\n'
    '    o.value = m.key; o.textContent = m.id;\n'
    '    if (m.key === want) o.selected = true;\n'
    '    grp.appendChild(o);\n'
    '  });\n'
    '}')

# ---- P3: show-older via delegation (set() strips onclick) ----
sub(HTML,
    '    html += \'<div class="olderbar"><button class="ghost" onclick="showOlder()">\' +',
    '    html += \'<div class="olderbar"><button class="ghost" data-act="older">\' +')
sub(HTML,
    '$("logInner").addEventListener("click", e => {\n'
    '  const chip = e.target.closest(".chip[data-q]");\n'
    '  if (chip) quick(chip.dataset.q);\n'
    '});',
    '$("logInner").addEventListener("click", e => {\n'
    '  const chip = e.target.closest(".chip[data-q]");\n'
    '  if (chip) { quick(chip.dataset.q); return; }\n'
    '  const older = e.target.closest("[data-act=\'older\']");\n'
    '  if (older) showOlder();\n'
    '});')

# ---- P4: drawer above the blurred topbar in narrow mode ----
sub(HTML,
    '  aside{position:fixed;left:0;top:0;bottom:0;width:86vw;max-width:330px;transform:translateX(-102%);\n'
    '    transition:transform .22s ease;box-shadow:0 0 40px rgba(0,0,0,.5);padding-top:6px}',
    '  aside{position:fixed;left:0;top:0;bottom:0;width:86vw;max-width:330px;transform:translateX(-102%);\n'
    '    transition:transform .22s ease;box-shadow:0 0 40px rgba(0,0,0,.5);padding-top:6px;z-index:30}\n'
    '  #scrim{z-index:25}')
sub(HTML,
    'let statsFails = 0;',
    'let statsFails = 0;\nlet sessFails = 0;')

# ---- P5: dedupe timestamped snapshot files in the session list ----
sub(HTML,
    '    const list = await api("/sessions");\n'
    '    SESS = (list || []).slice();',
    '    const list = await api("/sessions");\n'
    '    // Pi keeps timestamped snapshot files next to the live session file\n'
    '    // (2026-11-19T09-14-30-020Z_<uuid> vs <uuid>): same chat, listed twice.\n'
    '    // Keep only the newest entry per base id.\n'
    '    const byBase = new Map();\n'
    '    (list || []).forEach(s => {\n'
    '      const base = String(s.id || "").replace(/^\\d{4}-\\d{2}-\\d{2}T[\\d-]+Z_/, "");\n'
    '      const prev = byBase.get(base);\n'
    '      if (!prev || (s.mtime || 0) > (prev.mtime || 0)) byBase.set(base, s);\n'
    '    });\n'
    '    SESS = [...byBase.values()];')

# ---- P6: quiet transient sessions failures; toast once per streak ----
sub(HTML,
    '    renderSessions();\n'
    '    const target = anyRunning() ? 2000 : 10000;',
    '    renderSessions();\n'
    '    sessFails = 0;\n'
    '    const target = anyRunning() ? 2000 : 10000;')
sub(HTML,
    '  } catch (e) {\n'
    '    if (!silent && e.message !== "unauthorized") toast("Sessions: " + e.message);\n'
    '  }',
    '  } catch (e) {\n'
    '    if (e.message === "unauthorized") return;\n'
    '    sessFails++;\n'
    '    if (!silent && sessFails === 3) toast("Sessions: " + e.message);\n'
    '  }')

# ---- G1: cache session_files() for 5s ----
sub(GW,
    'def session_files():\n'
    '    out = []',
    '_sess_cache = {"ts": 0.0, "data": None}\n'
    'SESS_CACHE_TTL = 5.0  # /pi polls /sessions every 2-10s; don\'t re-parse every file each time\n\n\n'
    'def session_files():\n'
    '    now = time.time()\n'
    '    if _sess_cache["data"] is not None and now - _sess_cache["ts"] < SESS_CACHE_TTL:\n'
    '        return _sess_cache["data"]\n'
    '    out = []')
sub(GW,
    '    out.sort(key=lambda s: s.get("mtime", 0), reverse=True)\n'
    '    return out',
    '    out.sort(key=lambda s: s.get("mtime", 0), reverse=True)\n'
    '    _sess_cache["ts"], _sess_cache["data"] = now, out\n'
    '    return out')

# ---- G2: bigger listen backlog + daemon threads ----
sub(GW,
    '    print(f"pi-gateway listening on {HOST}:{PORT}", flush=True)\n'
    '    ThreadingHTTPServer((HOST, PORT), H).serve_forever()',
    '    print(f"pi-gateway listening on {HOST}:{PORT}", flush=True)\n'
    '    # The /pi page polls /sessions + /stats + /events concurrently; the\n'
    '    # default listen backlog of 5 drops connections under that load and\n'
    '    # cloudflared reports them as 502s.\n'
    '    class Srv(ThreadingHTTPServer):\n'
    '        request_queue_size = 128\n'
    '        daemon_threads = True\n'
    '    Srv((HOST, PORT), H).serve_forever()')

print("ALL PATCHES APPLIED")
