import * as net from "node:net";
import { describe, expect, it } from "vitest";
import {
  certificateProblem,
  hasValidCertificate,
  judgeDomainDns,
} from "../../src/lib/domain-reachability.js";

const DOMAIN = "gaia.example.com";

/** A Caddy 2.10 tls.obtain error line, as `docker logs` prints it. */
function obtainError(error: string, identifier = DOMAIN): string {
  return JSON.stringify({
    level: "error",
    ts: 1792551941.3,
    logger: "tls.obtain",
    msg: "could not get certificate from issuer",
    identifier,
    issuer: "acme-v02.api.letsencrypt.org-directory",
    error,
  });
}

describe("judgeDomainDns", () => {
  it("is quiet when the domain points at this machine", () => {
    expect(
      judgeDomainDns(DOMAIN, ["203.0.113.7"], {
        addresses: ["203.0.113.7"],
        publicKnown: true,
      }),
    ).toBeNull();
  });

  it("names a missing record and the address to point it at", () => {
    const warning = judgeDomainDns(DOMAIN, [], {
      addresses: ["203.0.113.7"],
      publicKnown: true,
    });

    expect(warning).toContain(`${DOMAIN} has no DNS A or AAAA record`);
    expect(warning).toContain("203.0.113.7");
  });

  it("names where the domain points instead", () => {
    const warning = judgeDomainDns(DOMAIN, ["198.51.100.9"], {
      addresses: ["203.0.113.7", "2001:db8::7"],
      publicKnown: true,
    });

    expect(warning).toContain("points to 198.51.100.9");
    expect(warning).toContain("A record at 203.0.113.7");
  });

  it("says it couldn't confirm when this machine's public address is unknown", () => {
    const warning = judgeDomainDns(DOMAIN, ["198.51.100.9"], {
      addresses: ["10.0.0.4"],
      publicKnown: false,
    });

    expect(warning).toMatch(/Couldn't confirm/);
  });
});

describe("certificateProblem", () => {
  it("names Let's Encrypt's rate limit", () => {
    const problem = certificateProblem(DOMAIN, [
      obtainError(
        "HTTP 429 urn:ietf:params:acme:error:rateLimited - too many certificates (5) already issued for this exact set of identifiers in the last 168h0m0s",
      ),
    ]);

    expect(problem).toMatch(/rate limit/);
    expect(problem).toContain("letsencrypt.org/docs/rate-limits");
  });

  it("names a firewall that keeps Let's Encrypt off port 80, pointing past the host firewall", () => {
    const problem = certificateProblem(DOMAIN, [
      obtainError(
        `HTTP 400 urn:ietf:params:acme:error:connection - 203.0.113.7: Fetching http://${DOMAIN}/.well-known/acme-challenge/x: Timeout during connect (likely firewall problem)`,
      ),
    ]);

    expect(problem).toContain("couldn't reach this machine on port 80");
    expect(problem).toContain("security group");
  });

  it("names a DNS problem", () => {
    const problem = certificateProblem(DOMAIN, [
      obtainError(
        `HTTP 400 urn:ietf:params:acme:error:dns - DNS problem: NXDOMAIN looking up A for ${DOMAIN}`,
      ),
    ]);

    expect(problem).toContain("DNS");
  });

  it("quotes an error it has no words for, as Caddy wrote it", () => {
    const problem = certificateProblem(DOMAIN, [
      obtainError(
        `HTTP 400 urn:ietf:params:acme:error:rejectedIdentifier - Invalid identifiers requested :: Cannot issue for "${DOMAIN}": Domain name does not end with a valid public suffix (TLD)`,
      ),
    ]);

    expect(problem).toContain("does not end with a valid public suffix");
  });

  it("forgets an earlier error once the certificate was obtained", () => {
    expect(
      certificateProblem(DOMAIN, [
        obtainError("HTTP 429 urn:ietf:params:acme:error:rateLimited - x"),
        JSON.stringify({
          level: "info",
          logger: "tls.obtain",
          msg: "certificate obtained successfully",
          identifier: DOMAIN,
        }),
      ]),
    ).toBeNull();
  });

  it("ignores other domains and lines that are not JSON", () => {
    expect(
      certificateProblem(DOMAIN, [
        "plain text",
        obtainError("HTTP 429 rateLimited", "other.example.org"),
      ]),
    ).toBeNull();
  });
});

describe("hasValidCertificate", () => {
  it("is false when nothing answers HTTPS", async () => {
    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, resolve));
    const port = (server.address() as net.AddressInfo).port;
    await new Promise<void>((resolve) => server.close(() => resolve()));

    expect(await hasValidCertificate(DOMAIN, port)).toBe(false);
  });

  it("is false when the server's certificate isn't trusted for the domain", async () => {
    // A plain TCP server that hangs up: the TLS handshake fails.
    const server = net.createServer((socket) => socket.destroy());
    await new Promise<void>((resolve) => server.listen(0, resolve));
    const port = (server.address() as net.AddressInfo).port;
    try {
      expect(await hasValidCertificate(DOMAIN, port)).toBe(false);
    } finally {
      server.close();
    }
  });
});
