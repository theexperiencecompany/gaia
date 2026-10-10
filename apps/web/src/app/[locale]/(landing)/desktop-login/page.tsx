import { resolveInstanceAuthMode } from "@/features/auth/api/serverSetupStatusApi";

import { DesktopLoginClient } from "./desktop-login-client";

// Mode-switching depends on live instance state (setup/status):
// this page can never be prerendered at build time.
export const dynamic = "force-dynamic";

/**
 * Desktop login: resolves the instance auth mode on the server (self-host
 * mounts no WorkOS routes, so those visitors get an honest "use your browser"
 * state); the interactive Electron flow lives in ./desktop-login-client.
 */
export default async function DesktopLoginPage() {
  const isSelfHosted = (await resolveInstanceAuthMode()) === "local";
  return <DesktopLoginClient isSelfHosted={isSelfHosted} />;
}
