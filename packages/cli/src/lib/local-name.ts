/**
 * gaia.local: names a self-host install on its home or office network with
 * portless (https://github.com/vercel-labs/portless). A root startup service
 * runs portless's proxy in LAN mode on plain HTTP port 80 and announces
 * gaia.local over mDNS (avahi on Linux, dns-sd on macOS); an alias routes the
 * name to GAIA's web port. Plain HTTP, so other devices meet no certificate.
 * A second GAIA on the same network takes gaia-2.local, mDNS's own numbering.
 * @module lib/local-name
 */

import * as fs from "node:fs";
import * as http from "node:http";
import * as os from "node:os";
import * as path from "node:path";
import { execa } from "execa";
import { z } from "zod";
import { readConfig, recordedLocalName } from "./config.js";
import { DEFAULT_WEB_PORT } from "./endpoints.js";
import {
  currentStableIpv6,
  installIpv6Publisher,
  removeIpv6Publisher,
} from "./local-name-ipv6.js";
import { existingLogNote, newLogPath } from "./logs.js";
import { isDebianAptLinux } from "./prerequisite-install.js";
import { runAsRoot } from "./root-command.js";

const LOCAL_NAME = "gaia";
/** The last of gaia, gaia-2 … gaia-9 tried when other GAIAs on the network hold the earlier ones. */
const LAST_LOCAL_NAME_NUMBER = 9;

function hostnameOf(name: string): string {
  return `${name}.local`;
}

/** The name to try first, then the next free ones in mDNS's own numbering. */
export function localNameCandidates(recorded: string | null): string[] {
  const numbered = Array.from(
    { length: LAST_LOCAL_NAME_NUMBER - 1 },
    (_, i) => `${LOCAL_NAME}-${i + 2}`,
  );
  const names = [LOCAL_NAME, ...numbered];
  return recorded ? [recorded, ...names.filter((n) => n !== recorded)] : names;
}

/** How copy names the recorded name: gaia-2.local, or a generic name before a run confirmed one. */
export function localNameLabel(recorded: string | true | undefined): string {
  const name = recordedLocalName(recorded);
  return name ? hostnameOf(name) : "GAIA's .local name";
}

/** Pinned: portless is pre-1.0 and its state format may change between releases. */
const PORTLESS_VERSION = "0.15.8";
const PORTLESS_MIN_NODE_MAJOR = 24;
const PORTLESS_PROXY_PORT = 80;

/** The proxy and mDNS each get this long to answer after a change. */
const SETTLE_TIMEOUT_MS = 15_000;
const SETTLE_POLL_MS = 500;
const PROBE_TIMEOUT_MS = 2_000;

/** What this run does about gaia.local. */
export type LocalNameAction = "set-up" | "remove" | "none";

/**
 * A served domain takes port 80 for Caddy, so it and --no-local-name both
 * mean no gaia.local; one an earlier run set up is then removed.
 */
export function localNameAction(input: {
  optedOut: boolean;
  domain: string | undefined;
  setUpBefore: boolean;
}): LocalNameAction {
  if (!input.optedOut && !input.domain) return "set-up";
  return input.setUpBefore ? "remove" : "none";
}

/** Why gaia.local can't be set up on this computer for GAIA on webPort, or null when it can. */
export function localNameBlocker(
  nodeVersion: string,
  platform: NodeJS.Platform,
  webPort: number,
): string | null {
  if (platform !== "linux" && platform !== "darwin") {
    return "it works only on Linux and macOS";
  }
  // GAIA's own proxy would answer every probe for the name, so nothing else could be told apart.
  if (webPort === PORTLESS_PROXY_PORT) {
    return `GAIA itself uses port ${PORTLESS_PROXY_PORT}, which the name's proxy needs; run 'gaia up --web-port ${DEFAULT_WEB_PORT}' to move GAIA off it`;
  }
  const version = nodeVersion.replace(/^v/, "");
  if (Number.parseInt(version, 10) < PORTLESS_MIN_NODE_MAJOR) {
    return `it needs Node.js ${PORTLESS_MIN_NODE_MAJOR} or newer, and this is Node.js ${version}`;
  }
  return null;
}

/** The npm that belongs to the Node running this CLI, so portless lands beside it. */
function npmCommand(): string {
  return path.join(path.dirname(process.execPath), "npm");
}

async function portlessEntry(): Promise<string> {
  const { stdout } = await execa(npmCommand(), ["root", "-g"]);
  return path.join(stdout.trim(), "portless", "dist", "cli.js");
}

const PackageManifestSchema = z.object({ version: z.string() });

function installedPortlessVersion(entry: string): string | null {
  const manifest = path.join(path.dirname(entry), "..", "package.json");
  if (!fs.existsSync(manifest)) return null;
  return PackageManifestSchema.parse(
    JSON.parse(fs.readFileSync(manifest, "utf-8")),
  ).version;
}

