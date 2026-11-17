"""Serve a local build as its production origin to a crawler that cannot remap hosts.

squirrel audits the origin it is given, and a local build's sitemap, canonicals and
links all name https://heygaia.io, so audited at localhost every sitemap URL is
"another domain". Behind this HTTPS proxy the crawler fetches https://heygaia.io and
the local server answers: CONNECT to a site host is terminated with a certificate
from a throwaway CA (the crawler trusts it through NODE_EXTRA_CA_CERTS) and piped to
the origin, so the server sees Host: heygaia.io. Every other host is refused, so the
audit never reaches the live site.

With --sitemap the proxy answers /sitemap.xml itself, listing only that file's URLs:
squirrel picks the pages it audits from the sitemap, never from the URL it is given,
so this is how a run audits a chosen set of pages and nothing else.
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
from xml.sax.saxutils import escape

HEAD_LIMIT = 65536
CHUNK = 65536
CERT_DAYS = "2"
SITEMAP_PATH = "/sitemap.xml"
HEAD_END = b"\r\n\r\n"


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
    while HEAD_END not in head and len(head) < HEAD_LIMIT:
        chunk = client.recv(4096)
        if not chunk:
            break
        head += chunk
    return head


def sitemap_response(urls: list[str]) -> bytes:
    """Render a sitemap listing exactly urls as a complete HTTP response that closes the connection."""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{escape(url)}</loc></url>\n" for url in urls)
        + "</urlset>\n"
    ).encode()
    head = (
        "HTTP/1.1 200 OK\r\nContent-Type: application/xml\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    )
    return head.encode() + body


def _content_length(head: bytes) -> int:
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"transfer-encoding":
            raise ValueError("a chunked request body")
        if name.strip().lower() == b"content-length":
            return int(value.strip())
    return 0


def _forward_requests(source: socket.socket, sink: socket.socket, sitemap: bytes | None) -> None:
    """Copy requests from source to sink one at a time, answering the sitemap path from sitemap.

    The sitemap answer closes the connection, so it can never interleave with an origin
    response still in flight: a crawler that does not pipeline sends its next request only
    after the previous answer, on this connection or a new one.
    """
    buffer = b""
    with contextlib.suppress(OSError):
        while True:
            while HEAD_END not in buffer:
                if not (chunk := source.recv(CHUNK)):
                    return
                buffer += chunk
            head, _, buffer = buffer.partition(HEAD_END)
            length = _content_length(head)
            while len(buffer) < length:
                if not (chunk := source.recv(CHUNK)):
                    return
                buffer += chunk
            body, buffer = buffer[:length], buffer[length:]
            parts = head.split(b" ", 2)
            if len(parts) < 3:
                raise ValueError(f"a malformed request line {head[:80]!r}")
            target = parts[1].decode("latin-1")
            if sitemap is not None and urllib.parse.urlsplit(target).path == SITEMAP_PATH:
                source.sendall(sitemap)
                return
            sink.sendall(head + HEAD_END + body)


def _handle(
    client: socket.socket,
    hosts: set[str],
    origin: tuple[str, int],
    tls: ssl.SSLContext,
    sitemap: bytes | None,
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
            try:
                _forward_requests(secure, upstream, sitemap)
            except ValueError as exc:
                print(f"origin-proxy: refused {exc}", file=sys.stderr, flush=True)
            for sock in (secure, upstream):
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)
            back.join()


def serve(
    listener: socket.socket,
    hosts: set[str],
    origin: str,
    cert: Path,
    key: Path,
    sitemap: bytes | None = None,
) -> None:
    """Accept proxy connections on listener forever, tunnelling site hosts to origin."""
    parsed = urllib.parse.urlparse(origin)
    if parsed.scheme != "http" or parsed.hostname is None or parsed.port is None:
        raise SystemExit(f"origin-proxy: origin must be http://host:port, got {origin}")
    tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    tls.load_cert_chain(cert, key)
    while True:
        client, _ = listener.accept()
        threading.Thread(
            target=_handle,
            args=(client, hosts, (parsed.hostname, parsed.port), tls, sitemap),
            daemon=True,
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
    parser.add_argument(
        "--sitemap",
        type=Path,
        help="answer /sitemap.xml with this file's URLs, one per line, instead of the origin's",
    )
    args = parser.parse_args()
    sitemap = sitemap_response(args.sitemap.read_text().split()) if args.sitemap else None
    site_host = urllib.parse.urlparse(args.site).hostname
    if site_host is None:
        raise SystemExit(f"origin-proxy: no host in --site {args.site}")
    hosts = [site_host, f"www.{site_host}"]
    cert, key = make_certificates(args.cert_dir, hosts)
    listener = socket.create_server(("127.0.0.1", 0))
    args.port_file.write_text(str(listener.getsockname()[1]))
    serve(listener, set(hosts), args.origin, cert, key, sitemap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
