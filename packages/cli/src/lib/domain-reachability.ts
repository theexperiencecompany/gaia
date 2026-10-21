/**
 * Whether a --domain can get its HTTPS certificate: before the start, does
 * its DNS point at this machine; after it, did Caddy get a certificate, and
 * if not, why (in Let's Encrypt's words, translated).
 * @module lib/domain-reachability
 */

import { promises as dns } from "node:dns";
import * as os from "node:os";
import { setTimeout as delay } from "node:timers/promises";
import * as tls from "node:tls";
import { execa } from "execa";
import { COMPOSE_PROJECT_BY_MODE } from "./docker.js";
import { fetchWithTimeout } from "./setup-endpoints.js";

/** Cloudflare's trace answers with the caller's address, by IP so no DNS is needed. */
const PUBLIC_ADDRESS_URLS = [
  "https://1.1.1.1/cdn-cgi/trace",
  "https://[2606:4700:4700::1111]/cdn-cgi/trace",
] as const;
const LOOKUP_TIMEOUT_MS = 4000;
const TLS_TIMEOUT_MS = 4000;
const PROXY_LOG_LINES = 300;
/** Caddy asks Let's Encrypt within seconds of starting; its first error follows soon after. */
const CERTIFICATE_WAIT_MS = 90_000;
const CERTIFICATE_POLL_MS = 3000;

/** The addresses that count as this machine, and whether its public ones were found. */
export interface MachineAddresses {
  addresses: string[];
  publicKnown: boolean;
}

/** The domain's A and AAAA records; none when it has no record yet. */
async function domainRecords(domain: string): Promise<string[]> {
  const lookups = await Promise.allSettled([
    dns.resolve4(domain),
    dns.resolve6(domain),
  ]);
  const records: string[] = [];
  for (const lookup of lookups) {
    if (lookup.status === "fulfilled") {
      records.push(...lookup.value);
      continue;
    }
    const code = (lookup.reason as NodeJS.ErrnoException).code;
    if (code !== dns.NOTFOUND && code !== dns.NODATA) throw lookup.reason;
  }
  return records;
}

async function publicAddress(url: string): Promise<string | null> {
  try {
    const res = await fetchWithTimeout(url, undefined, LOOKUP_TIMEOUT_MS);
    const text = await res.text();
    return /^ip=(.+)$/m.exec(text)?.[1]?.trim() ?? null;
  } catch {
    // No route for this IP family (an IPv4-only box has no v6): the other lookup decides.
    return null;
  }
}

async function machineAddresses(): Promise<MachineAddresses> {
  const local = Object.values(os.networkInterfaces())
    .flat()
    .filter((iface) => iface !== undefined && !iface.internal)
    .map((iface) => iface?.address ?? "");
  const publicOnes = (
    await Promise.all(PUBLIC_ADDRESS_URLS.map(publicAddress))
  ).filter((address): address is string => address !== null);
  return {
    addresses: [...publicOnes, ...local],
    publicKnown: publicOnes.length > 0,
  };
}

/** One warning when the domain's DNS doesn't (yet) point here; null when it does. */
export function judgeDomainDns(
  domain: string,
  records: readonly string[],
  machine: MachineAddresses,
): string | null {
  if (records.some((record) => machine.addresses.includes(record))) return null;
  const target =
    (machine.publicKnown &&
      machine.addresses.find((address) => !address.includes(":"))) ||
    "this machine's public IP";
  if (records.length === 0) {
    return `${domain} has no DNS A or AAAA record yet, so HTTPS can't be set up. Add an A record pointing to ${target}.`;
  }
  if (!machine.publicKnown) {
    return `Couldn't confirm ${domain} (${records.join(", ")}) points here: this machine's public address couldn't be looked up.`;
  }
  return `${domain} points to ${records.join(", ")}, not this machine. Set its A record at ${target}; HTTPS works once it does (ignore this behind a proxy such as Cloudflare).`;
}

/** The DNS warning for a domain, looked up live. */
export async function checkDomainDns(domain: string): Promise<string | null> {
  const [records, machine] = await Promise.all([
    domainRecords(domain),
    machineAddresses(),
  ]);
  return judgeDomainDns(domain, records, machine);
}

