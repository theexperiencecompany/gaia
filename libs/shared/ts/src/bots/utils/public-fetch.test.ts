import { beforeEach, describe, expect, it, vi } from "vitest";

// Deterministic fake resolver so the tests never touch the network. Anything
// not in the table resolves to a public address, and an IP literal resolves to
// itself (mirroring real dns.lookup) so it can never slip past via the fallback.
vi.mock("node:dns/promises", () => {
  const IPV4_LITERAL = /^(\d{1,3}\.){3}\d{1,3}$/;
  const IPV6_LITERAL = /:/;
  return {
    lookup: vi.fn(async (hostname: string) => {
      if (IPV4_LITERAL.test(hostname) || IPV6_LITERAL.test(hostname)) {
        return [
          {
            address: hostname,
            family: IPV4_LITERAL.test(hostname) ? 4 : 6,
          },
        ];
      }
      const table: Record<string, string[]> = {
        "res.cloudinary.com": ["146.112.61.108"],
        "example.com": ["93.184.215.14"],
        "internal.local": ["10.0.0.5"],
        localhost: ["127.0.0.1"],
        "v4mapped.example": ["::ffff:10.0.0.5"],
      };
      const addresses = table[hostname] ?? ["93.184.215.14"];
      return addresses.map((address) => ({
        address,
        family: address.includes(":") ? 6 : 4,
      }));
    }),
  };
});

import {
  assertIsPublicHttpsUrl,
  fetchPublicAsset,
  isNonPublicAddress,
} from "./public-fetch";

describe("isNonPublicAddress", () => {
  it("flags IPv4 private/reserved/link-local ranges", () => {
    expect(isNonPublicAddress("10.0.0.5")).toBe(true);
    expect(isNonPublicAddress("172.16.0.1")).toBe(true);
    expect(isNonPublicAddress("192.168.1.1")).toBe(true);
    expect(isNonPublicAddress("127.0.0.1")).toBe(true);
    expect(isNonPublicAddress("169.254.169.254")).toBe(true);
    expect(isNonPublicAddress("100.64.0.1")).toBe(true);
    expect(isNonPublicAddress("198.18.0.1")).toBe(true);
    expect(isNonPublicAddress("0.0.0.0")).toBe(true);
  });

  it("allows public IPv4 addresses", () => {
    expect(isNonPublicAddress("8.8.8.8")).toBe(false);
    expect(isNonPublicAddress("146.112.61.108")).toBe(false);
  });

  it("flags IPv6 loopback/ULA/link-local/documentation ranges", () => {
    expect(isNonPublicAddress("::1")).toBe(true);
    expect(isNonPublicAddress("fc00::1")).toBe(true);
    expect(isNonPublicAddress("fe80::1")).toBe(true);
    expect(isNonPublicAddress("2001:db8::1")).toBe(true);
    expect(isNonPublicAddress("::ffff:10.0.0.5")).toBe(true);
  });

  it("allows public IPv6 addresses", () => {
    expect(isNonPublicAddress("2606:4700::1111")).toBe(false);
  });

  it("treats an unparsable value as non-public", () => {
    expect(isNonPublicAddress("not-an-ip")).toBe(true);
  });
});

describe("assertIsPublicHttpsUrl", () => {
  const rejects = async (url: string) => {
    await expect(assertIsPublicHttpsUrl(url)).rejects.toThrow();
  };

  it("rejects non-https schemes", async () => {
    await rejects("http://example.com/x");
    await rejects("ftp://example.com/x");
  });

  it("rejects URLs carrying userinfo", async () => {
    await rejects("https://evil@example.com/x");
    await rejects("https://user:pass@example.com/x");
  });

  it("rejects literal private/link-local IPs", async () => {
    await rejects("https://169.254.169.254/latest/meta-data/");
    await rejects("https://10.0.0.5/x");
  });

  it("rejects hostnames that resolve to private addresses", async () => {
    await rejects("https://internal.local/x");
    await rejects("https://localhost/x");
    await rejects("https://v4mapped.example/x");
  });

  it("accepts public FQDNs and public literal IPs", async () => {
    await expect(
      assertIsPublicHttpsUrl("https://example.com/x"),
    ).resolves.toBeUndefined();
    await expect(
      assertIsPublicHttpsUrl("https://res.cloudinary.com/x"),
    ).resolves.toBeUndefined();
  });
});

describe("fetchPublicAsset", () => {
  const okBody = new Uint8Array([1, 2, 3, 4]);
  const LIMITS = { maxContentLength: 1024, maxBodyLength: 1024 };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches bytes and exposes content-type on the happy path", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(okBody, {
          status: 200,
          headers: { "content-type": "image/png" },
        }),
    );
    const result = await fetchPublicAsset(
      "https://example.com/a.png",
      LIMITS,
      fetcher,
    );
    expect(result.data).toEqual(Buffer.from(okBody));
    expect(result.contentType).toBe("image/png");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("refuses to follow a redirect that lands on a private host", async () => {
    const fetcher = vi.fn(
      async (url: string) =>
        new Response(null, {
          status: 302,
          headers: { location: `https://internal.local/secrets` },
        }),
    );
    await expect(
      fetchPublicAsset("https://example.com/x", LIMITS, fetcher),
    ).rejects.toThrow(/non-public/i);
    // The redirect destination was validated before the second request went out.
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("follows safe redirects up to the cap", async () => {
    const fetcher = vi.fn(async (url: string) =>
      url === "https://example.com/b.png"
        ? new Response(okBody, { status: 200 })
        : new Response(null, {
            status: 302,
            headers: { location: "https://example.com/b.png" },
          }),
    );
    const result = await fetchPublicAsset(
      "https://example.com/a.png",
      LIMITS,
      fetcher,
    );
    expect(result.data).toEqual(Buffer.from(okBody));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("stops after too many redirects", async () => {
    const fetcher = vi.fn(
      async (url: string) =>
        new Response(null, {
          status: 302,
          headers: { location: "https://example.com/loop" },
        }),
    );
    await expect(
      fetchPublicAsset("https://example.com/start", LIMITS, fetcher),
    ).rejects.toThrow(/too many redirects/i);
  });

  it("rejects a body over the content cap", async () => {
    const big = new Uint8Array(2048);
    const fetcher = vi.fn(async () => new Response(big, { status: 200 }));
    await expect(
      fetchPublicAsset("https://example.com/big", LIMITS, fetcher),
    ).rejects.toThrow(/content cap/i);
  });
});
