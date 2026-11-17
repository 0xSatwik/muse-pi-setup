#!/usr/bin/env bash
# setup-muse.sh — Muse-side setup for muse-pi-setup (run on the Muse VM).
# Does everything scriptable on this side, then prints the exact manual
# steps that remain (Altare console, Tailscale approvals, sandbox script).
#
# Usage:
#   ./setup-muse.sh [--repo-dir DIR] [--tailnet IP]
#   --repo-dir DIR   where to clone/copy this repo (default: ~/workspace/muse-pi-setup)
#   --tailnet IP     sandbox tailnet IP, e.g. 100.x.x.x — finishes the setup
#                    (writes tailnet-url.txt and runs the health check).
#                    Omit it on the first run; re-run with it after the
#                    sandbox reports its tailnet IP.
#
# Optional env vars (keys are never printed except the gateway token, once):
#   ALTARE_TEAM, ALTARE_SERVER   Altare team + sandbox server IDs (enables
#                                the automatic bundle upload step).
#   XINGCHI_API_KEY, TOKENLAB_API_KEY, MOSS_API_KEY, HOWTOFIX_API_KEY,
#   HMS_API_KEY                  model keys — if set, they go into the
#                                sandbox bundle's provider-keys.env.
#                                If unset, the bundle gets an empty template
#                                and you fill it in on the sandbox.
#   MONID_API_KEY                free search key — if set, written to
#                                ~/.config/monid/credentials.yaml (chmod 600).
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/workspace/muse-pi-setup}"
BRIDGE_DIR="$HOME/workspace/altare-pi-setup/pi-bridge"
TAILNET_IP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo-dir) REPO_DIR="$2"; shift 2;;
    --tailnet) TAILNET_IP="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing tool: $1" >&2; exit 1; }; }

say "Checking tools"
need python3; need git; need curl

say "Repo dir: $REPO_DIR"
if [ -d "$REPO_DIR/.git" ]; then
  echo "repo already present, pulling latest"
  git -C "$REPO_DIR" pull --ff-only || echo "pull failed — continuing with the local copy"
elif [ -d "$REPO_DIR" ]; then
  echo "using existing directory $REPO_DIR (not a git checkout)"
else
  git clone https://github.com/0xSatwik/muse-pi-setup.git "$REPO_DIR"
fi

say "Installing bridge files to $BRIDGE_DIR"
mkdir -p "$BRIDGE_DIR"
for f in pi-api.py muse-pi.py pi-gateway.py watcher.py README.md; do
  cp "$REPO_DIR/bridge/$f" "$BRIDGE_DIR/$f"
done
cp "$REPO_DIR/bridge/tailnet-url.txt.example" "$BRIDGE_DIR/tailnet-url.txt.example"
cp "$REPO_DIR/bridge/public-url.txt.example" "$BRIDGE_DIR/public-url.txt.example"
echo "bridge files installed"

say "Installing search + skill"
mkdir -p "$HOME/workspace/search" "$HOME/workspace/custom-skills/web-research"
cp "$REPO_DIR/search/web.py" "$HOME/workspace/search/web.py"
cp "$REPO_DIR/search/SEARCH.md" "$HOME/workspace/search/SEARCH.md"
cp "$REPO_DIR/skills/web-research/SKILL.md" "$HOME/workspace/custom-skills/web-research/SKILL.md"

say "Session registry"
if [ ! -f "$BRIDGE_DIR/pi-sessions.json" ]; then
  cp "$REPO_DIR/pi/pi-sessions.template.json" "$BRIDGE_DIR/pi-sessions.json"
  echo "created pi-sessions.json from the template"
else
  echo "pi-sessions.json already exists, left alone"
fi

say "Gateway token"
if [ -f "$BRIDGE_DIR/gateway-token.txt" ]; then
  echo "gateway-token.txt already exists — NOT regenerated (keep the existing one)"
  TOKEN="$(cat "$BRIDGE_DIR/gateway-token.txt")"
else
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  printf '%s' "$TOKEN" > "$BRIDGE_DIR/gateway-token.txt"
  chmod 600 "$BRIDGE_DIR/gateway-token.txt"
  echo "generated a new gateway token (saved to gateway-token.txt, chmod 600)"
fi

