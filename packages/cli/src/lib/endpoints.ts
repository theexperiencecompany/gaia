/**
 * Where a local GAIA install answers, per setup mode.
 * @module lib/endpoints
 */

import { type NetworkInterfaceInfo, networkInterfaces } from "node:os";
import { readConfig, recordedLocalName } from "./config.js";
import type { SetupMode } from "./env-parser.js";
import { readGaiaDomain } from "./env-writer.js";

/** Default host port of the web app — the self-host single origin. */
export const DEFAULT_WEB_PORT = 3000;

/** Default host port of the natively run developer API. */
export const DEFAULT_API_PORT = 8000;

/** Default host port the self-host proxy publishes for HTTPS (GAIA_DOMAIN). */
export const DEFAULT_HTTPS_PORT = 3443;

/** HTTP's own port, which a URL leaves out. */
const HTTP_DEFAULT_PORT = 80;

/** http://<host>:<port>, without the port when it is HTTP's own. */
function httpOrigin(host: string, port: number): string {
  return port === HTTP_DEFAULT_PORT
    ? `http://${host}`
    : `http://${host}:${port}`;
}

/**
 * Where the API answers on this machine for the detected mode. Self-host
 * serves it through the proxy on the web port; developer mode runs the API on
 * its own port. `/health/ready` lives at this origin.
 */
export function localOrigin(
  mode: SetupMode,
  portOverrides: Record<number, number>,
): string {
  const port =
    mode === "selfhost"
      ? (portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT)
      : (portOverrides[DEFAULT_API_PORT] ?? DEFAULT_API_PORT);
  return httpOrigin("localhost", port);
}

/** The API base (`…/api/v1`) on this machine. */
export function localApiUrl(
  mode: SetupMode,
  portOverrides: Record<number, number>,
): string {
  return `${localOrigin(mode, portOverrides)}/api/v1`;
}

/** Docker's own bridges (docker0, br-<network id>) answer only on this host. */
export const DOCKER_BRIDGE_RE = /^(docker\d+|br-[0-9a-f]+)$/;

/** http://localhost:<port>: where this machine always reaches the web app. */
export function localhostWebUrl(webPort: number): string {
  return httpOrigin("localhost", webPort);
}

/** http://<address>:<port> for each non-loopback IPv4 address of the host. */
export function hostWebUrls(
  webPort: number,
  interfaces: NodeJS.Dict<NetworkInterfaceInfo[]> = networkInterfaces(),
): string[] {
  return Object.entries(interfaces)
    .filter(([name]) => !DOCKER_BRIDGE_RE.test(name))
    .flatMap(([, infos]) => infos ?? [])
    .filter((info) => info.family === "IPv4" && !info.internal)
    .map((info) => httpOrigin(info.address, webPort));
}

/**
 * True when the browser that opens GAIA is on another machine: the CLI runs
 * over SSH, or on a Linux host with no desktop session.
 */
export function browsesFromElsewhere(
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): boolean {
  if (env.SSH_CONNECTION || env.SSH_TTY) return true;
  return platform === "linux" && !env.DISPLAY && !env.WAYLAND_DISPLAY;
}

/**
 * The one address to send a browser to: the domain, else localhost when the
 * browser is on this machine, else the host's first LAN address.
 */
export function primaryWebUrl(
  webPort: number,
  domain: string | undefined,
  interfaces: NodeJS.Dict<NetworkInterfaceInfo[]> = networkInterfaces(),
  remote: boolean = browsesFromElsewhere(),
): string {
  if (domain) return `https://${domain}`;
  const local = localhostWebUrl(webPort);
  if (!remote) return local;
  return hostWebUrls(webPort, interfaces)[0] ?? local;
}

/** The address other devices on the network open GAIA at, for a .local name gaia up set up. */
export function localNameUrl(name: string): string {
  return `http://${name}.local`;
}

/** The one address to send a browser to for the install at repoRoot: its domain, its .local name, else its LAN or local address. */
export function installWebUrl(repoRoot: string, webPort: number): string {
  const domain = readGaiaDomain(repoRoot);
  const localName = recordedLocalName(readConfig()?.localName);
  if (!domain && localName) return localNameUrl(localName);
  return primaryWebUrl(webPort, domain);
}
