/**
 * SSRF guards for direct outbound fetches in the bot processes.
 *
 * Bots fetch attachment bytes straight from CDN URLs the API publishes (signed
 * R2 screenshots), so the URL itself is the authorization. That makes the fetch
 * path a potential SSRF proxy: anyone who can place a URL on the bot queue must
 * not be able to turn the bot into a reader of internal services.
 *
 * This mirrors the API's policy in `apps/api/app/utils/url_safety.py`:
 *   * HTTPS only — a cleartext hop would leak the signed asset on the wire.
 *   * no hop may resolve to a private, loopback, link-local (incl. the cloud
 *     metadata address 169.254.169.254), reserved, CGNAT, or otherwise
 *     non-public address — checked on *every* redirect destination, not just
 *     the first URL, so a redirect can't smuggle the chain back inside.
 *   * the guard runs at DNS-resolution time via `node:dns/promises`, so a
 *     hostname that happens to resolve internally is caught before the request
 *     is dialed (no check/dial differential).
 *
 * IPv4 is classified with `node:net.BlockList` (the same classifier Undici
 * uses); IPv6 is classified against an explicit prefix table because BlockList
 * only supports IPv4 subnets.
 */

import { lookup } from "node:dns/promises";
import { BlockList, isIP } from "node:net";

const MAX_REDIRECTS = 5; // parity with app/constants/search.py MAX_HTTPX_REDIRECTS

const NON_PUBLIC_IPV4 = new BlockList();

// IPv4: private / loopback / link-local (incl. cloud metadata) / CGNAT /
// benchmarking / documentation / multicast / reserved.
NON_PUBLIC_IPV4.addSubnet("0.0.0.0", 8);
NON_PUBLIC_IPV4.addSubnet("10.0.0.0", 8);
NON_PUBLIC_IPV4.addSubnet("100.64.0.0", 10);
NON_PUBLIC_IPV4.addSubnet("127.0.0.0", 8);
NON_PUBLIC_IPV4.addSubnet("169.254.0.0", 16);
NON_PUBLIC_IPV4.addSubnet("172.16.0.0", 12);
NON_PUBLIC_IPV4.addSubnet("192.0.0.0", 24);
NON_PUBLIC_IPV4.addSubnet("192.0.2.0", 24);
NON_PUBLIC_IPV4.addSubnet("192.88.99.0", 24);
NON_PUBLIC_IPV4.addSubnet("192.168.0.0", 16);
NON_PUBLIC_IPV4.addSubnet("198.18.0.0", 15);
NON_PUBLIC_IPV4.addSubnet("198.51.100.0", 24);
NON_PUBLIC_IPV4.addSubnet("203.0.113.0", 24);
NON_PUBLIC_IPV4.addSubnet("224.0.0.0", 4);
NON_PUBLIC_IPV4.addSubnet("240.0.0.0", 4);
NON_PUBLIC_IPV4.addSubnet("255.255.255.255", 32);

// IPv6 non-public prefixes as (128-bit bigint, prefix length).
// [hextet values of the prefix, prefix length] — the parser expands any `::`.
const IPV6_PRIVATE_RANGES: ReadonlyArray<readonly [string, number]> = [
  ["::", 128], // unspecified address
  ["::1", 128], // loopback
  ["::ffff:0:0", 96], // IPv4-mapped (embedded v4 checked as v4 below)
  ["64:ff9b::", 96], // NAT64 well-known prefix
  ["100::", 64], // discard-only
  ["2001::", 32], // Teredo
  ["2001:2::", 48], // benchmarking
  ["2001:10::", 28], // ORCHIDv2
  ["2001:db8::", 32], // documentation
  ["fc00::", 7], // unique local addressing
  ["fe80::", 10], // link-local
  ["ff00::", 8], // multicast
];

class PublicFetchError extends Error {
  constructor(message: string) {
    super(`refusing to fetch non-public/unsafe asset URL: ${message}`);
    this.name = "PublicFetchError";
  }
}

/** Expand an IPv6 literal (allowing `::` compression) into a 128-bit BigInt. */
export function parseIpv6ToBigInt(ip: string): bigint {
  let groups: string[];
  const comp = ip.indexOf("::");
  if (comp !== -1) {
    const left = ip.slice(0, comp) || "0";
    const right = ip.slice(comp + 2) || "0";
    const l = left.split(":").filter(Boolean);
    const r = right.split(":").filter(Boolean);
    if (l.length + r.length > 8) {
      throw new RangeError(`malformed IPv6 address: ${ip}`);
    }
    const zeros = 8 - l.length - r.length;
    groups = [...l, ...Array<string>(zeros).fill("0"), ...r];
  } else {
    groups = ip.split(":").filter(Boolean);
    if (groups.length !== 8) {
      throw new RangeError(`malformed IPv6 address: ${ip}`);
    }
  }
  let value = 0n;
  for (const hex of groups) {
    if (!/^[0-9a-f]{1,4}$/i.test(hex)) {
      throw new RangeError(`malformed IPv6 hextet: ${hex}`);
    }
    value = (value << 16n) | BigInt(parseInt(hex, 16));
  }
  return value;
}

