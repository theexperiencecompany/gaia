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

/** Name of the WorkOS session cookie the app authenticates with. The bridge
 * logout hook watches this same cookie on `session.defaultSession` to detect
 * sign-out, so both sites key off one constant rather than a magic string. */
export const WOS_SESSION_COOKIE = "wos_session";

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
          if (!c.includes(WOS_SESSION_COOKIE)) return c;
          // SameSite=None needs Secure or Chromium drops the cookie; the dev
          // API omits Secure over http, which lost rotated sessions to stale
          // 401s. localhost accepts Secure cookies over http, so we add it.
          let patched = c.replace(/SameSite=\w+/i, "SameSite=None");
          if (!/;\s*Secure/i.test(patched)) patched += "; Secure";
          return patched;
        });
      }

      callback({ responseHeaders: headers });
    },
  );
}
