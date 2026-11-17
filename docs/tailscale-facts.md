# Tailscale facts

Inspection time: `2026-11-17 19:16:31 UTC`

No secrets, auth keys, or state-file contents are included.

## 1. Version and status

Command:

```text
tailscale version
```

Output:

```text
1.104.7
  tailscale commit: fb3b9b2964ace04490fbd65d4f26a0eaf362131f
  long version: 1.104.7-tfb3b9b296-g0651cc45e
  other commit: 0651cc45e79e308b0b3b808f4b42e7f3a1a8c221
  go version: go1.27.4 (tailscale/go 1635316a95)
```

Command:

```text
tailscale status
```

Output:

```text
failed to connect to local tailscaled (which appears to be running as tailscaled, pid 2278). Got error: Failed to connect to local Tailscale daemon for /localapi/v0/status; not running? Error: dial unix /var/run/tailscale/tailscaled.sock: connect: connection refused
```

The running daemon uses a non-default socket. Querying that socket directly:

```text
tailscale --socket=/root/tailscale/tailscaled.sock status
```

Output:

```text
<sandbox-tailnet-ip>   pi-altare  <tailscale-account>@  linux  -
<muse-tailnet-ip>  muse       <tailscale-account>@         idle, tx 52360 rx 11352
```

Thus the configured Tailscale hostname shown by status is `pi-altare`, and the daemon is reachable at `/root/tailscale/tailscaled.sock`.

## 2. Binary locations and `/root/tailscale`

Command:

```text
which tailscale tailscaled
```

Output:

```text
/usr/bin/tailscale
/usr/sbin/tailscaled
```

Command:

```text
ls -la /root/tailscale/
```

Output:

```text
total 212
drwx------  5 root root   4096 Nov 17 02:57 .
drwx------ 11 root root   4096 Nov 17 13:54 ..
-rw-------  1 root root  15989 Nov 17 02:57 derpmap.cached.json
drwx------  2 root root   4096 Nov 17 02:52 dns-cache
drwx------  3 root root   4096 Nov 17 02:57 files
drwx------  3 root root   4096 Nov 17 02:57 profile-data
-rw-r--r--  1 root root   5984 Nov 17 02:51 tailscaled-conf.log
-rw-r--r--  1 root root 135787 Nov 18 00:44 tailscaled-final.log
-rw-r--r--  1 root root   4078 Nov 17 02:50 tailscaled-stock.log
-rw-r--r--  1 root root   6931 Nov 17 02:48 tailscaled-verbose.log
-rw-r--r--  1 root root     76 Nov 17 02:50 tailscaled.conf
-rw-r--r--  1 root root   2509 Nov 17 02:29 tailscaled.log
srw-rw-rw-  1 root root      0 Nov 17 02:52 tailscaled.sock
-rw-------  1 root root   2887 Nov 17 02:57 tailscaled.state
-rw-r--r--  1 root root     93 Nov 17 02:52 up-output.txt
```

Command:

```text
cat /root/tailscale/tailscaled.conf 2>/dev/null
```

Output:

```json
{
  "Version": "alpha0",
  "Locked": false,
  "OperatorUser": "container"
}
```

## 3. Running process and full tailscaled command line

Command:

```text
ps aux | grep -i tailscale | grep -v grep
```

Output (the command was run with `ww` to retain full arguments):

```text
contain+    2275  0.0  0.0   4772  2152 pts/4    Ss+  Nov17   0:00 bash -c tailscaled --tun=userspace-networking --state=/root/tailscale/tailscaled.state --socket=/root/tailscale/tailscaled.sock --config=/root/tailscale/tailscaled.conf 2>&1 | tee /root/tailscale/tailscaled-final.log
contain+    2278  0.0  0.0 1290128 23932 pts/4   Sl+  Nov17   0:30 tailscaled --tun=userspace-networking --state=/root/tailscale/tailscaled.state --socket=/root/tailscale/tailscaled.sock --config=/root/tailscale/tailscaled.conf
contain+    2279  0.0  0.0   3152  1056 pts/4    S+   Nov17   0:00 tee /root/tailscale/tailscaled-final.log
contain+   11089  0.0  0.0 1281600 9260 ?        tsl  00:46   0:00 tailscale version
contain+   11090  0.0  0.0 1279936 7268 ?        tsl  00:46   0:00 tailscale status
```

The daemon command line is:

```text
tailscaled --tun=userspace-networking --state=/root/tailscale/tailscaled.state --socket=/root/tailscale/tailscaled.sock --config=/root/tailscale/tailscaled.conf
```

## 4. TUN device

Command:

```text
ls -la /dev/net/ 2>&1
```

Output:

```text
ls: cannot access '/dev/net/': No such file or directory
```

`/dev/net/tun` does not exist. The daemon is explicitly using `--tun=userspace-networking`.

## 5. Listening ports and Tailscale Serve

Command:

```text
ss -ltnp 2>/dev/null | grep -E '8765|1055'
```

Output:

```text
LISTEN 0      5          127.0.0.1:8765       0.0.0.0:*    users:(('python3',pid=9490,fd=3))
```

Nothing is listening on port `1055`. Port `8765` is listened to by `python3` PID `9490` on `127.0.0.1` only.

