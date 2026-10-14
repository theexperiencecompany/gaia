import { type NextRequest, NextResponse } from "next/server";

import { isSelfhostWeb } from "@/lib/selfhost";

import { getSetupStatusServer } from "./serverSetupStatusApi";

/** The session cookie the API sets on sign-in. */
const SESSION_COOKIE = "wos_session";

/**
 * Where a self-hosted instance sends "/": the setup wizard while setup is
 * owed, else the app or login by session. Null on hosted GAIA, which keeps
 * its landing page; that check never touches the network.
 */
export async function selfhostHomeRedirect(
  request: NextRequest,
): Promise<NextResponse | null> {
  if (!isSelfhostWeb()) return null;
  const setupStatus = await getSetupStatusServer();
  const signedIn = request.cookies.has(SESSION_COOKIE);
  let target = signedIn ? "/c" : "/login";
  if (setupStatus?.needs_setup) target = "/setup";
  return NextResponse.redirect(new URL(target, request.url));
}
