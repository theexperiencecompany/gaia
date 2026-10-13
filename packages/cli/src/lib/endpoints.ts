/**
 * Where a local GAIA install answers, per setup mode.
 * @module lib/endpoints
 */

import type { SetupMode } from "./env-parser.js";

/** Default host port of the web app — the self-host single origin. */
export const DEFAULT_WEB_PORT = 3000;

/** Default host port of the natively run developer API. */
export const DEFAULT_API_PORT = 8000;

/** Default host port the self-host proxy publishes for HTTPS (GAIA_DOMAIN). */
export const DEFAULT_HTTPS_PORT = 3443;

/**
 * The API base (`…/api/v1`) on this machine. Self-host serves it through the
 * proxy on the web port; developer mode runs the API on its own port.
 */
export function localApiUrl(
  mode: SetupMode,
  portOverrides: Record<number, number>,
): string {
  const port =
    mode === "selfhost"
      ? (portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT)
      : (portOverrides[DEFAULT_API_PORT] ?? DEFAULT_API_PORT);
  return `http://localhost:${port}/api/v1`;
}
