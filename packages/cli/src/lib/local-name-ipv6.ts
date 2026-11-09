/**
 * gaia.local's IPv6 (AAAA) record on Linux. portless announces only the
 * IPv4 address, and macOS then waits ~5s per lookup for the AAAA answer that
 * never comes; a root startup unit running avahi-publish-address for the
 * host's stable IPv6 address answers it. The address is read at install
 * time, so a changed prefix is re-read by the next `gaia up`; until then
 * clients fall back to IPv4 at once.
 * @module lib/local-name-ipv6
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execa } from "execa";
import { DOCKER_BRIDGE_RE } from "./endpoints.js";
import { runAsRoot } from "./root-command.js";

const UNIT_NAME = "gaia-local-name-ipv6.service";
const UNIT_PATH = `/etc/systemd/system/${UNIT_NAME}`;

/** Address flags that make an address a poor name: it rotates, is leaving, or isn't usable yet. */
const UNSTABLE_FLAGS = ["temporary", "deprecated", "tentative", "dadfailed"];

/** The interface of the default route, from `ip -o route show default`. */
export function defaultRouteDevice(routes: string): string | null {
  return /\bdev (\S+)/.exec(routes)?.[1] ?? null;
}

/**
 * The address to announce, from `ip -6 -o addr show scope global`: a stable
 * one on the default route's interface first, else on any other non-Docker one.
 */
export function stableIpv6(
  addresses: string,
  defaultDevice: string | null,
): string | null {
  const candidates = addresses
    .split("\n")
    .map((line) =>
      /^\d+:\s+(\S+)\s+inet6\s+([0-9a-f:]+)\/\d+\s+(.*)$/.exec(line),
    )
    .filter((match): match is RegExpExecArray => match !== null)
    .map(([, device = "", address = "", flags = ""]) => ({
      device,
      address,
      flags,
    }))
    .filter(
      ({ device, flags }) =>
        !DOCKER_BRIDGE_RE.test(device) &&
        !UNSTABLE_FLAGS.some((flag) => flags.split(/\s+/).includes(flag)),
    );
  const preferred = candidates.find(({ device }) => device === defaultDevice);
  return (preferred ?? candidates[0])?.address ?? null;
}

/** The systemd unit that keeps hostname's AAAA record published. */
export function ipv6PublisherUnit(
  avahiPublish: string,
  hostname: string,
  address: string,
): string {
  return `[Unit]
Description=Announce ${hostname}'s IPv6 address over mDNS (GAIA)
Requires=avahi-daemon.service
After=avahi-daemon.service network-online.target
Wants=network-online.target

[Service]
ExecStart=${avahiPublish} -R ${hostname} ${address}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
`;
}

/** This host's stable IPv6 address, or null when it has none to announce. */
export async function currentStableIpv6(): Promise<string | null> {
  const [addresses, routes] = await Promise.all([
    execa("ip", ["-6", "-o", "addr", "show", "scope", "global"]),
    execa("ip", ["-o", "route", "show", "default"]),
  ]);
  return stableIpv6(addresses.stdout, defaultRouteDevice(routes.stdout));
}

/** Install (or re-point) the unit announcing hostname at address, and start it. */
export async function installIpv6Publisher(
  hostname: string,
  address: string,
  logPath: string,
): Promise<void> {
  const { stdout } = await execa("sh", [
    "-c",
    "command -v avahi-publish-address",
  ]);
  const staged = path.join(os.tmpdir(), UNIT_NAME);
  fs.writeFileSync(staged, ipv6PublisherUnit(stdout.trim(), hostname, address));
  await runAsRoot("install", ["-m", "644", staged, UNIT_PATH], logPath);
  fs.rmSync(staged, { force: true });
  await runAsRoot("systemctl", ["daemon-reload"], logPath);
  await runAsRoot("systemctl", ["enable", UNIT_NAME], logPath);
  await runAsRoot("systemctl", ["restart", UNIT_NAME], logPath);
}

/** Stop and delete the unit, when an earlier run installed it. */
export async function removeIpv6Publisher(logPath: string): Promise<void> {
  if (!fs.existsSync(UNIT_PATH)) return;
  await runAsRoot("systemctl", ["disable", "--now", UNIT_NAME], logPath);
  await runAsRoot("rm", ["-f", UNIT_PATH], logPath);
  await runAsRoot("systemctl", ["daemon-reload"], logPath);
}
