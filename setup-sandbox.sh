#!/usr/bin/env bash
# setup-sandbox.sh — runs ON the Altare sandbox as root, in the web console.
#   bash /root/work/setup/setup-sandbox.sh
# The bundle (setup-muse.sh output) must already be in /root/work/setup/.
# Idempotent: safe to re-run; files it overwrites are backed up with .bak.
# Every step verifies itself and stops loudly with the fix if it fails.
#
# Env (optional): PI_HOSTNAME — Tailscale device name (default: pi-altare).
set -euo pipefail

BUNDLE=/root/work/setup
HOSTNAME="${PI_HOSTNAME:-pi-altare}"
SOCK=/root/tailscale/tailscaled.sock

# tzdata (and friends) must never stop the run with an interactive
# question in the web console — apt runs noninteractively throughout.
export DEBIAN_FRONTEND=noninteractive

say() { printf '\n==> %s\n' "$*"; }
fail() { echo "FAILED: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || fail "run as root"
[ -d "$BUNDLE" ] || fail "bundle not found at $BUNDLE — upload it first (see setup-muse.sh)"

say "Directories"
mkdir -p /root/pi-bridge /root/work /root/tailscale /root/.pi/agent

say "Base tools (curl, tmux)"
apt-get update -qq && apt-get install -y -qq curl ca-certificates gnupg tmux \
  || fail "apt install failed — check the sandbox network and re-run"

say "Node 22"
if ! node --version 2>/dev/null | grep -q '^v22\.'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    || fail "NodeSource setup failed"
  apt-get install -y -qq nodejs || fail "nodejs install failed"
fi
node --version | grep -q '^v22\.' || fail "node 22 not installed (got: $(node --version 2>/dev/null))"
echo "node $(node --version) ok"

say "Pi 1.5.2"
if ! pi --version 2>/dev/null | grep -q '1.5.2'; then
  npm install -g @earendil-works/pi-coding-agent@1.5.2 || fail "pi install failed"
fi
pi --version | grep -q '1.5.2' || fail "pi 1.5.2 not installed (got: $(pi --version 2>/dev/null))"
echo "pi $(pi --version) ok"
grep -q '/root/.pi/agent/bin' /root/.profile 2>/dev/null \
  || echo 'export PATH="$PATH:/root/.pi/agent/bin"' >> /root/.profile

say "Tailscale (official APT repo)"
if ! command -v tailscaled >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh \
    || fail "Tailscale install failed"
fi
tailscale version | head -1

# The sandbox has NO /dev/net/tun and fakes root (real uid 999), so the
# daemon must run in userspace mode with OperatorUser "container" — that
# is the fix that makes LocalAPI mutating calls work. Do not use the
# default socket: it is /var/run/tailscale/tailscaled.sock and the daemon
# below does not listen there.
printf '{\n  "Version": "alpha0",\n  "Locked": false,\n  "OperatorUser": "container"\n}\n' \
  > /root/tailscale/tailscaled.conf

say "Placing bundle files"
for f in pi-gateway.py watcher.py gateway.env provider-keys.env; do
  [ -f "/root/pi-bridge/$f" ] && cp "/root/pi-bridge/$f" "/root/pi-bridge/$f.bak"
  cp "$BUNDLE/$f" "/root/pi-bridge/$f"
done
chmod 600 /root/pi-bridge/gateway.env /root/pi-bridge/provider-keys.env
for f in models.json settings.json; do
  [ -f "/root/.pi/agent/$f" ] && cp "/root/.pi/agent/$f" "/root/.pi/agent/$f.bak"
  cp "$BUNDLE/$f" "/root/.pi/agent/$f"
done
# The gateway reads provider-keys.env directly, but the watcher (and an
# interactive pi) read keys from /root/.profile — so export them there too.
while IFS='=' read -r k v || [ -n "$k" ]; do
  case "$k" in ''|\#*) continue;; esac
  v="$(printf '%s' "$v" | tr -d '[:space:]')"
  [ -z "$v" ] && { echo "  (key $k is empty — fill it in provider-keys.env later)"; continue; }
  grep -q "^export $k=" /root/.profile 2>/dev/null || echo "export $k='$v'" >> /root/.profile
  grep -q "^export $k=" /root/.bashrc 2>/dev/null || echo "export $k='$v'" >> /root/.bashrc
done < /root/pi-bridge/provider-keys.env
echo "files placed"

say "Combined search on the box (Pi side)"
# Pi's copy of the combined search tool (search/web.py in the repo).
# The bundle carries it as web.py; without this copy Pi has no search.
if [ -f "$BUNDLE/web.py" ]; then
  cp "$BUNDLE/web.py" /root/pi-bridge/search.py
  chmod +x /root/pi-bridge/search.py
  echo "search.py installed"
else
  echo "WARNING: bundle has no web.py — Pi search not installed (rebuild the bundle with setup-muse.sh)"
fi
# Monid credentials template — the real key is pasted on the box later
# (or via the Pi Admin page's Monid card, which writes this same file).
mkdir -p /root/.config/monid
if [ ! -f /root/.config/monid/credentials.yaml ]; then
  printf 'key: "PASTE_MONID_KEY_HERE"\nlabel: main\n' > /root/.config/monid/credentials.yaml
  chmod 600 /root/.config/monid/credentials.yaml
  echo "Monid credentials template created — paste the real key into /root/.config/monid/credentials.yaml"
fi

say "Starting tailscaled (tmux session 'tailscaled')"
tmux kill-session -t tailscaled 2>/dev/null || true
tmux new-session -d -s tailscaled \
  'tailscaled --tun=userspace-networking --state=/root/tailscale/tailscaled.state --socket=/root/tailscale/tailscaled.sock --config=/root/tailscale/tailscaled.conf 2>&1 | tee /root/tailscale/tailscaled-final.log'
for i in $(seq 1 30); do [ -S "$SOCK" ] && break; sleep 2; done
[ -S "$SOCK" ] || fail "tailscaled socket never appeared — check: tmux attach -t tailscaled"

say "Tailscale login (device name: $HOSTNAME)"
# NOTE: plain `tailscale status` FAILS here (it talks to the default socket,
# which this daemon does not use). Always pass --socket=$SOCK.
if ! tailscale --socket="$SOCK" status >/dev/null 2>&1; then
  echo "A login URL will appear below. Open it in your browser and approve"
  echo "this device (it will appear as $HOSTNAME). The script waits here."
  tailscale --socket="$SOCK" up --operator=container --hostname="$HOSTNAME" \
    || fail "tailscale up failed — approve the device and re-run"
fi
IP=""
for i in $(seq 1 30); do
  IP="$(tailscale --socket="$SOCK" ip -4 2>/dev/null | head -1)"
  [ -n "$IP" ] && break; sleep 2
done
[ -n "$IP" ] || fail "tailscale never got an IP — approve the device in login.tailscale.com/admin/machines and re-run"
echo "tailnet IP: $IP"

say "Starting gateway + watcher (tmux 'pi-gateway' and 'pi-bridge')"
tmux kill-session -t pi-gateway 2>/dev/null || true
tmux kill-session -t pi-bridge 2>/dev/null || true
tmux new-session -d -s pi-gateway 'python3 /root/pi-bridge/pi-gateway.py'
tmux new-session -d -s pi-bridge 'python3 /root/pi-bridge/watcher.py'
sleep 3
curl -fsS http://127.0.0.1:8765/health \
  || fail "gateway health check failed — check: tmux attach -t pi-gateway"
echo; echo "gateway ok"

say "Cloudflared tunnel (fallback only — best effort)"
if ! command -v cloudflared >/dev/null 2>&1; then
  if curl -fsSL -o /tmp/cloudflared.deb \
      https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
      && dpkg -i /tmp/cloudflared.deb 2>/dev/null; then
    echo "cloudflared installed"
  else
    echo "WARNING: cloudflared install failed — skipping the tunnel (tailnet is the primary path)"
  fi
fi
if command -v cloudflared >/dev/null 2>&1; then
  tmux kill-session -t pi-tunnel 2>/dev/null || true
  tmux new-session -d -s pi-tunnel 'cloudflared tunnel --url http://127.0.0.1:8765 --logfile /root/pi-bridge/tunnel.log'
  echo "tunnel starting — its public URL appears in /root/pi-bridge/tunnel.log"
fi

say "DONE"
echo "Sandbox tailnet IP: $IP"
echo "Give this IP to your Muse, then on the Muse VM run:"
echo "  ./setup-muse.sh --tailnet $IP"
echo "Then test: pi-api.py prompt \"Say OK\" --model xingchi/gpt-6.1-sol"