interface CaddyLogEntry {
  level?: string;
  logger?: string;
  msg?: string;
  identifier?: string;
  error?: string;
}

function parseCaddyLine(line: string): CaddyLogEntry | null {
  if (!line.startsWith("{")) return null;
  try {
    return JSON.parse(line) as CaddyLogEntry;
  } catch {
    // A plain line Caddy printed before its logger started.
    return null;
  }
}

/** Let's Encrypt's error, said as what to change. */
function explainAcmeError(domain: string, error: string): string {
  if (/rateLimited|too many certificates/i.test(error)) {
    return `Let's Encrypt's rate limit for ${domain} was hit; Caddy retries on its own once it resets (https://letsencrypt.org/docs/rate-limits/).`;
  }
  if (
    /likely firewall problem|Timeout during connect|Connection refused/i.test(
      error,
    )
  ) {
    return "Let's Encrypt couldn't reach this machine on port 80. Open ports 80 and 443 to the internet in your cloud provider's firewall (security group) or router; Caddy retries on its own.";
  }
  if (/DNS problem|NXDOMAIN|no valid A records/i.test(error)) {
    return `Let's Encrypt can't find ${domain} in DNS yet. Point its A record at this machine; Caddy retries on its own.`;
  }
  if (/unauthorized|Invalid response/i.test(error)) {
    return `Let's Encrypt reached a different server for ${domain}: its DNS points somewhere else.`;
  }
  return `Caddy couldn't get a certificate: ${error}`;
}

/** Why Caddy has no certificate for the domain, from its log lines; null when nothing failed. */
export function certificateProblem(
  domain: string,
  lines: readonly string[],
): string | null {
  let problem: string | null = null;
  for (const entry of lines.map(parseCaddyLine)) {
    if (!entry?.logger?.startsWith("tls") || entry.identifier !== domain) {
      continue;
    }
    if (entry.msg === "certificate obtained successfully") problem = null;
    else if (entry.level === "error" && entry.error) {
      problem = explainAcmeError(domain, entry.error);
    }
  }
  return problem;
}

/** Whether the proxy on this machine serves a certificate trusted for the domain. */
export function hasValidCertificate(
  domain: string,
  httpsPort: number,
): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = tls.connect({
      host: "127.0.0.1",
      port: httpsPort,
      servername: domain,
      timeout: TLS_TIMEOUT_MS,
    });
    const done = (valid: boolean): void => {
      socket.destroy();
      resolve(valid);
    };
    socket.once("secureConnect", () => done(socket.authorized));
    socket.once("error", () => done(false));
    socket.once("timeout", () => done(false));
  });
}

/** The self-host proxy's last log lines; Caddy logs to stderr. */
async function readProxyLog(): Promise<string[]> {
  const { stdout: id } = await execa("docker", [
    "ps",
    "-q",
    "--filter",
    `label=com.docker.compose.project=${COMPOSE_PROJECT_BY_MODE.selfhost}`,
    "--filter",
    "label=com.docker.compose.service=proxy",
  ]);
  const container = id.trim().split("\n")[0];
  if (!container) return [];
  const { all } = await execa(
    "docker",
    ["logs", "--tail", String(PROXY_LOG_LINES), container],
    { all: true },
  );
  return (all ?? "").split("\n");
}

/**
 * Wait for the domain's certificate. Returns null once it is served, else
 * why it isn't: Caddy's reason as soon as it logs one, or that it is still
 * working on it when the wait runs out.
 */
export async function waitForCertificate(
  domain: string,
  httpsPort: number,
): Promise<string | null> {
  const deadline = Date.now() + CERTIFICATE_WAIT_MS;
  for (;;) {
    if (await hasValidCertificate(domain, httpsPort)) return null;
    const problem = certificateProblem(domain, await readProxyLog());
    if (problem) return problem;
    if (Date.now() >= deadline) {
      return `Caddy is still getting a certificate for ${domain}; it keeps trying. See its progress with 'gaia logs'.`;
    }
    await delay(CERTIFICATE_POLL_MS);
  }
}
