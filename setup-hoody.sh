#!/usr/bin/env bash
# setup-hoody.sh — runs ON a Hoody computer (Debian 13) in its terminal, as root.
#   PI_GATEWAY_TOKEN=<token> XINGCHI_API_KEY=<key> ... bash setup-hoody.sh
# Or fetch it directly on the computer first:
#   curl -fsSL https://raw.githubusercontent.com/0xSatwik/muse-pi-setup/main/setup-hoody.sh -o /tmp/setup-hoody.sh
#   PI_GATEWAY_TOKEN=<token> XINGCHI_API_KEY=<key> ... bash /tmp/setup-hoody.sh
# Pulls the bridge files from this public repo (REPO_REF overridable).
# Idempotent: safe to re-run; files it overwrites are backed up with .bak.
# Every step verifies itself and stops loudly with the fix if it fails.
#
# Env (optional):
#   PI_GATEWAY_TOKEN  Bearer token for the gateway. If unset, the script
#                     generates one and prints it — give it to your Muse,
#                     which saves it as gateway-token.txt (chmod 600).
#   XINGCHI_API_KEY, TOKENLAB_API_KEY, MOSS_API_KEY, HOWTOFIX_API_KEY,
#   HMS_API_KEY       model keys. Keys left unset stay empty in
#                     provider-keys.env — fill them in later, then restart
#                     the gateway (tmux: pi-gateway).
#   HOODY_GATEWAY_URL the public gateway URL, e.g.
#                     https://<project>-<computer>-http-8765.<server>.computers.hoody.com
#                     If unset, the script prints how to derive it from
#                     your computer's terminal URL (replace `terminal-1`
#                     with `http-8765`).
#   REPO_REF          git ref to fetch the bridge files from (default: main).
#
# No Tailscale here: the Hoody proxy exposes the gateway directly. The
# gateway binds 0.0.0.0 (PI_GATEWAY_HOST) so the proxy can reach it. The
# public URL is open by default — the Bearer token is what guards the
# gateway. Set proxy permissions on your Hoody project if you want the
# URL itself locked down.
set -euo pipefail

REPO_REF="${REPO_REF:-main}"
REPO_RAW="https://raw.githubusercontent.com/0xSatwik/muse-pi-setup/$REPO_REF"

# tzdata (and friends) must never stop the run with an interactive
# question — apt runs noninteractively throughout.
export DEBIAN_FRONTEND=noninteractive