/** Install the pinned portless with this Node's npm unless it is already there. */
async function ensurePortless(logPath: string): Promise<string> {
  const entry = await portlessEntry();
  if (installedPortlessVersion(entry) === PORTLESS_VERSION) return entry;
  const result = await execa(
    npmCommand(),
    [
      "install",
      "-g",
      "--no-fund",
      "--no-audit",
      `portless@${PORTLESS_VERSION}`,
    ],
    { all: true, reject: false },
  );
  fs.appendFileSync(logPath, result.all ?? "");
  if (result.failed) {
    throw new Error(
      `installing portless with npm failed (output in ${logPath})`,
    );
  }
  return entry;
}

function hasCommand(command: string): Promise<boolean> {
  return execa("sh", ["-c", `command -v ${command}`], { reject: false }).then(
    (result) => !result.failed,
  );
}

/** avahi's publisher, which portless announces names with on Linux. */
async function ensureAvahi(logPath: string): Promise<void> {
  if (process.platform !== "linux") return;
  if (await hasCommand("avahi-publish-address")) return;
  if (!isDebianAptLinux()) {
    throw new Error(
      "it needs avahi-utils (avahi-publish-address); install it, then run 'gaia up' again",
    );
  }
  await runAsRoot("apt-get", ["update"], logPath);
  await runAsRoot("apt-get", ["install", "-y", "avahi-utils"], logPath);
}

async function runPortless(entry: string, args: string[]): Promise<void> {
  const result = await execa(process.execPath, [entry, ...args], {
    all: true,
    reject: false,
  });
  if (result.failed) {
    throw new Error(
      `'portless ${args.join(" ")}' failed: ${(result.all ?? "").trim()}`,
    );
  }
}

/** GAIA's readiness answer through the portless proxy, as a browser asking for hostname gets it. */
function proxiedStatus(hostname: string): Promise<number | null> {
  return new Promise((resolve) => {
    const request = http.get(
      {
        host: "127.0.0.1",
        port: PORTLESS_PROXY_PORT,
        path: "/health/ready",
        headers: { Host: hostname },
        timeout: PROBE_TIMEOUT_MS,
      },
      (response) => {
        response.resume();
        resolve(response.statusCode ?? null);
      },
    );
    request.on("timeout", () => request.destroy());
    request.on("error", () => resolve(null));
  });
}

/** Who answers for a .local name on the network. */
export type LocalNameHolder = "this-computer" | "another-computer" | "nobody";

/** Who the address a name resolved to belongs to, given this computer's own addresses. */
export function localNameHolder(
  resolved: string | null,
  ownAddresses: readonly string[],
): LocalNameHolder {
  if (resolved === null) return "nobody";
  return ownAddresses.includes(resolved) ? "this-computer" : "another-computer";
}

function ownAddresses(): string[] {
  return Object.values(os.networkInterfaces()).flatMap((entries) =>
    (entries ?? []).map((entry) => entry.address),
  );
}

/** The address mDNS resolves hostname to in this family, or null when nothing answers. */
async function resolveHostname(
  hostname: string,
  family: "-4" | "-6",
): Promise<string | null> {
  const result = await execa("avahi-resolve-host-name", [family, hostname], {
    reject: false,
    timeout: PROBE_TIMEOUT_MS,
  });
  if (result.failed) return null;
  const [name, resolved] = result.stdout.trim().split(/\s+/);
  return name === hostname && resolved ? resolved : null;
}

/** Who answers for hostname in this family right now; macOS's dns-sd always announces it as this computer. */
async function currentHolder(
  hostname: string,
  family: "-4" | "-6",
): Promise<LocalNameHolder> {
  if (process.platform !== "linux") return "this-computer";
  return localNameHolder(
    await resolveHostname(hostname, family),
    ownAddresses(),
  );
}

/** Who answers for hostname once mDNS settles after a change. */
async function settledHolder(
  hostname: string,
  family: "-4" | "-6",
): Promise<LocalNameHolder> {
  await settles(
    async () => (await currentHolder(hostname, family)) === "this-computer",
  );
  return currentHolder(hostname, family);
}

/**
 * Announce the name's IPv6 address too (Linux): portless announces only the
 * IPv4 one, and without an AAAA answer macOS waits ~5s per lookup. A network
 * without IPv6 has nothing to announce.
 */
async function announceIpv6(hostname: string, logPath: string): Promise<void> {
  if (process.platform !== "linux") return;
  const address = await currentStableIpv6();
  if (!address) return;
  if ((await resolveHostname(hostname, "-6")) === address) return;
  await installIpv6Publisher(hostname, address, logPath);
  if ((await settledHolder(hostname, "-6")) !== "this-computer") {
    throw new Error(
      `${hostname}'s IPv6 address isn't announced, so Apple devices wait ~5s per lookup${existingLogNote(logPath)}`,
    );
  }
}

