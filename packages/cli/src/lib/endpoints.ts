/**
 * Where a local GAIA install answers, per setup mode.
 * @module lib/endpoints
 */

import { type NetworkInterfaceInfo, networkInterfaces } from "node:os";
import type { SetupMode } from "./env-parser.js";

/** Default host port of the web app — the self-host single origin. */
export const DEFAULT_WEB_PORT = 3000;

/** Default host port of the natively run developer API. */
export const DEFAULT_API_PORT = 8000;

/** Default host port the self-host proxy publishes for HTTPS (GAIA_DOMAIN). */
export const DEFAULT_HTTPS_PORT = 3443;

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
  return `http://localhost:${port}`;
}

/** The API base (`…/api/v1`) on this machine. */
export function localApiUrl(
  mode: SetupMode,
  portOverrides: Record<number, number>,
): string {
  return `${localOrigin(mode, portOverrides)}/api/v1`;
}

/** Docker's own bridges (docker0, br-<network id>) answer only on this host. */
const DOCKER_BRIDGE_RE = /^(docker\d+|br-[0-9a-f]+)$/;

/**
 * Every address a browser can open the self-host web app at: https://<domain>
 * when one is set, localhost, then each non-loopback IPv4 address of the host.
 */
export function reachableWebUrls(
  webPort: number,
  domain: string | undefined,
  interfaces: NodeJS.Dict<NetworkInterfaceInfo[]> = networkInterfaces(),
): string[] {
  const hostAddresses = Object.entries(interfaces)
    .filter(([name]) => !DOCKER_BRIDGE_RE.test(name))
    .flatMap(([, infos]) => infos ?? [])
    .filter((info) => info.family === "IPv4" && !info.internal)
    .map((info) => `http://${info.address}:${webPort}`);
  return [
    ...(domain ? [`https://${domain}`] : []),
    `http://localhost:${webPort}`,
    ...hostAddresses,
  ];
}
