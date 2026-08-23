import { getSetupStatusServer } from "@/features/auth/api/serverSetupStatusApi";

import { DesktopLoginClient } from "./desktop-login-client";

// Mode-switching depends on live instance state (setup/status):
// this page can never be prerendered at build time.
export const dynamic = "force-dynamic";

/**
 * Desktop Login Page
 *
 * Probes the instance's public `GET /setup/status` to detect AUTH_MODE=local
 * (self-host): those instances mount no WorkOS OAuth routes, so the desktop
 * browser-handoff URL (`/oauth/login/workos/desktop`) would dead-end. Self-host
 * visitors get an honest "use your browser" state instead. Hosted instances
 * reject the probe pre-auth (or don't mount it), which resolves to `null` —
 * the classic WorkOS flow renders unchanged.
 */
export default async function DesktopLoginPage() {
  const setupStatus = await getSetupStatusServer();
  return (
    <DesktopLoginClient isSelfHosted={setupStatus?.auth_mode === "local"} />
  );
}
