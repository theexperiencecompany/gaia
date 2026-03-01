import { NextResponse } from "next/server";

/**
 * Electron identity check endpoint.
 *
 * The desktop main process calls this before loading the app to confirm
 * it is talking to the GAIA web server and not some other service that
 * happens to be running on the same port.
 */
export function GET(): NextResponse {
  return NextResponse.json({ app: "gaia" });
}
