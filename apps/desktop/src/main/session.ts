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

/**
 * Install a `webRequest.onHeadersReceived` filter that rewrites
 * `SameSite` on `wos_session` cookies from the API origin.
 *
 * Should be called once during startup, after `app.ready`.
 */
export function fixSessionCookies(): void {
  const apiOrigin = (
    process.env.NEXT_PUBLIC_API_BASE_URL || "https://api.heygaia.io"
  ).replace(/\/api\/v1\/?$/, "");

  session.defaultSession.webRequest.onHeadersReceived(
    { urls: [`${apiOrigin}/*`] },
    (details, callback) => {
      const headers = { ...details.responseHeaders };

      if (headers["set-cookie"]) {
        headers["set-cookie"] = headers["set-cookie"].map((c: string) =>
          c.includes("wos_session")
            ? c.replace(/SameSite=\w+/i, "SameSite=None")
            : c,
        );
      }

      callback({ responseHeaders: headers });
    },
  );
}