Command:

```text
tailscale serve status 2>&1
```

Output:

```text
getting serve config: Failed to connect to local Tailscale daemon for /localapi/v0/serve-config; not running? Error: dial unix /var/run/tailscale/tailscaled.sock: connect: connection refused
```

Using the actual daemon socket:

```text
tailscale --socket=/root/tailscale/tailscaled.sock serve status 2>&1
```

Output:

```text
No serve config
```

Therefore no Tailscale Serve configuration is present according to the running daemon.

## 6. tmux sessions

Command:

```text
tmux ls
```

Output:

```text
pi-bridge: 1 windows (created Tue Nov 17 00:43:00 2026)
pi-gateway: 1 windows (created Tue Nov 17 16:51:40 2026)
pi-tunnel: 1 windows (created Tue Nov 17 02:04:13 2026)
tailscaled: 1 windows (created Tue Nov 17 02:52:00 2026)
```

The `tailscaled` tmux pane startup command is:

```text
bash -c tailscaled --tun=userspace-networking --state=/root/tailscale/tailscaled.state --socket=/root/tailscale/tailscaled.sock --config=/root/tailscale/tailscaled.conf 2>&1 | tee /root/tailscale/tailscaled-final.log
```

The related tunnel pane is:

```text
cloudflared tunnel --url http://127.0.0.1:8765 --logfile /root/pi-bridge/tunnel.log
```

## 7. Installation source

Command:

```text
dpkg-query -W -f='${binary:Package}\t${Version}\t${Status}\n' '*tailscale*'
```

Output:

```text
tailscale	1.104.7	install ok installed
tailscale-archive-keyring	1.35.181	install ok installed
tailscale-relay		unknown ok not-installed
```

Command:

```text
dpkg-query -S /usr/bin/tailscale /usr/sbin/tailscaled
```

Output:

```text
tailscale: /usr/bin/tailscale
tailscale: /usr/sbin/tailscaled
```

APT source:

```text
/etc/apt/sources.list.d/tailscale.list:2:deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/ubuntu noble main
```

APT history records:

```text
Commandline: apt-get install -y tailscale tailscale-archive-keyring
Install: tailscale:amd64 (1.104.7), tailscale-archive-keyring:all (1.35.181), ...
```

The exact dpkg log entries show installation/configuration on `2026-11-17 02:17:52` through `02:17:55`. This is an APT installation from the official Tailscale stable Ubuntu Noble repository, not a static binary and not an identifiable standalone install-script binary.

## Reproduction from scratch

On a fresh Altare sandbox, install from the same repository with `curl -fsSL https://tailscale.com/install.sh | sh` (the resulting installation is the official APT repository installation), or equivalently configure the official Tailscale stable Ubuntu Noble repository and run `apt-get update && apt-get install -y tailscale tailscale-archive-keyring`; then create `/root/tailscale`, start the daemon in a tmux session with `tmux new-session -d -s tailscaled 'tailscaled --tun=userspace-networking --state=/root/tailscale/tailscaled.state --socket=/root/tailscale/tailscaled.sock --config=/root/tailscale/tailscaled.conf 2>&1 | tee /root/tailscale/tailscaled-final.log'`, run `tailscale --socket=/root/tailscale/tailscaled.sock up --hostname=pi-altare` interactively, complete the browser/device approval in the Tailscale admin console, and use the same socket for subsequent commands. The inspection shows hostname `pi-altare`, userspace networking, state at `/root/tailscale/tailscaled.state`, socket at `/root/tailscale/tailscaled.sock`, and config at `/root/tailscale/tailscaled.conf`; it does not expose the original login credential, so no secret login key is reproduced here.

## Restart order after a sandbox reboot

1. Ensure the `tailscaled` tmux session exists; if it does not, recreate `/root/tailscale` and start the daemon first:

```text
tmux new-session -d -s tailscaled 'tailscaled --tun=userspace-networking --state=/root/tailscale/tailscaled.state --socket=/root/tailscale/tailscaled.sock --config=/root/tailscale/tailscaled.conf 2>&1 | tee /root/tailscale/tailscaled-final.log'
```

2. Wait for `/root/tailscale/tailscaled.sock`, then verify the daemon with:

```text
tailscale --socket=/root/tailscale/tailscaled.sock status
```

3. If the node is not authenticated, run:

```text
tailscale --socket=/root/tailscale/tailscaled.sock up --hostname=pi-altare
```

Then complete the browser/device approval. Do not put an auth key in this report.

4. Start the dependent local service that listens on `127.0.0.1:8765` (currently `python3 /root/pi-bridge/pi-gateway.py`), and only after that start the tunnel session:

```text
tmux new-session -d -s pi-gateway 'python3 /root/pi-bridge/pi-gateway.py'
tmux new-session -d -s pi-tunnel 'cloudflared tunnel --url http://127.0.0.1:8765 --logfile /root/pi-bridge/tunnel.log'
```

The required order is therefore: Tailscale daemon, Tailscale status/authentication, local gateway on `127.0.0.1:8765`, then the `cloudflared` tunnel. No Tailscale Serve configuration is currently needed because the daemon reports `No serve config`.
