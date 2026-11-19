#!/usr/bin/env python3
"""SSH ProxyCommand helper: open a TCP connection to a tailnet address
through the Muse runtime tunnel proxy (HTTPS_PROXY with port -> 3130),
using HTTP CONNECT with the proxy's own credentials from the environment.

Usage: ts-connect.py <host> <port>   (stdio is piped to the socket)
"""
import os
import socket
import sys
import threading
from urllib.parse import urlparse


def main() -> int:
    host, port = sys.argv[1], int(sys.argv[2])
    # ssh sets the proxy command's stdio to non-blocking; restore blocking
    # mode or os.read raises BlockingIOError, which looks like EOF and would
    # half-close the tunnel mid-handshake.
    for fd in (0, 1):
        try:
            os.set_blocking(fd, True)
        except OSError:
            pass
    u = urlparse(os.environ["HTTPS_PROXY"])
    proxy_host = u.hostname
    proxy_port = 3130
    s = socket.create_connection((proxy_host, proxy_port), timeout=30)
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if u.username:
        import base64

        cred = base64.b64encode(f"{u.username}:{u.password}".encode()).decode()
        req += f"Proxy-Authorization: Basic {cred}\r\n"
    req += "\r\n"
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            print("proxy closed during CONNECT", file=sys.stderr)
            return 1
        buf += chunk
    status = buf.split(b"\r\n", 1)[0]
    if b"200" not in status:
        print(f"CONNECT failed: {status!r}", file=sys.stderr)
        return 1
    # Any bytes after the header belong to the tunnel stream; none expected
    # for SSH (server speaks first, after CONNECT completes).

    def pump_in() -> None:
        try:
            while True:
                data = os.read(0, 65536)
                if not data:
                    break
                s.sendall(data)
        except OSError:
            pass
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    t = threading.Thread(target=pump_in, daemon=True)
    t.start()
    try:
        while True:
            data = s.recv(65536)
            if not data:
                break
            view = memoryview(data)
            while view:
                n = os.write(1, view)
                view = view[n:]
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
