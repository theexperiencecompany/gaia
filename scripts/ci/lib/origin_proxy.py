"""Serve a local build as its production origin to a crawler that cannot remap hosts.

squirrel audits the origin it is given, and a local build's sitemap, canonicals and
links all name https://heygaia.io, so audited at localhost every sitemap URL is
"another domain". Behind this HTTPS proxy the crawler fetches https://heygaia.io and
the local server answers: CONNECT to a site host is terminated with a certificate
from a throwaway CA (the crawler trusts it through NODE_EXTRA_CA_CERTS) and piped to
the origin, so the server sees Host: heygaia.io. Every other host is refused, so the
audit never reaches the live site.
"""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import urllib.parse

HEAD_LIMIT = 65536
CHUNK = 65536
CERT_DAYS = "2"


def make_certificates(cert_dir: Path, hosts: list[str]) -> tuple[Path, Path]:
    """Write a throwaway CA (ca.pem) and a leaf for hosts it signs; return the leaf's cert and key."""
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_key, ca_pem = cert_dir / "ca.key", cert_dir / "ca.pem"
    key, csr, pem = cert_dir / "site.key", cert_dir / "site.csr", cert_dir / "site.pem"
    ext = cert_dir / "site.ext"
    ext.write_text(
        "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=" + ",".join(f"DNS:{h}" for h in hosts) + "\n"
    )
    ca_ext = cert_dir / "ca.ext"
    ca_ext.write_text("basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign\n")
    for command in (
        ["openssl", "genrsa", "-out", str(ca_key), "2048"],
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(ca_key),
            "-subj",
            "/CN=gaia-seo-audit CA",
            "-out",
            str(cert_dir / "ca.csr"),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(cert_dir / "ca.csr"),
            "-signkey",
            str(ca_key),
            "-days",
            CERT_DAYS,
            "-extfile",
            str(ca_ext),
            "-out",
            str(ca_pem),
        ],
        ["openssl", "genrsa", "-out", str(key), "2048"],
        ["openssl", "req", "-new", "-key", str(key), "-subj", f"/CN={hosts[0]}", "-out", str(csr)],
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(ca_pem),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-days",
            CERT_DAYS,
            "-extfile",
            str(ext),
            "-out",
            str(pem),
        ],
    ):
        subprocess.run(command, check=True, capture_output=True)
    return pem, key


def _pump(source: socket.socket, sink: socket.socket) -> None:
    """Copy source to sink until either side closes, then close both."""
    # A reset or a socket the other pump already shut is how a tunnel ends, not a failure.
    with contextlib.suppress(OSError):
        while data := source.recv(CHUNK):
            sink.sendall(data)
    for sock in (source, sink):
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)


def _read_head(client: socket.socket) -> bytes:
    head = b""
    while b"\r\n\r\n" not in head and len(head) < HEAD_LIMIT:
        chunk = client.recv(4096)
        if not chunk:
            break
        head += chunk
    return head


def _handle(
    client: socket.socket, hosts: set[str], origin: tuple[str, int], tls: ssl.SSLContext
) -> None:
    with client:
        request_line = _read_head(client).split(b"\r\n", 1)[0].decode("latin-1")
        method, _, target = request_line.partition(" ")
        host, _, port = target.split(" ", 1)[0].rpartition(":")
        if method != "CONNECT" or host not in hosts or port != "443":
            client.sendall(
                b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            print(f"origin-proxy: refused {request_line!r}", file=sys.stderr, flush=True)
            return
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        try:
            secure = tls.wrap_socket(client, server_side=True)
        except (ssl.SSLError, OSError) as exc:
            print(
                f"origin-proxy: TLS handshake for {host} failed: {exc}", file=sys.stderr, flush=True
            )
            return
        with secure, socket.create_connection(origin) as upstream:
            back = threading.Thread(target=_pump, args=(upstream, secure), daemon=True)
            back.start()
            _pump(secure, upstream)
            back.join()


def serve(listener: socket.socket, hosts: set[str], origin: str, cert: Path, key: Path) -> None:
    """Accept proxy connections on listener forever, tunnelling site hosts to origin."""
    parsed = urllib.parse.urlparse(origin)
    if parsed.scheme != "http" or parsed.hostname is None or parsed.port is None:
        raise SystemExit(f"origin-proxy: origin must be http://host:port, got {origin}")
    tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    tls.load_cert_chain(cert, key)
    while True:
        client, _ = listener.accept()
        threading.Thread(
            target=_handle, args=(client, hosts, (parsed.hostname, parsed.port), tls), daemon=True
        ).start()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site", required=True, help="the production origin, e.g. https://heygaia.io"
    )
    parser.add_argument(
        "--origin", required=True, help="the local server, e.g. http://127.0.0.1:3000"
    )
    parser.add_argument("--cert-dir", type=Path, required=True, help="where ca.pem is written")
    parser.add_argument(
        "--port-file", type=Path, required=True, help="written with the port once listening"
    )
    args = parser.parse_args()
    site_host = urllib.parse.urlparse(args.site).hostname
    if site_host is None:
        raise SystemExit(f"origin-proxy: no host in --site {args.site}")
    hosts = [site_host, f"www.{site_host}"]
    cert, key = make_certificates(args.cert_dir, hosts)
    listener = socket.create_server(("127.0.0.1", 0))
    args.port_file.write_text(str(listener.getsockname()[1]))
    serve(listener, set(hosts), args.origin, cert, key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
