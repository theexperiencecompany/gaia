import {
  DESKTOP_SERVER_FORM_PARAM,
  type DesktopServerFormReason,
} from "@shared/desktop-tools";

import { resolveInstanceAuthMode } from "@/features/auth/api/serverSetupStatusApi";

import { DesktopLoginClient } from "./desktop-login-client";

function isServerFormReason(value: unknown): value is DesktopServerFormReason {
  return value === "choose" || value === "unreachable";
}

/**
 * Desktop login: resolves the instance auth mode on the server (a self-hosted
 * server signs in at its own /login), and whether the desktop app opened this
 * page for its server form; the interactive Electron flow lives in
 * ./desktop-login-client.
 */
export default async function DesktopLoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { [DESKTOP_SERVER_FORM_PARAM]: reason } = await searchParams;
  const isSelfHosted = (await resolveInstanceAuthMode()) === "local";
  return (
    <DesktopLoginClient
      isSelfHosted={isSelfHosted}
      serverFormReason={isServerFormReason(reason) ? reason : null}
    />
  );
}