function rangeMatches(addr: bigint, prefix: bigint, length: number): boolean {
  return addr >> BigInt(128 - length) === prefix >> BigInt(128 - length);
}

function isPrivateIpv6Literal(ip: string): boolean {
  const addr = parseIpv6ToBigInt(ip);
  for (const [range, length] of IPV6_PRIVATE_RANGES) {
    try {
      if (rangeMatches(addr, parseIpv6ToBigInt(range), length)) {
        return true;
      }
    } catch {
      // A malformed range entry would have failed for every address; a single
      // literal that fails parsing is already handled by the caller.
    }
  }
  // IPv4-mapped (::ffff:a.b.c.d) — classify the embedded IPv4 with the v4 table.
  const mapped = ip.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/i);
  if (mapped) {
    return isNonPublicIpv4Literal(mapped[1]);
  }
  return false;
}

function isNonPublicIpv4Literal(ipv4: string): boolean {
  try {
    return NON_PUBLIC_IPV4.check(ipv4);
  } catch {
    return true; // not a parseable v4 literal — do not dial it
  }
}

/** True when the given IP literal (v4 or v6) falls in a non-public range. */
export function isNonPublicAddress(ip: string): boolean {
  const family = isIP(ip);
  if (family === 4) {
    return isNonPublicIpv4Literal(ip);
  }
  if (family === 6) {
    try {
      return isPrivateIpv6Literal(ip);
    } catch {
      return true;
    }
  }
  return true; // not an IP literal at all — treat as non-public for literal checks
}

function assertPublicResolvedAddresses(
  addresses: readonly { address: string }[],
): void {
  if (addresses.length === 0) {
    throw new PublicFetchError("hostname resolved to no addresses");
  }
  for (const { address } of addresses) {
    if (isNonPublicAddress(address)) {
      throw new PublicFetchError(`resolved to non-public address ${address}`);
    }
  }
}

function assertPublicHttpsUrl(url: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new PublicFetchError("malformed URL");
  }
  if (parsed.protocol !== "https:") {
    throw new PublicFetchError(
      `unsupported scheme ${parsed.protocol} (https required)`,
    );
  }
  if (!parsed.hostname) {
    throw new PublicFetchError("URL has no host");
  }
  // userinfo would let an attacker smuggle a different authority past a naive
  // host check (`https://evil@internal.host/`) — reject it outright.
  if (parsed.username || parsed.password) {
    throw new PublicFetchError("URL must not carry userinfo");
  }
  return parsed;
}

/** Resolve-time SSRF guard for a single https hop (literal IPs + DNS). */
export async function assertIsPublicHttpsUrl(url: string): Promise<void> {
  const parsed = assertPublicHttpsUrl(url);
  const lookedUp = await lookup(parsed.hostname, { all: true, verbatim: true });
  assertPublicResolvedAddresses(lookedUp);
}

/**
 * Fetch an https asset with the SSRF guard applied on every redirect hop.
 *
 * Returns the body buffer plus the response's content-type, preserving the
 * contract `downloadUrlRequest` had before the guard — so callers that only
 * needed bytes keep working unchanged.
 */
export async function fetchPublicAsset(
  url: string,
  limits: { maxContentLength: number; maxBodyLength: number },
  fetcher: typeof fetch = fetch,
  maxRedirects: number = MAX_REDIRECTS,
): Promise<{ data: Buffer; contentType: string }> {
  let current = url;
  for (let hop = 0; hop <= maxRedirects; hop += 1) {
    const parsed = assertPublicHttpsUrl(current);
    const lookedUp = await lookup(parsed.hostname, {
      all: true,
      verbatim: true,
    });
    assertPublicResolvedAddresses(lookedUp);

    const response = await fetcher(current, {
      redirect: "manual",
      signal: AbortSignal.timeout(60_000),
    });
    const contentType =
      response.headers.get("content-type") ?? "application/octet-stream";

    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (!location) {
        throw new PublicFetchError(`redirect without Location at hop ${hop}`);
      }
      const next = new URL(location, current).toString();
      // The next hop gets the full resolve-time check at the top of this loop;
      // catching a redirect to a banned host here only shortens the error path.
      const nextParsed = assertPublicHttpsUrl(next);
      const nextAddr = await lookup(nextParsed.hostname, {
        all: true,
        verbatim: true,
      });
      assertPublicResolvedAddresses(nextAddr);
      current = next;
      continue;
    }

    if (!response.ok) {
      throw new PublicFetchError(
        `server responded with status ${response.status}`,
      );
    }

    const body = Buffer.from(await response.arrayBuffer());
    if (body.byteLength > limits.maxContentLength) {
      throw new PublicFetchError("body exceeds the configured content cap");
    }
    return { data: body, contentType };
  }
  throw new PublicFetchError(`too many redirects (≥ ${maxRedirects + 1})`);
}
