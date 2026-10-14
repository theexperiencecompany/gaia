import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIES } from "@/features/auth/constants";
import { opensSetupWizard } from "@/features/setup-wizard/utils/setupWizardRoute";
import { isSelfhostWeb } from "@/lib/selfhost";

import { getSetupStatusServer } from "./serverSetupStatusApi";

/**
 * Where a self-hosted instance sends "/": the setup wizard while it has no
 * admin (the visitor's role is unknown here), else the app or login by
 * session. Null on hosted GAIA, which keeps its landing page; that check
 * never touches the network.
 */
export async function selfhostHomeRedirect(
  request: NextRequest,
): Promise<NextResponse | null> {
  if (!isSelfhostWeb()) return null;
  const setupStatus = await getSetupStatusServer();
  const signedIn = SESSION_COOKIES.some((name) => request.cookies.has(name));
  let target = signedIn ? "/c" : "/login";
  if (setupStatus && opensSetupWizard(setupStatus, undefined)) {
    target = "/setup";
  }
  return NextResponse.redirect(new URL(target, request.url));
}
