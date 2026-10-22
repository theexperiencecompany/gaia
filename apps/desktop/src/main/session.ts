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

import {
  LOCAL_SESSION_COOKIE,
  WOS_SESSION_COOKIE,
} from "@gaia/shared/utils/sessionCookies";
import { session } from "electron";
import { getApiOrigin, isApiOriginSecure } from "./api-origin";
import { getDesktopSettings } from "./settings";

/** The cookie that holds the signed-in session for the server this app uses. */
export function getSessionCookieName(): string {
  return getDesktopSettings().selfHostOrigin
    ? LOCAL_SESSION_COOKIE
    : WOS_SESSION_COOKIE;
}

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
  // A self-hosted window loads the server's own origin, so its session cookie
  // is first-party and its SameSite=Lax persists as-is.
  if (getDesktopSettings().selfHostOrigin) return;
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
