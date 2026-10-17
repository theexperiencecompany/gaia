/**
 * Turn a pasted self-host address into the one origin the desktop app may load,
 * and probe that it is a GAIA server the desktop can sign in to. Electron-free:
 * the caller passes the fetch to use (`net.fetch` in the main process).
 *
 * @module server-address
 */

import type { SetupStatusResponse } from "@gaia/shared/api/generated";

/** Public under local auth and served through the self-host proxy's /api/v1. */
const SETUP_STATUS_PATH = "/api/v1/setup/status";

const PROBE_TIMEOUT_MS = 10_000;

const REDIRECT_STATUSES: ReadonlySet<number> = new Set([
  301, 302, 303, 307, 308,
]);

const MAX_REDIRECTS = 5;

const HAS_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

const NOT_GAIA_ERROR =
  "No GAIA server answered at this address. Use the address you open GAIA at in your browser.";

const WORKOS_ERROR =
  "This server signs in through GAIA Cloud accounts, which the desktop app supports only on GAIA Cloud. Open it in your browser instead.";

export type ServerAddressResult =
  | { ok: true; origin: string }
  | { ok: false; error: string };

/** Reduce a pasted address to its origin; a bare hostname means https. */
export function normalizeServerAddress(input: string): ServerAddressResult {
  const trimmed = input.trim();
  if (!trimmed) return { ok: false, error: "Enter your server's address." };

  let url: URL;
  try {
    url = new URL(HAS_SCHEME.test(trimmed) ? trimmed : `https://${trimmed}`);
  } catch {
    return { ok: false, error: "That doesn't look like a web address." };
  }

  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return { ok: false, error: "Use an http:// or https:// address." };
  }
  if (url.username || url.password) {
    return {
      ok: false,
      error: "Remove the username and password from the address.",
    };
  }
  return { ok: true, origin: url.origin };
}

/** Probe `origin`; the result carries the origin the server finally answered on. */
export async function probeSelfHostServer(
  origin: string,
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): Promise<ServerAddressResult> {
  // Redirects are followed by hand: net.fetch leaves Response.url empty, and the
  // window must load the origin the server finally answers on (http→https).
  let url = `${origin}${SETUP_STATUS_PATH}`;
  let response: Response;
  try {
    for (let hops = 0; ; hops++) {
      response = await fetchImpl(url, {
        redirect: "manual",
        signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
      });
      const location = response.headers.get("location");
      if (!REDIRECT_STATUSES.has(response.status) || !location) break;
      if (hops === MAX_REDIRECTS) {
        return { ok: false, error: "The server redirected too many times." };
      }
      url = new URL(location, url).href;
    }
  } catch (err) {
    console.error(`[Main] Server probe to ${origin} failed:`, err);
    return {
      ok: false,
      error: `Couldn't reach ${origin}. Check the address, and include http:// if your server doesn't use HTTPS.`,
    };
  }

  if (response.status === 401) return { ok: false, error: WORKOS_ERROR };
  if (response.status === 404) return { ok: false, error: NOT_GAIA_ERROR };
  if (!response.ok) {
    return {
      ok: false,
      error: `The server answered with HTTP ${response.status}. Check that GAIA is running.`,
    };
  }

  let body: Partial<Pick<SetupStatusResponse, "auth_mode">>;
  try {
    body = (await response.json()) as typeof body;
  } catch {
    return { ok: false, error: NOT_GAIA_ERROR };
  }

  if (body.auth_mode === "workos") return { ok: false, error: WORKOS_ERROR };
  if (body.auth_mode !== "local") return { ok: false, error: NOT_GAIA_ERROR };

  return { ok: true, origin: new URL(url).origin };
}
