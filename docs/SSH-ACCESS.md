# Direct SSH into the sandbox

Built 2026-11-20. Gives the operator's machine a real shell on the Pi
sandbox, so files and commands no longer have to go through the
provider's Files API (which rate-limits under burst use — 429s across
every endpoint, a cooldown rather than a ban, but enough to stall work).

## Why not OpenSSH — the chroot wall

The obvious setup fails here, in a way that looks like a network problem:
the connection completes the banner exchange and then closes, every time,
including from inside the box itself (`ssh root@127.0.0.1`).

Running the server in debug mode (`sshd -ddd -p 2222`) shows the cause:

```
chroot("/run/sshd"): Operation not permitted [preauth]
```

OpenSSH's privilege-separation child must `chroot()` into its privsep
directory before auth. The sandbox's seccomp filter denies `chroot`, the
child dies instantly, and the connection closes right after the banner.
OpenSSH 9.6 has no option to skip privilege separation, so **no sshd
configuration can work in this sandbox**.

## The working server: Dropbear

Dropbear has no privilege separation and nothing for the filter to kill:

```sh
apt-get install -y dropbear-bin
mkdir -p /etc/dropbear
dropbearkey -t ed25519 -f /etc/dropbear/dropbear_ed25519_host_key
chmod 600 /etc/dropbear/dropbear_ed25519_host_key
# your operator public key goes in /root/.ssh/authorized_keys (chmod 600,
# directory 700) — Dropbear reads the same file OpenSSH does
nohup dropbear -E -p 22 -s -g -r /etc/dropbear/dropbear_ed25519_host_key \
  > /tmp/dropbear.log 2>&1 &
```

`-s` disables password logins, `-g` disables root password logins —
together: public-key auth only, same policy as a hardened sshd.

The sandbox platform runs its own `altare-sshd` on a high port (25375).
That is platform infrastructure — leave it alone; it is not what answers
on port 22.

## Reaching it from Muse's VM — Tailscale + CONNECT proxy

The VM joins the tailnet as a client. Ordinary networking does not reach
the tailnet; TCP goes through the runtime tunnel proxy (the runtime's
HTTP proxy with its port changed to 3130) using HTTP CONNECT.
`bridge/ts-connect.py` is an ssh `ProxyCommand` that does exactly that —
CONNECT with the proxy's own credentials from the environment, then pipes
stdio. One gotcha baked into it: ssh sets the proxy command's stdio to
non-blocking, which makes a naive `os.read` raise `BlockingIOError` that
looks like EOF and half-closes the tunnel mid-handshake — the helper
restores blocking mode first.

`bridge/pi-ssh.sh` wraps the whole thing:

```sh
PI_BOX_ADDR=<sandbox-tailnet-ip> bridge/pi-ssh.sh 'cat /root/work/agentx/TASKS.md'
```

Outbound SSH from the VM needs the matching network permission enabled
in the Muse app (Settings → Permissions → Outbound SSH); the tailnet
address needs its one-time tunnel approval, which then covers all ports
on that address.

## Persistence caveat

The Dropbear start above is a plain background process — it does **not**
survive a sandbox power-cycle. If SSH stops answering after a restart,
start it again (a short Pi session can do it) or wire the same command
into whatever startup path you use for the gateway and watcher.