say "Sandbox bundle"
BUNDLE="$BRIDGE_DIR/sandbox-bundle"
mkdir -p "$BUNDLE"
cp "$REPO_DIR/bridge/pi-gateway.py" "$REPO_DIR/bridge/watcher.py" "$BUNDLE/"
cp "$REPO_DIR/pi/models.json" "$REPO_DIR/pi/settings.json" "$BUNDLE/"
cp "$REPO_DIR/setup-sandbox.sh" "$BUNDLE/"
printf 'PI_GATEWAY_TOKEN=%s\n' "$TOKEN" > "$BUNDLE/gateway.env"
chmod 600 "$BUNDLE/gateway.env"
{
  for v in XINGCHI_API_KEY TOKENLAB_API_KEY MOSS_API_KEY HOWTOFIX_API_KEY HMS_API_KEY; do
    printf '%s=%s\n' "$v" "${!v:-}"
  done
} > "$BUNDLE/provider-keys.env"
chmod 600 "$BUNDLE/provider-keys.env"
EMPTY_KEYS=0
for v in XINGCHI_API_KEY TOKENLAB_API_KEY MOSS_API_KEY HOWTOFIX_API_KEY HMS_API_KEY; do
  [ -z "${!v:-}" ] && EMPTY_KEYS=$((EMPTY_KEYS + 1))
done
if [ "$EMPTY_KEYS" -gt 0 ]; then
  echo "WARNING: $EMPTY_KEYS of 5 model keys are empty in the bundle's provider-keys.env."
  echo "Fill them in on the sandbox (or re-run with the key env vars set), then restart the gateway."
else
  echo "all 5 model keys present in the bundle"
fi
echo "bundle ready in $BUNDLE"

if [ -n "${MONID_API_KEY:-}" ]; then
  say "Monid search key"
  mkdir -p "$HOME/.config/monid"
  # web.py reads this with: key:\s*"([^"]+)" — keep the quotes.
  printf 'key: "%s"\nlabel: main\n' "$MONID_API_KEY" > "$HOME/.config/monid/credentials.yaml"
  chmod 600 "$HOME/.config/monid/credentials.yaml"
  echo "wrote ~/.config/monid/credentials.yaml (chmod 600)"
else
  echo "NOTE: MONID_API_KEY not set — search will not work until you add it."
  echo "Get a free key at monid, then save it to ~/.config/monid/credentials.yaml (chmod 600)."
fi

say "Uploading the bundle to the sandbox"
if [ -n "${ALTARE_TEAM:-}" ] && [ -n "${ALTARE_SERVER:-}" ]; then
  cd "$BRIDGE_DIR"
  for f in setup-sandbox.sh pi-gateway.py watcher.py models.json settings.json gateway.env provider-keys.env; do
    ALTARE_TEAM="$ALTARE_TEAM" ALTARE_SERVER="$ALTARE_SERVER" python3 muse-pi.py put "$BUNDLE/$f" "setup/$f"
  done
  echo "bundle uploaded to /root/work/setup/ on the sandbox"
else
  echo "ALTARE_TEAM / ALTARE_SERVER not set — upload skipped."
  echo "Upload it yourself with:"
  echo "  cd $BRIDGE_DIR"
  echo "  for f in setup-sandbox.sh pi-gateway.py watcher.py models.json settings.json gateway.env provider-keys.env; do"
  echo "    ALTARE_TEAM=<team-id> ALTARE_SERVER=<server-id> python3 muse-pi.py put sandbox-bundle/\$f setup/\$f"
  echo "  done"
  echo "(Find the IDs in the Altare console → server details.)"
fi

if [ -n "$TAILNET_IP" ]; then
  say "Finishing with tailnet IP $TAILNET_IP"
  printf 'http://%s:8765\n' "$TAILNET_IP" > "$BRIDGE_DIR/tailnet-url.txt"
  cd "$BRIDGE_DIR"
  python3 pi-api.py health
  python3 pi-api.py models | head -20
  echo
  echo "If health is ok and the models list, the setup is DONE."
  echo "Try: python3 pi-api.py prompt \"Say OK\" --model xingchi/gpt-6.1-sol"
else
  say "Manual steps that remain (do these, then re-run with --tailnet)"
  cat <<'EOF'
1. Altare console (browser): create the sandbox if you have not yet
   (team token cannot create one — use the console). Note the team ID
   and server ID, and set ALTARE_TEAM / ALTARE_SERVER.
2. Altare web console terminal (browser), as root:
     bash /root/work/setup/setup-sandbox.sh
   It installs Node + Pi + Tailscale, places the bundle files, starts
   the gateway and watcher in tmux, and prints the sandbox tailnet IP.
   When it prints a Tailscale login URL, open it and approve the
   device (it will appear as pi-altare).
3. Approve the sandbox device in the Tailscale admin console
   (login.tailscale.com/admin/machines) if it asks.
4. Re-run this script with the tailnet IP it printed:
     ./setup-muse.sh --tailnet <ip>
   That writes tailnet-url.txt and runs the health check.
5. First request to a new tailnet address needs one approval from you
   (Muse will show it). Approve it once, then re-run the health check.
EOF
fi

say "Done"
echo "Gateway token (save this somewhere safe — it is also in gateway-token.txt):"
echo "$TOKEN"
