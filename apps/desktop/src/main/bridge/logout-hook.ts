// Wires the bridge's user-binding (R5) into the app's session lifecycle. The
// desktop main process has no logout signal today, so we watch the WorkOS
// session cookie on session.defaultSession — the same jar pair()/self-pair fetch
// with — and tear the device down when it is genuinely removed (sign-out).
//
// Registered once from index.ts at startup. Also runs one launch-time
// reconciliation: a logout or account switch that happened while the app was
// closed fires no cookie "changed" event on the next launch, so start()'s guard
// alone would miss it until the tunnel is next started.

import { session } from "electron";
import { WOS_SESSION_COOKIE } from "../session";
import { getBridgeHost } from "./host";

/** Cookie-change causes that are NOT a sign-out: an "overwrite" (and its
 * "expired-overwrite" sibling) is the WorkOS session rotating — Chromium fires a
 * removal for the old value immediately followed by the new one. Tearing down on
 * those would unpair the device on every routine session refresh. */
const ROTATION_CAUSES = new Set(["overwrite", "expired-overwrite"]);

export function registerBridgeLogoutHook(): void {
  const host = getBridgeHost();

  session.defaultSession.cookies.on(
    "changed",
    (_event, cookie, cause, removed) => {
      if (cookie.name !== WOS_SESSION_COOKIE) return;
      if (!removed || ROTATION_CAUSES.has(cause)) return;
      void host
        .unbindAndReset("logout")
        .catch((error) =>
          console.error("[bridge] logout teardown failed:", error),
        );
    },
  );

  void host
    .reconcileUserBinding()
    .catch((error) =>
      console.error("[bridge] launch reconcile failed:", error),
    );
}
