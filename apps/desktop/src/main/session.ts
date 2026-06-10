/**
 * Session / Cookie Fix Module
 *
 * Patches outgoing `Set-Cookie` headers from the API origin so
 * that the `wos_session` cookie uses `SameSite=None`. Without
 * this fix, Electron's Chromium engine would reject the cookie
 * because the renderer is served from `localhost` (a different
 * origin to the API).
 *
 * @module session
 */

import { session } from "electron";
import { getApiOrigin, isApiOriginSecure } from "./api-origin";

/**
 * Install a `webRequest.onHeadersReceived` filter that rewrites
 * `SameSite` on `wos_session` cookies from the API origin.
 *
 * Only needed for the HTTPS production API (cross-site from localhost);
 * in dev both renderer and API are localhost — same-site — and the
 * API's own `SameSite=Lax` cookies work as-is.
 *
 * Should be called once during startup, after `app.ready`.
 */
export function fixSessionCookies(): void {
  if (!isApiOriginSecure()) return;

  const apiOrigin = getApiOrigin();

  session.defaultSession.webRequest.onHeadersReceived(
    { urls: [`${apiOrigin}/*`] },
    (details, callback) => {
      const headers = { ...details.responseHeaders };

      if (headers["set-cookie"]) {
        headers["set-cookie"] = headers["set-cookie"].map((c: string) => {
          if (!c.includes("wos_session")) return c;
          // SameSite=None is only valid WITH Secure — without it Chromium
          // silently drops the cookie. In dev the API omits Secure (http),
          // so rotated sessions were being lost and the stale cookie kept
          // 401-ing. localhost is a trustworthy origin, so Secure cookies
          // are accepted over http there.
          let patched = c.replace(/SameSite=\w+/i, "SameSite=None");
          if (!/;\s*Secure/i.test(patched)) patched += "; Secure";
          return patched;
        });
      }

      callback({ responseHeaders: headers });
    },
  );
}