say() { printf '\n==> %s\n' "$*"; }
fail() { echo "FAILED: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || fail "run as root (the Hoody computer's terminal runs as root)"
command -v python3 >/dev/null 2>&1 || fail "python3 not found — this computer should have it preinstalled"

say "Directories"
mkdir -p /root/pi-bridge /root/work /root/.pi/agent

say "Base tools (curl, tmux)"
apt-get update -qq && apt-get install -y -qq curl ca-certificates gnupg tmux \
  || fail "apt install failed — check the computer's network and re-run"

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

say "Fetching bridge files from the repo (ref: $REPO_REF)"
cd /root/pi-bridge
for f in pi-gateway.py watcher.py; do
  curl -fsSL "$REPO_RAW/bridge/$f" -o "/tmp/$f" \
    || fail "could not fetch bridge/$f from $REPO_RAW — check the network and REPO_REF"
  [ -f "/root/pi-bridge/$f" ] && cp "/root/pi-bridge/$f" "/root/pi-bridge/$f.bak"
  cp "/tmp/$f" "/root/pi-bridge/$f"
done
for f in models.json settings.json; do
  curl -fsSL "$REPO_RAW/pi/$f" -o "/tmp/$f" \
    || fail "could not fetch pi/$f from $REPO_RAW"
  [ -f "/root/.pi/agent/$f" ] && cp "/root/.pi/agent/$f" "/root/.pi/agent/$f.bak"
  cp "/tmp/$f" "/root/.pi/agent/$f"
done
# Pi's copy of the combined search tool (search/web.py in the repo).
curl -fsSL "$REPO_RAW/search/web.py" -o /tmp/search.py \
  || fail "could not fetch search/web.py from $REPO_RAW"
[ -f /root/pi-bridge/search.py ] && cp /root/pi-bridge/search.py /root/pi-bridge/search.py.bak
cp /tmp/search.py /root/pi-bridge/search.py
chmod +x /root/pi-bridge/search.py
echo "files fetched"

say "Combined search on the box (Pi side)"
# Monid credentials template — the real key is pasted on the box later
# (or via the Pi Admin page's Monid card, which writes this same file).
mkdir -p /root/.config/monid
if [ ! -f /root/.config/monid/credentials.yaml ]; then
  printf 'key: "PASTE_MONID_KEY_HERE"\nlabel: main\n' > /root/.config/monid/credentials.yaml
  chmod 600 /root/.config/monid/credentials.yaml
  echo "Monid credentials template created — paste the real key into /root/.config/monid/credentials.yaml"
fi

say "Gateway token + model keys"
if [ -n "${PI_GATEWAY_TOKEN:-}" ]; then
  TOKEN="$PI_GATEWAY_TOKEN"
  echo "using the PI_GATEWAY_TOKEN you passed in"
else
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "generated a new gateway token (it is printed again at the end)"
fi
printf 'PI_GATEWAY_TOKEN=%s\n' "$TOKEN" > /root/pi-bridge/gateway.env
chmod 600 /root/pi-bridge/gateway.env
{
  for v in XINGCHI_API_KEY TOKENLAB_API_KEY MOSS_API_KEY HOWTOFIX_API_KEY HMS_API_KEY; do
    printf '%s=%s\n' "$v" "${!v:-}"
  done
} > /root/pi-bridge/provider-keys.env
chmod 600 /root/pi-bridge/provider-keys.env
# The gateway reads provider-keys.env directly, but the watcher (and an
# interactive pi) read keys from /root/.profile — so export them there too.
while IFS='=' read -r k v || [ -n "$k" ]; do
  case "$k" in ''|\#*) continue;; esac
  v="$(printf '%s' "$v" | tr -d '[:space:]')"
  [ -z "$v" ] && { echo "  (key $k is empty — fill it in provider-keys.env later)"; continue; }
  grep -q "^export $k=" /root/.profile 2>/dev/null || echo "export $k='$v'" >> /root/.profile
  grep -q "^export $k=" /root/.bashrc 2>/dev/null || echo "export $k='$v'" >> /root/.bashrc
done < /root/pi-bridge/provider-keys.env
echo "token + keys placed"

say "Starting gateway + watcher (tmux 'pi-gateway' and 'pi-bridge')"
# The gateway must bind 0.0.0.0 here (not its 127.0.0.1 default) so the
# Hoody proxy can reach it. The Bearer token is the guard, not the bind.
tmux kill-session -t pi-gateway 2>/dev/null || true
tmux kill-session -t pi-bridge 2>/dev/null || true
tmux new-session -d -s pi-gateway 'PI_GATEWAY_HOST=0.0.0.0 python3 /root/pi-bridge/pi-gateway.py'
tmux new-session -d -s pi-bridge 'python3 /root/pi-bridge/watcher.py'
sleep 3
curl -fsS http://127.0.0.1:8765/health \
  || fail "gateway health check failed — check: tmux attach -t pi-gateway"
echo; echo "gateway ok on localhost"

if [ -n "${HOODY_GATEWAY_URL:-}" ]; then
  say "Checking the public URL"
  if curl -fsS "$HOODY_GATEWAY_URL/health" >/dev/null 2>&1; then
    echo "public URL answers: $HOODY_GATEWAY_URL"
  else
    echo "WARNING: the public URL does not answer yet ($HOODY_GATEWAY_URL/health)."
    echo "The gateway itself is up (localhost check passed). The proxy can take a"
    echo "moment, or the URL is wrong — re-check it and retry the curl."
  fi
else
  echo "NOTE: HOODY_GATEWAY_URL was not set, so the public URL was not checked."
  echo "Your gateway URL is your computer's terminal URL with \`terminal-1\`"
  echo "replaced by \`http-8765\`, e.g.:"
  echo "  https://<project>-<computer>-http-8765.<server>.computers.hoody.com"
fi

say "DONE"
echo "Gateway token (give this to your Muse — it saves it as gateway-token.txt):"
echo "$TOKEN"
echo
echo "On the Muse VM, finish with:"
if [ -n "${HOODY_GATEWAY_URL:-}" ]; then
  echo "  ./setup-muse.sh --hoody $HOODY_GATEWAY_URL"
else
  echo "  ./setup-muse.sh --hoody https://<project>-<computer>-http-8765.<server>.computers.hoody.com"
fi
echo "Then test: pi-api.py prompt \"Say OK\" --model xingchi/gpt-6.1-sol"
echo
echo "After a computer restart, restart the two tmux sessions:"
echo "  tmux new-session -d -s pi-gateway 'PI_GATEWAY_HOST=0.0.0.0 python3 /root/pi-bridge/pi-gateway.py'"
echo "  tmux new-session -d -s pi-bridge 'python3 /root/pi-bridge/watcher.py'"
