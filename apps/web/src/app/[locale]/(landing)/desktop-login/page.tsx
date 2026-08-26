import { resolveInstanceAuthMode } from "@/features/auth/api/serverSetupStatusApi";

import { DesktopLoginClient } from "./desktop-login-client";

// Mode-switching depends on live instance state (setup/status):
// this page can never be prerendered at build time.
export const dynamic = "force-dynamic";

/**
 * Desktop Login Page
 *
 * Detects an AUTH_MODE=local instance (self-host) via
 * `resolveInstanceAuthMode`: those instances mount no WorkOS OAuth routes, so
 * the desktop browser-handoff URL (`/oauth/login/workos/desktop`) would
 * dead-end. Self-host visitors get an honest "use your browser" state instead;
 * hosted instances render the classic WorkOS flow unchanged.
 */
export default async function DesktopLoginPage() {
  const isSelfHosted = (await resolveInstanceAuthMode()) === "local";
  return <DesktopLoginClient isSelfHosted={isSelfHosted} />;
}
