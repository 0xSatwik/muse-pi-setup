#!/bin/sh
# SSH into the Pi sandbox over the Tailscale tunnel.
#
# Why this shape: the sandbox runs Dropbear on port 22 (OpenSSH's server
# cannot run there — see docs/SSH-ACCESS.md), and Muse's VM reaches the
# tailnet only through the runtime tunnel proxy, so ssh goes through
# ts-connect.py as a ProxyCommand.
#
# Setup: set PI_BOX_ADDR to your sandbox's tailnet IP (100.x.y.z), and
# make sure your public key is in the sandbox's /root/.ssh/authorized_keys.
# Usage: pi-ssh.sh 'command...'   (or no args for an interactive shell)
ADDR="${PI_BOX_ADDR:-100.64.0.2}"
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec ssh \
  -o "ProxyCommand=python3 $DIR/ts-connect.py %h %p" \
  -i "$HOME/.ssh/id_ed25519" \
  -o ConnectTimeout=30 \
  -o StrictHostKeyChecking=accept-new \
  root@"$ADDR" "$@"
