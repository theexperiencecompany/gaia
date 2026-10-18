/**
 * gaia.local: names a self-host install on its home or office network with
 * portless (https://github.com/vercel-labs/portless). A root startup service
 * runs portless's proxy in LAN mode on plain HTTP port 80 and announces
 * gaia.local over mDNS (avahi on Linux, dns-sd on macOS); an alias routes the
 * name to GAIA's web port. Plain HTTP, so other devices meet no certificate.
 * @module lib/local-name
 */

import * as fs from "node:fs";
import * as http from "node:http";
import * as path from "node:path";
import { execa } from "execa";
import { newLogPath } from "./logs.js";
import { isDebianAptLinux } from "./prerequisite-install.js";
import { runAsRoot } from "./root-command.js";

const LOCAL_NAME = "gaia";
const LOCAL_HOSTNAME = `${LOCAL_NAME}.local`;

/** The address other devices on the network open GAIA at. */
export const LOCAL_NAME_URL = `http://${LOCAL_HOSTNAME}`;

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

/** Why gaia.local can't be set up on this computer, or null when it can. */
export function localNameBlocker(
  nodeVersion: string,
  platform: NodeJS.Platform,
): string | null {
  if (platform !== "linux" && platform !== "darwin") {
    return "it works only on Linux and macOS";
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

function installedPortlessVersion(entry: string): string | null {
  const manifest = path.join(path.dirname(entry), "..", "package.json");
  if (!fs.existsSync(manifest)) return null;
  return (JSON.parse(fs.readFileSync(manifest, "utf-8")) as { version: string })
    .version;
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

/** GAIA's readiness answer through the portless proxy, as a browser asking for gaia.local gets it. */
function proxiedStatus(): Promise<number | null> {
  return new Promise((resolve) => {
    const request = http.get(
      {
        host: "127.0.0.1",
        port: PORTLESS_PROXY_PORT,
        path: "/health/ready",
        headers: { Host: LOCAL_HOSTNAME },
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

async function servesGaia(): Promise<boolean> {
  return (await proxiedStatus()) === 200;
}

async function proxyListening(): Promise<boolean> {
  return (await proxiedStatus()) !== null;
}

/** Whether the network can resolve gaia.local; macOS's dns-sd always announces it. */
async function announced(): Promise<boolean> {
  if (process.platform !== "linux") return true;
  const result = await execa(
    "avahi-resolve-host-name",
    ["-4", LOCAL_HOSTNAME],
    { reject: false, timeout: PROBE_TIMEOUT_MS },
  );
  return !result.failed && result.stdout.includes(LOCAL_HOSTNAME);
}

async function settles(check: () => Promise<boolean>): Promise<boolean> {
  const deadline = Date.now() + SETTLE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await check()) return true;
    await new Promise((resolve) => setTimeout(resolve, SETTLE_POLL_MS));
  }
  return check();
}

/**
 * Point gaia.local at GAIA's web port and check that the proxy serves GAIA
 * and the network can resolve the name. The root service is installed only
 * when no running proxy serves GAIA yet, so a rerun asks for no sudo.
 * @throws Error saying, in a clause, why gaia.local isn't set up.
 */
export async function setUpLocalName(webPort: number): Promise<void> {
  const blocker = localNameBlocker(process.version, process.platform);
  if (blocker) throw new Error(blocker);
  const logPath = newLogPath("local-name");
  const entry = await ensurePortless(logPath);
  if (!(await servesGaia())) {
    await ensureAvahi(logPath);
    await runAsRoot(
      process.execPath,
      [entry, "service", "install", "--lan", "--no-tls"],
      logPath,
    );
    // The proxy records its LAN mode once listening; an alias before that gets .localhost.
    if (!(await settles(proxyListening))) {
      throw new Error(
        `portless's proxy didn't start on port ${PORTLESS_PROXY_PORT}; is another server using it? (log: ${logPath})`,
      );
    }
  }
  // After the service, so the alias takes the LAN proxy's .local name.
  await runPortless(entry, ["alias", LOCAL_NAME, String(webPort), "--force"]);
  if (!(await settles(servesGaia))) {
    throw new Error(
      `portless's proxy on port ${PORTLESS_PROXY_PORT} doesn't route ${LOCAL_HOSTNAME} to GAIA on port ${webPort} (log: ${logPath})`,
    );
  }
  if (!(await settles(announced))) {
    throw new Error(
      `${LOCAL_HOSTNAME} isn't announced on the network; check that avahi-daemon is running (log: ${logPath})`,
    );
  }
}

/** Remove the gaia.local alias and the portless startup service an earlier run installed. */
export async function removeLocalName(): Promise<void> {
  const entry = await portlessEntry();
  if (!fs.existsSync(entry)) return;
  const removal = await execa(
    process.execPath,
    [entry, "alias", "--remove", LOCAL_NAME],
    { all: true, reject: false },
  );
  // Already gone is the state removal wants.
  if (removal.failed && !(removal.all ?? "").includes("No alias found")) {
    throw new Error(
      `'portless alias --remove ${LOCAL_NAME}' failed: ${(removal.all ?? "").trim()}`,
    );
  }
  await runAsRoot(
    process.execPath,
    [entry, "service", "uninstall"],
    newLogPath("local-name-remove"),
  );
}