async function settles(check: () => Promise<boolean>): Promise<boolean> {
  const deadline = Date.now() + SETTLE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await check()) return true;
    await new Promise((resolve) => setTimeout(resolve, SETTLE_POLL_MS));
  }
  return check();
}

/** Start portless's LAN proxy as a root service, unless one already serves GAIA at hostname (a rerun asks for no sudo). */
async function ensureProxy(
  entry: string,
  hostname: string,
  logPath: string,
): Promise<void> {
  if ((await proxiedStatus(hostname)) === 200) return;
  await ensureAvahi(logPath);
  await runAsRoot(
    process.execPath,
    [entry, "service", "install", "--lan", "--no-tls"],
    logPath,
  );
  // The proxy records its LAN mode once listening; an alias before that gets .localhost.
  const listening = async () => (await proxiedStatus(hostname)) !== null;
  if (!(await settles(listening))) {
    throw new Error(
      `portless's proxy didn't start on port ${PORTLESS_PROXY_PORT}; is another server using it?${existingLogNote(logPath)}`,
    );
  }
}

async function removeAlias(entry: string, name: string): Promise<void> {
  const removal = await execa(
    process.execPath,
    [entry, "alias", "--remove", name],
    { all: true, reject: false },
  );
  // Already gone is the state removal wants.
  if (removal.failed && !(removal.all ?? "").includes("No alias found")) {
    throw new Error(
      `'portless alias --remove ${name}' failed: ${(removal.all ?? "").trim()}`,
    );
  }
}

/**
 * Route name.local to GAIA and announce it; false when another computer on
 * the network answers for the name, so the next one is tried. A name taken
 * from under an earlier run loses its alias, which only collides.
 */
async function claimName(
  entry: string,
  name: string,
  webPort: number,
  logPath: string,
): Promise<boolean> {
  const hostname = hostnameOf(name);
  if ((await currentHolder(hostname, "-4")) === "another-computer") {
    await removeAlias(entry, name);
    return false;
  }
  await runPortless(entry, ["alias", name, String(webPort), "--force"]);
  const servesGaia = async () => (await proxiedStatus(hostname)) === 200;
  if (!(await settles(servesGaia))) {
    throw new Error(
      `portless's proxy on port ${PORTLESS_PROXY_PORT} doesn't route ${hostname} to GAIA on port ${webPort}${existingLogNote(logPath)}`,
    );
  }
  const holder = await settledHolder(hostname, "-4");
  if (holder === "another-computer") {
    await removeAlias(entry, name);
    return false;
  }
  if (holder === "nobody") {
    throw new Error(
      `${hostname} isn't announced on the network; check that avahi-daemon is running${existingLogNote(logPath)}`,
    );
  }
  await announceIpv6(hostname, logPath);
  return true;
}

/**
 * Name GAIA on the network: gaia.local, or when other GAIAs there hold it the
 * next free gaia-2.local … gaia-9.local, checked to resolve to this computer.
 * onProgress hears what it is doing, in plain words. Returns the name now in use.
 * @throws Error saying, in a clause, why no name is set up.
 */
export async function setUpLocalName(
  webPort: number,
  recorded: string | null,
  onProgress: (detail: string) => void = () => undefined,
): Promise<string> {
  const blocker = localNameBlocker(process.version, process.platform, webPort);
  if (blocker) throw new Error(blocker);
  const logPath = newLogPath("local-name");
  onProgress("Getting portless, which serves the name");
  const entry = await ensurePortless(logPath);
  const candidates = localNameCandidates(recorded);
  onProgress("Starting portless on port 80");
  await ensureProxy(entry, hostnameOf(candidates[0] ?? LOCAL_NAME), logPath);
  for (const name of candidates) {
    onProgress(`Checking ${hostnameOf(name)} is free`);
    if (!(await claimName(entry, name, webPort, logPath))) continue;
    if (recorded && recorded !== name) await removeAlias(entry, recorded);
    return name;
  }
  throw new Error(
    `other computers on this network already use ${hostnameOf(LOCAL_NAME)} through ${hostnameOf(`${LOCAL_NAME}-${LAST_LOCAL_NAME_NUMBER}`)}`,
  );
}

/** Remove the name this install claimed (gaia for CLIs that recorded none), and the portless startup service. */
export async function removeLocalName(): Promise<void> {
  const entry = await portlessEntry();
  if (!fs.existsSync(entry)) return;
  await removeAlias(
    entry,
    recordedLocalName(readConfig()?.localName) ?? LOCAL_NAME,
  );
  const logPath = newLogPath("local-name-remove");
  await runAsRoot(process.execPath, [entry, "service", "uninstall"], logPath);
  await removeIpv6Publisher(logPath);
}
